"""Eval harness: pure-classifier vs pure-LLM vs tiered triage.

First-class deliverable (see plan Step 10). Produces the numbers
published in docs/evals.md, the /evals page, and the README.

The harness is scrupulous about provenance: when the tier-2 fixtures
are stubs (not real LLM output), the accuracy numbers for the LLM and
tiered strategies are not meaningful and are labeled as such. What IS
always real: classifier accuracy on held-out data, all latency
measurements, cost modeling from token counts, and the escalation-rate
threshold sweep.
"""

from winnow_api.eval.dataset import EvalSplit, load_split
from winnow_api.eval.harness import EvalReport, run_eval
from winnow_api.eval.metrics import StrategyMetrics, compute_metrics

__all__ = [
    "EvalReport",
    "EvalSplit",
    "StrategyMetrics",
    "compute_metrics",
    "load_split",
    "run_eval",
]
