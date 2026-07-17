"""Tier-1 inference and explainability.

``Classifier`` is a thin runtime wrapper around a ``TrainedModel``: it
holds the model in memory, batches encoding, and produces a
``ClassifierResult`` that carries the predicted lane, confidence, and
the top features that drove the decision.

Top-feature attribution for LogisticRegression is trivially exact:
each engineered feature's contribution to the winning class's score is
``coef_class[i] * standardized_x_i``. Embedding dimensions get bundled
into a single ``email_content_signal`` bucket because 384 dims of
"embedding_dim_137: 0.03" would drown the panel and mean nothing to a
human.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from winnow_api.classifier.embeddings import embed_batch, embed_one
from winnow_api.classifier.features import extract_features, to_vector
from winnow_api.classifier.model import TrainedModel


@dataclass
class TopFeature:
    name: str
    value: float
    weight: float  # signed contribution to the winning class's score

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value, "weight": self.weight}


@dataclass
class ClassifierResult:
    lane: str
    confidence: float
    class_probabilities: dict[str, float]
    top_features: list[TopFeature]
    features: dict[str, float]  # full engineered-feature dict for DB storage
    latency_ms: int
    classifier_version: str

    def top_features_json(self) -> list[dict[str, Any]]:
        return [tf.to_dict() for tf in self.top_features]


class Classifier:
    """Runtime classifier. One instance per process; thread-safe for inference."""

    def __init__(self, model: TrainedModel, version_label: str):
        self.model = model
        self.version = version_label
        self._scaler = model.pipeline.named_steps["scaler"]
        self._clf = model.pipeline.named_steps["clf"]
        self._n_eng = len(model.engineered_feature_names)

    @staticmethod
    def load(artifact_path: Path, version_label: str | None = None) -> "Classifier":
        model = TrainedModel.load(artifact_path)
        label = version_label or f"base-{model.trained_at_iso}"
        return Classifier(model, label)

    def predict_one(self, email: Any) -> ClassifierResult:
        return self.predict_many([email])[0]

    def predict_many(self, emails: list[Any]) -> list[ClassifierResult]:
        started = time.perf_counter()

        feat_dicts = [extract_features(e) for e in emails]
        engineered = np.asarray(
            [to_vector(fd) for fd in feat_dicts], dtype=np.float32
        )
        embeddings = embed_batch([(e.subject, e.body_text) for e in emails])
        X = np.hstack([engineered, embeddings])

        # Predict + probabilities.
        probs = self._clf.predict_proba(self._scaler.transform(X))
        classes = list(self._clf.classes_)

        # Standardized X for attribution (same transform the model saw).
        X_scaled = self._scaler.transform(X)

        results: list[ClassifierResult] = []
        elapsed_ms_total = int((time.perf_counter() - started) * 1000)
        # Amortize batch latency across items — a per-item value is more
        # useful downstream than a single "batch took 12ms" figure.
        per_item_ms = max(1, elapsed_ms_total // max(1, len(emails)))

        for i, feat_dict in enumerate(feat_dicts):
            winning_idx = int(np.argmax(probs[i]))
            winning_class = classes[winning_idx]
            confidence = float(probs[i][winning_idx])
            class_probs = {c: float(p) for c, p in zip(classes, probs[i])}

            top = self._explain(X_scaled[i], winning_idx, feat_dict)

            results.append(
                ClassifierResult(
                    lane=winning_class,
                    confidence=confidence,
                    class_probabilities=class_probs,
                    top_features=top,
                    features=feat_dict,
                    latency_ms=per_item_ms,
                    classifier_version=self.version,
                )
            )
        return results

    def _explain(
        self,
        x_scaled: np.ndarray,
        winning_idx: int,
        feat_dict: dict[str, float],
    ) -> list[TopFeature]:
        """Rank features by their signed contribution to the winning class."""
        coef = self._clf.coef_[winning_idx]  # (n_features,)
        contribs = coef * x_scaled  # element-wise

        eng_names = self.model.engineered_feature_names
        eng_contribs = contribs[: self._n_eng]

        # Collapse the 384 embedding dims into one interpretable bucket.
        emb_bucket = float(contribs[self._n_eng:].sum())

        entries: list[TopFeature] = [
            TopFeature(
                name=name,
                value=float(feat_dict[name]),
                weight=float(w),
            )
            for name, w in zip(eng_names, eng_contribs)
        ]
        entries.append(
            TopFeature(
                name="email_content_signal",
                value=0.0,  # opaque — the raw 384 values would mean nothing
                weight=emb_bucket,
            )
        )

        entries.sort(key=lambda tf: abs(tf.weight), reverse=True)
        return entries[:5]
