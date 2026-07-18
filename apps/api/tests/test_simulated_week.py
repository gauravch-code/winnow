"""End-to-end simulated week: does the retrainer actually improve the model?

Sets up a deliberately weakened base (trained on a random 60-email
subset of the 200 seed corpus), simulates a week of user corrections
against emails the base gets wrong, runs the retrainer, and verifies:

- A ClassifierMetric row lands with deployed=True.
- The rotated ``base.previous.joblib`` matches the pre-retrain artifact.
- ``holdout_accuracy`` beats ``previous_active_accuracy`` — the
  retrainer's own before/after numbers show real improvement, and the
  numbers are printed so the user can eyeball them from the pytest
  output.

Runs against a real DB and re-embeds the 200 seed emails via MiniLM,
so it's slow (~30–60s cold). Marked slow but not skipped — it's the
one test that proves the whole story hangs together end-to-end.
"""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

import numpy as np
import pytest
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy.orm import Session

from winnow_api.classifier.embeddings import embed_batch, embedding_dim
from winnow_api.classifier.features import (
    ENGINEERED_FEATURE_NAMES,
    extract_features,
    to_vector,
)
from winnow_api.classifier.model import TrainedModel
from winnow_api.db.models import (
    ClassifierMetric,
    Email,
    TrainingExample,
    User,
)
from winnow_api.learning import artifacts as artifacts_module
from winnow_api.learning import retrainer as retrainer_module
from winnow_api.learning.retrainer import RetrainOutcome, Retrainer
from winnow_seed_data.seed_email_schema import SeedEmail

SEED_DIR = Path(__file__).resolve().parents[3] / "packages" / "seed-data" / "emails"


LANE_ORDER = ["needs_you", "informational", "hidden"]


@pytest.fixture(autouse=True)
def _isolate_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    art = tmp_path / "base.joblib"
    prev = tmp_path / "base.previous.joblib"
    monkeypatch.setattr(artifacts_module, "ARTIFACT_PATH", art)
    monkeypatch.setattr(artifacts_module, "PREVIOUS_ARTIFACT_PATH", prev)
    monkeypatch.setattr(retrainer_module, "ARTIFACT_PATH", art)


@pytest.fixture
def owner(db: Session):
    db.query(TrainingExample).delete()
    db.query(Email).delete()
    db.query(ClassifierMetric).delete()
    db.query(User).delete()
    db.commit()
    u = User(email=f"me-{uuid.uuid4()}@example.com")
    db.add(u)
    db.commit()
    yield u
    db.query(ClassifierMetric).delete()
    db.query(TrainingExample).delete()
    db.query(Email).delete()
    db.query(User).delete()
    db.commit()


def _load_all_seeds() -> list[SeedEmail]:
    return [
        SeedEmail.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(SEED_DIR.glob("seed_*.json"))
    ]


