"""Orchestrates the eval: split → train → run 3 strategies → sweep.

Produces an ``EvalReport`` that serializes to the JSON the /evals page
and README read. Also emits a threshold sweep for the tiered strategy —
that's the data behind docs/evals.md#threshold-selection, which the
``users.confidence_threshold`` default cites.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from winnow_api.classifier import Classifier
from winnow_api.classifier.embeddings import embed_batch, embedding_dim
from winnow_api.classifier.features import (
    ENGINEERED_FEATURE_NAMES,
    extract_features,
    to_vector,
)
from winnow_api.classifier.model import TrainedModel
from winnow_api.demo.fixtures import FixtureLoader
from winnow_api.eval import strategies
from winnow_api.eval.dataset import EvalSplit, load_split
from winnow_api.eval.metrics import StrategyMetrics, compute_metrics
from winnow_seed_data.seed_email_schema import SeedEmail

LANE_ORDER = ["needs_you", "informational", "hidden"]
# LogisticRegression saturates on the near-separable synthetic corpus —
# every prediction lands in ~[0.99, 1.0]. A [0.5..0.99] sweep is flat
# 0% escalation and tells the reader nothing. These thresholds span the
# range where escalation actually turns on for THIS model+data, so the
# tradeoff curve is visible. The default (0.75) is included so readers
# see it escalates nothing on clean data — which is the point.
SWEEP_THRESHOLDS = [0.75, 0.99, 0.995, 0.999, 0.9995, 0.9999]


@dataclass
class SweepPoint:
    threshold: float
    escalation_rate: float
    accuracy: float
    macro_f1: float
    cost_per_1000_usd: float
    mean_latency_ms: float


@dataclass
class EvalReport:
    generated_at: str
    n_train: int
    n_test: int
    seed: int
    test_fraction: float
    threshold: float
    tier_2_provenance: str  # "stub" | "live" (mixed → "stub" to stay conservative)
    strategies: dict[str, dict]  # name → StrategyMetrics.to_dict()
    threshold_sweep: list[dict]
    notes: list[str]

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "seed": self.seed,
            "test_fraction": self.test_fraction,
            "threshold": self.threshold,
            "tier_2_provenance": self.tier_2_provenance,
            "strategies": self.strategies,
            "threshold_sweep": self.threshold_sweep,
            "notes": self.notes,
        }


def _train_classifier(train: list[SeedEmail]) -> Classifier:
    """Fresh classifier on the train split — same recipe as production."""
    engineered = np.asarray(
        [to_vector(extract_features(s)) for s in train], dtype=np.float32
    )
    embeddings = embed_batch([(s.subject, s.body_text) for s in train])
    X = np.hstack([engineered, embeddings])
    y = np.asarray([s.ground_truth_lane for s in train])

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

    model = TrainedModel(
        pipeline=pipeline,
        lane_classes=LANE_ORDER,
        engineered_feature_names=ENGINEERED_FEATURE_NAMES,
        embedding_dim=embedding_dim(),
        sklearn_version=sklearn.__version__,
        trained_at_iso=dt.datetime.now(dt.timezone.utc).isoformat(),
        training_metrics={},
        training_size=len(train),
    )
    return Classifier(model, version_label="eval-holdout")


def _provenance(loader: FixtureLoader, test: list[SeedEmail]) -> str:
    """'live' only if every test email's fixture is real; else 'stub'.

    Conservative on purpose — if any test email is backed by a stub, the
    LLM/tiered accuracy figures are suspect, so we label the whole run
    stub and the UI shows the caveat.
    """
    saw_any = False
    for s in test:
        fx = loader.get(s.id)
        if fx is None:
            continue
        saw_any = True
        if fx.generator.provider == "stub":
            return "stub"
    return "live" if saw_any else "stub"


def run_eval(
    *,
    seed_dir: Path | None = None,
    fixture_dir: Path,
    threshold: float = 0.75,
    test_fraction: float = 0.30,
    random_state: int = 42,
) -> EvalReport:
    split: EvalSplit = load_split(
        seed_dir=seed_dir, test_fraction=test_fraction, random_state=random_state
    )
    loader = FixtureLoader(fixture_dir)
    loader.load()

    classifier = _train_classifier(split.train)

    runs = {
        "pure_classifier": strategies.pure_classifier(classifier, split.test),
        "pure_llm": strategies.pure_llm(loader, split.test),
        "tiered": strategies.tiered(classifier, loader, split.test, threshold),
    }
    metrics: dict[str, StrategyMetrics] = {
        name: compute_metrics(run) for name, run in runs.items()
    }

    sweep: list[SweepPoint] = []
    for t in SWEEP_THRESHOLDS:
        run = strategies.tiered(classifier, loader, split.test, t)
        m = compute_metrics(run)
        sweep.append(
            SweepPoint(
                threshold=t,
                escalation_rate=m.escalation_rate,
                accuracy=m.accuracy,
                macro_f1=m.macro_f1,
                cost_per_1000_usd=m.cost_per_1000_usd,
                mean_latency_ms=m.mean_latency_ms,
            )
        )

    provenance = _provenance(loader, split.test)
    notes = _build_notes(provenance, metrics)

    return EvalReport(
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        n_train=len(split.train),
        n_test=len(split.test),
        seed=split.seed,
        test_fraction=split.test_fraction,
        threshold=threshold,
        tier_2_provenance=provenance,
        strategies={name: m.to_dict() for name, m in metrics.items()},
        threshold_sweep=[vars(p) for p in sweep],
        notes=notes,
    )


def _build_notes(provenance: str, metrics: dict[str, StrategyMetrics]) -> list[str]:
    notes = [
        "Classifier accuracy, all latencies, cost modeling, and escalation "
        "rate are measured on a held-out 30% of the synthetic corpus.",
        "The synthetic corpus is intentionally clean and near-separable so "
        "the demo reads clearly; a real inbox is harder and tier-1 accuracy "
        "would be lower.",
        "Tier-1 confidences saturate near 1.0 on this near-separable data "
        "(logistic regression pushes separable classes to the extremes), so "
        "the default 0.75 threshold escalates nothing — Winnow correctly "
        "spends $0 on the LLM when the classifier is sure. Escalation only "
        "turns on above ~0.99; the sweep below uses thresholds in that range "
        "to make the tradeoff visible. On a real inbox, confidences spread "
        "out and the threshold does meaningful work at more ordinary values.",
    ]
    if provenance == "stub":
        notes.append(
            "TIER-2 IS STUBBED: the LLM fixtures used here are rule-based "
            "placeholders whose lanes mirror ground truth, so pure_llm and "
            "tiered ACCURACY are not meaningful. Latency and cost are modeled "
            "from token counts at Claude Opus pricing. Run "
            "packages/seed-data/generate.py with a real API key to publish "
            "genuine LLM accuracy."
        )
    else:
        notes.append(
            "Tier-2 fixtures are real pre-recorded Claude responses; LLM and "
            "tiered accuracy reflect genuine model judgments."
        )
    return notes
