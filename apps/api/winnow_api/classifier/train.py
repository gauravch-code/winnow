"""Train the baseline tier-1 classifier on the 200 seed emails.

Run once (or after schema changes) with:

    uv run python -m winnow_api.classifier.train

Writes ``apps/api/winnow_api/classifier/artifacts/base.joblib`` — that
file is what the demo API loads at startup. Cross-val metrics are
printed and saved into the artifact for later reference.

Design choices:

- LogisticRegression, not RandomForest. Interpretability wins here — I
  want per-feature contributions for the explainability panel, and a
  linear model gives them for free. Boosted trees would nudge accuracy
  up a percent or two on this small dataset but at real cost to
  explainability and inference speed.

- StandardScaler on the joined feature block. Engineered features vary
  by 3 orders of magnitude (0/1 booleans vs log(body_length)); without
  scaling, LR weights are impossible to compare against each other.

- StratifiedKFold, not a single train/test split. The seed dataset is
  200 emails with a ~62/20/18 lane distribution — a random 80/20 split
  can trivially miss whole slices of the minority class.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from winnow_api.classifier.embeddings import embed_batch, embedding_dim
from winnow_api.classifier.features import (
    ENGINEERED_FEATURE_NAMES,
    extract_features,
    to_vector,
)
from winnow_api.classifier.model import TrainedModel
from winnow_seed_data.seed_email_schema import SeedEmail

SEED_DIR = Path(__file__).resolve().parents[4] / "packages" / "seed-data" / "emails"
ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
ARTIFACT_PATH = ARTIFACT_DIR / "base.joblib"

LANE_ORDER = ["needs_you", "informational", "hidden"]


def _load_seeds() -> list[SeedEmail]:
    return [
        SeedEmail.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(SEED_DIR.glob("seed_*.json"))
    ]


def build_matrix(seeds: list[SeedEmail]) -> tuple[np.ndarray, np.ndarray]:
    engineered = np.asarray(
        [to_vector(extract_features(s)) for s in seeds], dtype=np.float32
    )
    embeddings = embed_batch([(s.subject, s.body_text) for s in seeds])
    X = np.hstack([engineered, embeddings])
    y = np.asarray([s.ground_truth_lane for s in seeds])
    return X, y


def main() -> None:
    seeds = _load_seeds()
    print(f"Loaded {len(seeds)} seed emails from {SEED_DIR}")

    X, y = build_matrix(seeds)
    print(f"Feature matrix: X={X.shape}, y={y.shape}")

    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                # sklearn>=1.7 always trains multinomial when there are 3+
                # classes with lbfgs — the old ``multi_class`` kwarg was
                # removed. Behavior here is identical to
                # ``multi_class='multinomial'`` in earlier versions.
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

    # Cross-val for honest metrics on the tiny 200-sample dataset.
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    y_pred = cross_val_predict(pipeline, X, y, cv=skf)
    report = classification_report(y, y_pred, labels=LANE_ORDER, output_dict=True)
    print("\n5-fold cross-val:")
    print(classification_report(y, y_pred, labels=LANE_ORDER))

    # Fit final model on the full dataset for shipping.
    pipeline.fit(X, y)
    # Force class order to our canonical order for downstream code sanity.
    if list(pipeline.classes_) != LANE_ORDER:
        # LogisticRegression puts classes_ in sorted order; if that's not
        # our canonical order, resort the coef_ / intercept_ so downstream
        # code can trust a fixed [needs_you, informational, hidden] mapping.
        clf = pipeline.named_steps["clf"]
        idx = [list(clf.classes_).index(c) for c in LANE_ORDER]
        clf.classes_ = np.asarray(LANE_ORDER)
        clf.coef_ = clf.coef_[idx]
        clf.intercept_ = clf.intercept_[idx]

    metrics = {
        "cv_macro_precision": report["macro avg"]["precision"],
        "cv_macro_recall": report["macro avg"]["recall"],
        "cv_macro_f1": report["macro avg"]["f1-score"],
        "cv_accuracy": report["accuracy"],
    }
    for lane in LANE_ORDER:
        metrics[f"cv_precision_{lane}"] = report[lane]["precision"]
        metrics[f"cv_recall_{lane}"] = report[lane]["recall"]

    model = TrainedModel(
        pipeline=pipeline,
        lane_classes=LANE_ORDER,
        engineered_feature_names=ENGINEERED_FEATURE_NAMES,
        embedding_dim=embedding_dim(),
        sklearn_version=sklearn.__version__,
        trained_at_iso=dt.datetime.now(dt.timezone.utc).isoformat(),
        training_metrics=metrics,
        training_size=len(seeds),
    )
    model.save(ARTIFACT_PATH)
    print(f"\nSaved model -> {ARTIFACT_PATH}")


if __name__ == "__main__":
    main()
