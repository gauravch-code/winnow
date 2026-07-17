"""Nightly retraining core.

Design contract:

- Read all owner-scoped ``training_examples`` from the DB.
- Combine with the seed corpus (200 emails, ground-truth labels) so the
  model never regresses on well-known signal when the user has only
  labeled a handful of new emails.
- Stratified 80/20 split.
- Train ``LogisticRegression`` under the same hyperparameters as the
  original baseline (Step 4c).
- Evaluate the new model AND the currently-active model on the same
  holdout, then apply guardrails.
- If deployed: rotate artifacts, insert metrics row with deployed=True.
- If rejected: insert metrics row with deployed=False + reason. Do not
  touch artifacts.

Kept as a plain class (no injected services) because the two moving
parts — DB session and classifier factory — are already boring-obvious
inputs. A service registry would be premature.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable

import numpy as np
import sklearn
import structlog
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select
from sqlalchemy.orm import Session

from winnow_api.classifier import Classifier
from winnow_api.classifier.embeddings import embed_batch, embedding_dim
from winnow_api.classifier.features import (
    ENGINEERED_FEATURE_NAMES,
    extract_features,
    to_vector,
)
from winnow_api.classifier.model import TrainedModel
from winnow_api.db.models import ClassifierMetric, Email, TrainingExample, User
from winnow_api.learning.artifacts import ARTIFACT_PATH, save_new_active
from winnow_seed_data.seed_email_schema import SeedEmail

log = structlog.get_logger(__name__)

LANE_ORDER = ["needs_you", "informational", "hidden"]


class RetrainOutcome(str, Enum):
    DEPLOYED = "deployed"
    REJECTED_INSUFFICIENT_EXAMPLES = "rejected_insufficient_examples"
    REJECTED_INSUFFICIENT_CLASSES = "rejected_insufficient_classes"
    REJECTED_REGRESSION = "rejected_regression"
    NO_ACTIVE_MODEL_PATH = "no_active_model_path"


@dataclass
class RetrainReport:
    outcome: RetrainOutcome
    n_training_examples: int
    n_holdout: int
    holdout_accuracy: float | None
    previous_active_accuracy: float | None
    per_lane_metrics: dict = field(default_factory=dict)
    rejection_reason: str | None = None
    classifier_version: str | None = None


class Retrainer:
    def __init__(
        self,
        db: Session,
        user: User,
        seed_dir: Path,
        min_examples: int = 20,
        regression_threshold: float = 0.05,
        holdout_fraction: float = 0.2,
        random_state: int = 42,
    ):
        self._db = db
        self._user = user
        self._seed_dir = seed_dir
        self._min_examples = min_examples
        self._regression_threshold = regression_threshold
        self._holdout_fraction = holdout_fraction
        self._random_state = random_state

    def run(self, *, force: bool = False, dry_run: bool = False) -> RetrainReport:
        # --- gather data --------------------------------------------------
        seed_rows = _load_seed_rows(self._seed_dir)
        user_rows = self._db.execute(
            select(TrainingExample, Email)
            .join(Email, Email.id == TrainingExample.email_id)
            .where(TrainingExample.user_id == self._user.id)
        ).all()

        n_user = len(user_rows)
        n_total = len(seed_rows) + n_user
        log.info(
            "retrain_started",
            user_id=str(self._user.id),
            n_seed=len(seed_rows),
            n_user_labeled=n_user,
        )

        if n_user < self._min_examples:
            report = RetrainReport(
                outcome=RetrainOutcome.REJECTED_INSUFFICIENT_EXAMPLES,
                n_training_examples=n_total,
                n_holdout=0,
                holdout_accuracy=None,
                previous_active_accuracy=None,
                rejection_reason=(
                    f"Only {n_user} user-labeled example(s); need at least "
                    f"{self._min_examples} before retraining is worth the risk."
                ),
            )
            self._log_metrics(report, deployed=False)
            log.info("retrain_skipped", reason=report.rejection_reason)
            return report

        # --- build feature matrix ----------------------------------------
        X_seed, y_seed = _seed_matrix(seed_rows)
        X_user, y_user = _user_matrix(user_rows)
        X = np.vstack([X_seed, X_user])
        y = np.concatenate([y_seed, y_user])

        distinct = set(y.tolist())
        if len(distinct) < 2:
            report = RetrainReport(
                outcome=RetrainOutcome.REJECTED_INSUFFICIENT_CLASSES,
                n_training_examples=n_total,
                n_holdout=0,
                holdout_accuracy=None,
                previous_active_accuracy=None,
                rejection_reason=(
                    f"Training data has {len(distinct)} distinct label(s); "
                    "need at least 2 to train a multi-class model."
                ),
            )
            self._log_metrics(report, deployed=False)
            return report

        X_train, X_holdout, y_train, y_holdout = train_test_split(
            X,
            y,
            test_size=self._holdout_fraction,
            stratify=y,
            random_state=self._random_state,
        )

        pipeline = _build_pipeline()
        pipeline.fit(X_train, y_train)
        _canonicalize_classes(pipeline)

        # --- evaluate new + current on same holdout ---------------------
        new_holdout_pred = pipeline.predict(X_holdout)
        new_accuracy = float((new_holdout_pred == y_holdout).mean())
        per_lane = _per_lane(y_holdout, new_holdout_pred)

        prev_accuracy = _evaluate_active(X_holdout, y_holdout)
        version_label = f"retrain-{dt.datetime.now(dt.timezone.utc).isoformat()}"

        report = RetrainReport(
            outcome=RetrainOutcome.DEPLOYED,
            n_training_examples=n_total,
            n_holdout=int(X_holdout.shape[0]),
            holdout_accuracy=new_accuracy,
            previous_active_accuracy=prev_accuracy,
            per_lane_metrics=per_lane,
            classifier_version=version_label,
        )

        # --- guardrail: regression check --------------------------------
        if (
            prev_accuracy is not None
            and not force
            and new_accuracy < prev_accuracy - self._regression_threshold
        ):
            report.outcome = RetrainOutcome.REJECTED_REGRESSION
            report.rejection_reason = (
                f"New model accuracy {new_accuracy:.3f} regressed more than "
                f"{self._regression_threshold:.2f} vs current {prev_accuracy:.3f}. "
                "Use --force to deploy anyway."
            )
            self._log_metrics(report, deployed=False)
            log.warning(
                "retrain_rejected_regression",
                new_accuracy=new_accuracy,
                previous_active_accuracy=prev_accuracy,
            )
            return report

        # --- deploy (unless dry-run) ------------------------------------
        if dry_run:
            log.info(
                "retrain_dry_run",
                new_accuracy=new_accuracy,
                previous_active_accuracy=prev_accuracy,
            )
            report.outcome = RetrainOutcome.DEPLOYED  # would have been
            return report

        trained = TrainedModel(
            pipeline=pipeline,
            lane_classes=LANE_ORDER,
            engineered_feature_names=ENGINEERED_FEATURE_NAMES,
            embedding_dim=embedding_dim(),
            sklearn_version=sklearn.__version__,
            trained_at_iso=dt.datetime.now(dt.timezone.utc).isoformat(),
            training_metrics={"holdout_accuracy": new_accuracy, **per_lane_flat(per_lane)},
            training_size=int(X_train.shape[0]),
        )
        save_new_active(trained)
        self._log_metrics(report, deployed=True)
        log.info(
            "retrain_deployed",
            new_accuracy=new_accuracy,
            previous_active_accuracy=prev_accuracy,
        )
        return report

    def _log_metrics(self, report: RetrainReport, *, deployed: bool) -> None:
        row = ClassifierMetric(
            user_id=self._user.id,
            classifier_version=report.classifier_version or "n/a",
            n_training_examples=report.n_training_examples,
            n_holdout=report.n_holdout,
            holdout_accuracy=report.holdout_accuracy if report.holdout_accuracy is not None else 0.0,
            per_lane_metrics=report.per_lane_metrics or {},
            previous_active_accuracy=report.previous_active_accuracy,
            deployed=deployed,
            rejection_reason=report.rejection_reason,
        )
        self._db.add(row)
        self._db.commit()


# --- helpers ---------------------------------------------------------------


def _load_seed_rows(seed_dir: Path) -> list[SeedEmail]:
    return [
        SeedEmail.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(seed_dir.glob("seed_*.json"))
    ]


def _seed_matrix(seeds: list[SeedEmail]) -> tuple[np.ndarray, np.ndarray]:
    engineered = np.asarray(
        [to_vector(extract_features(s)) for s in seeds], dtype=np.float32
    )
    embeddings = embed_batch([(s.subject, s.body_text) for s in seeds])
    X = np.hstack([engineered, embeddings])
    y = np.asarray([s.ground_truth_lane for s in seeds])
    return X, y


def _user_matrix(rows: Iterable[tuple[TrainingExample, Email]]) -> tuple[np.ndarray, np.ndarray]:
    feats: list[list[float]] = []
    embs: list[np.ndarray] = []
    labels: list[str] = []
    for training_example, email in rows:
        # Prefer the cached feature dict; fall back to recomputing.
        if training_example.features:
            feats.append([training_example.features[n] for n in ENGINEERED_FEATURE_NAMES])
        else:
            feats.append(to_vector(extract_features(email)))
        if training_example.embedding and training_example.embedding_dim:
            arr = np.frombuffer(
                training_example.embedding,
                dtype=np.dtype(training_example.embedding_dtype or "float32"),
                count=training_example.embedding_dim,
            )
        else:
            arr = embed_batch([(email.subject, email.body_text)])[0]
        embs.append(arr)
        labels.append(training_example.label)

    if not feats:
        return (
            np.zeros((0, len(ENGINEERED_FEATURE_NAMES) + embedding_dim()), dtype=np.float32),
            np.asarray([], dtype=object),
        )

    engineered = np.asarray(feats, dtype=np.float32)
    embeddings = np.vstack(embs).astype(np.float32)
    return np.hstack([engineered, embeddings]), np.asarray(labels)


def _build_pipeline() -> Pipeline:
    # Same hyperparameters as the Step 4c baseline.
    return Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    max_iter=2000,
                    class_weight="balanced",
                    C=1.0,
                    solver="lbfgs",
                    random_state=42,
                ),
            ),
        ]
    )


def _canonicalize_classes(pipeline: Pipeline) -> None:
    clf = pipeline.named_steps["clf"]
    if list(clf.classes_) == LANE_ORDER:
        return
    idx = [list(clf.classes_).index(c) for c in LANE_ORDER]
    clf.classes_ = np.asarray(LANE_ORDER)
    clf.coef_ = clf.coef_[idx]
    clf.intercept_ = clf.intercept_[idx]


def _per_lane(y_true, y_pred) -> dict:
    report = classification_report(
        y_true, y_pred, labels=LANE_ORDER, output_dict=True, zero_division=0
    )
    return {lane: {k: report[lane][k] for k in ("precision", "recall", "f1-score")} for lane in LANE_ORDER}


def per_lane_flat(per_lane: dict) -> dict:
    out: dict[str, float] = {}
    for lane, metrics in per_lane.items():
        for name, value in metrics.items():
            out[f"{lane}_{name.replace('-score','')}"] = float(value)
    return out


def _evaluate_active(X_holdout: np.ndarray, y_holdout: np.ndarray) -> float | None:
    """Score the currently-active on the same holdout, if it exists.

    Returns None when this is the first retrain (no artifact yet), which
    the caller treats as "no regression check possible — deploy."
    """
    if not ARTIFACT_PATH.exists():
        return None
    active = Classifier.load(ARTIFACT_PATH)
    pipeline = active.model.pipeline
    pred = pipeline.predict(X_holdout)
    return float((pred == y_holdout).mean())