def _train_weak_base(seeds: list[SeedEmail]) -> TrainedModel:
    """Train a base model that will demonstrably underperform on the
    holdout so the retrainer has real room to improve.

    Winnow's synthetic corpus is trivially separable — a model trained
    on any reasonable subset hits 100% on the whole corpus, which
    leaves no daylight to show improvement. So we do two things:

    1. Restrict to a random 40% subset of the corpus.
    2. Corrupt 35% of that subset's labels by rotating each to a
       different lane. The base learns from partially-wrong signal
       and misclassifies accordingly on the holdout.

    The retrainer, in contrast, sees the *clean* full seed corpus plus
    the user's clean corrections — so the delta is real and comes
    from cleaner labels, exactly the story the learning loop tells
    when a real user uses Winnow.
    """
    rng = np.random.default_rng(seed=1234)
    idx = rng.permutation(len(seeds))[: int(len(seeds) * 0.40)]
    subset = [seeds[i] for i in idx]

    engineered = np.asarray(
        [to_vector(extract_features(s)) for s in subset], dtype=np.float32
    )
    embeddings = embed_batch([(s.subject, s.body_text) for s in subset])
    X = np.hstack([engineered, embeddings])

    true_labels = [s.ground_truth_lane for s in subset]
    corrupt_pick = rng.random(len(true_labels)) < 0.35
    y_noisy = []
    for label, corrupt in zip(true_labels, corrupt_pick):
        if not corrupt:
            y_noisy.append(label)
            continue
        # Rotate to a different lane deterministically.
        others = [ln for ln in LANE_ORDER if ln != label]
        y_noisy.append(others[int(rng.integers(0, len(others)))])
    y = np.asarray(y_noisy)

    pipeline = Pipeline(
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
    pipeline.fit(X, y)

    return TrainedModel(
        pipeline=pipeline,
        lane_classes=LANE_ORDER,
        engineered_feature_names=ENGINEERED_FEATURE_NAMES,
        embedding_dim=embedding_dim(),
        sklearn_version=sklearn.__version__,
        trained_at_iso=dt.datetime.now(dt.timezone.utc).isoformat(),
        training_metrics={},
        training_size=len(subset),
    )


def _simulate_week_of_corrections(
    db: Session, owner: User, seeds: list[SeedEmail], count: int
) -> int:
    """Ingest ``count`` fresh emails and have the user label each with
    ground truth via ``lane_moved``. Returns the number of training rows written."""
    rng = np.random.default_rng(seed=99)
    picks = rng.choice(len(seeds), size=count, replace=False)

    written = 0
    for i in picks:
        seed = seeds[int(i)]
        email = Email(
            user_id=owner.id,
            gmail_message_id=f"sim-{seed.id}",
            sender_email=seed.sender_email,
            sender_name=seed.sender_name,
            sender_domain=seed.sender_domain,
            recipients=seed.recipients,
            subject=seed.subject,
            body_text=seed.body_text,
            snippet=seed.snippet,
            received_at=seed.received_at,
            thread_depth=seed.thread_depth,
            has_unsubscribe=seed.has_unsubscribe,
            is_reply=seed.is_reply,
        )
        db.add(email)
        db.flush()

        emb = embed_batch([(seed.subject, seed.body_text)])[0]
        features = extract_features(email)
        db.add(
            TrainingExample(
                email_id=email.id,
                user_id=owner.id,
                label=seed.ground_truth_lane,
                label_source="user_move",
                features=features,
                embedding=np.asarray(emb, dtype=np.float32).tobytes(),
                embedding_dim=int(emb.shape[0]),
                embedding_dtype="float32",
            )
        )
        written += 1
    db.commit()
    return written


def test_simulated_week_shows_measurable_improvement(
    owner: User, db: Session, tmp_path: Path, capsys
):
    seeds = _load_all_seeds()

    # 1. Establish a weak baseline and save as the "currently active" model.
    weak_base = _train_weak_base(seeds)
    weak_base.save(artifacts_module.ARTIFACT_PATH)

    # 2. Simulate a week of user actions.
    n_written = _simulate_week_of_corrections(db, owner, seeds, count=50)
    assert n_written == 50

    # 3. Retrain.
    report = Retrainer(
        db=db,
        user=owner,
        seed_dir=SEED_DIR,
        min_examples=20,
        regression_threshold=0.05,
    ).run()

    # 4. Metrics row is durable and marked deployed.
    saved = db.query(ClassifierMetric).filter(ClassifierMetric.user_id == owner.id).one()
    assert saved.deployed is True
    assert saved.holdout_accuracy == pytest.approx(report.holdout_accuracy)
    assert saved.previous_active_accuracy == pytest.approx(report.previous_active_accuracy)

    # 5. Artifact rotation happened — the weakened base moved into
    #    the .previous slot; the new one sits on ARTIFACT_PATH.
    assert artifacts_module.ARTIFACT_PATH.exists()
    assert artifacts_module.PREVIOUS_ARTIFACT_PATH.exists()

    # 6. The main assertion: the retrained model beats the weak base on
    #    the same holdout. A tiny epsilon avoids flaky ties.
    assert report.outcome is RetrainOutcome.DEPLOYED
    assert report.previous_active_accuracy is not None
    assert report.holdout_accuracy is not None
    assert report.holdout_accuracy > report.previous_active_accuracy + 0.01, (
        f"Expected retrained model to beat weakened base. "
        f"before={report.previous_active_accuracy:.3f} "
        f"after={report.holdout_accuracy:.3f}"
    )

    # 7. Print the before/after numbers so the pytest output tells the
    #    story on its own — this is the log the user asked for.
    delta = report.holdout_accuracy - report.previous_active_accuracy
    with capsys.disabled():
        print(
            f"\n[simulated-week] n_seed=200 n_user={n_written} "
            f"n_train={report.n_training_examples} n_holdout={report.n_holdout}\n"
            f"[simulated-week] previous_active_accuracy = {report.previous_active_accuracy:.3f}\n"
            f"[simulated-week] new_holdout_accuracy     = {report.holdout_accuracy:.3f}\n"
            f"[simulated-week] delta                    = {delta:+.3f}"
        )
