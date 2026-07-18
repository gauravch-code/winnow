"""Turn a StrategyRun into the published metrics.

Everything here is pure arithmetic over the per-email outcomes — no
model, no I/O — so it's fast and trivially unit-testable against a
known confusion matrix.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
from sklearn.metrics import classification_report

from winnow_api.eval.strategies import StrategyRun

LANE_ORDER = ["needs_you", "informational", "hidden"]


@dataclass
class LaneMetrics:
    precision: float
    recall: float
    f1: float
    support: int


@dataclass
class StrategyMetrics:
    name: str
    n: int
    accuracy: float
    macro_f1: float
    per_lane: dict[str, LaneMetrics]
    mean_latency_ms: float
    p95_latency_ms: float
    cost_per_1000_usd: float
    escalation_rate: float  # fraction routed to tier-2 (0 for pure_classifier)
    n_missing_fixture: int

    def to_dict(self) -> dict:
        d = asdict(self)
        # asdict turns LaneMetrics into plain dicts already.
        return d


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=float), pct))


def compute_metrics(run: StrategyRun) -> StrategyMetrics:
    y_true = run.y_true
    y_pred = run.y_pred
    n = len(run.outcomes)

    report = classification_report(
        y_true,
        y_pred,
        labels=LANE_ORDER,
        output_dict=True,
        zero_division=0,
    )
    per_lane = {
        lane: LaneMetrics(
            precision=float(report[lane]["precision"]),
            recall=float(report[lane]["recall"]),
            f1=float(report[lane]["f1-score"]),
            support=int(report[lane]["support"]),
        )
        for lane in LANE_ORDER
    }

    latencies = [o.latency_ms for o in run.outcomes]
    total_cost = sum(o.cost_usd for o in run.outcomes)
    n_escalated = sum(1 for o in run.outcomes if o.tier == 2)

    return StrategyMetrics(
        name=run.name,
        n=n,
        accuracy=float(report["accuracy"]),
        macro_f1=float(report["macro avg"]["f1-score"]),
        per_lane=per_lane,
        mean_latency_ms=float(np.mean(latencies)) if latencies else 0.0,
        p95_latency_ms=_percentile(latencies, 95),
        # Scale the observed average cost to a per-1000-email figure.
        cost_per_1000_usd=(total_cost / n * 1000.0) if n else 0.0,
        escalation_rate=(n_escalated / n) if n else 0.0,
        n_missing_fixture=sum(1 for o in run.outcomes if not o.had_fixture),
    )
