"""Tier-1 triage model bundle.

A ``TrainedModel`` is a self-contained artifact: the fitted sklearn
pipeline, the sklearn version it was fitted on, the lane class order,
the engineered-feature name list, and the embedding dimension. Loading
verifies the sklearn version and raises loudly if the runtime differs —
deserializing a joblib blob across sklearn versions is undefined
behavior and can silently produce wrong predictions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import sklearn


@dataclass
class TrainedModel:
    pipeline: Any  # sklearn Pipeline (StandardScaler + LogisticRegression)
    lane_classes: list[str]  # canonical order — matches pipeline.classes_
    engineered_feature_names: list[str]
    embedding_dim: int
    sklearn_version: str
    trained_at_iso: str
    training_metrics: dict[str, float] = field(default_factory=dict)
    training_size: int = 0

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> "TrainedModel":
        obj: TrainedModel = joblib.load(path)
        if obj.sklearn_version != sklearn.__version__:
            raise RuntimeError(
                f"Model was trained with sklearn=={obj.sklearn_version} but this "
                f"process runs sklearn=={sklearn.__version__}. Refusing to "
                f"deserialize — retrain the model or pin sklearn."
            )
        return obj
