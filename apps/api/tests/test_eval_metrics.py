"""metrics.compute_metrics against hand-built runs.

Pure arithmetic — no model, no I/O — so these are fast and exact. A
known confusion matrix has known precision/recall/F1; if these drift,
the published eval numbers are wrong.
"""

from __future__ import annotations

from winnow_api.eval.metrics import compute_metrics
from winnow_api.eval.strategies import EmailOutcome, StrategyRun


def _run(outcomes: list[EmailOutcome]) -> StrategyRun:
    return StrategyRun(name="test", outcomes=outcomes)


def _oc(
    true_lane: str,
    pred_lane: str,
    *,
    tier: int = 1,
    latency_ms: float = 1.0,
    cost_usd: float = 0.0,
    had_fixture: bool = True,
) -> EmailOutcome:
    return EmailOutcome(
        seed_email_id="x",
        true_lane=true_lane,
        pred_lane=pred_lane,
        tier=tier,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        had_fixture=had_fixture,
    )


def test_perfect_predictions():
    run = _run(
        [
            _oc("needs_you", "needs_you"),
            _oc("informational", "informational"),
            _oc("hidden", "hidden"),
        ]
    )
    m = compute_metrics(run)
    assert m.accuracy == 1.0
    assert m.macro_f1 == 1.0
    for lane in ("needs_you", "informational", "hidden"):
        assert m.per_lane[lane].precision == 1.0
        assert m.per_lane[lane].recall == 1.0


def test_known_confusion_matrix():
    """Two classes, one confusion each way — hand-computable P/R/F1.

    needs_you: 2 true. Predicted needs_you 2 times but one is actually
    hidden → TP=1, FP=1, FN=1 → precision 0.5, recall 0.5, F1 0.5.
    """
    run = _run(
        [
            _oc("needs_you", "needs_you"),   # TP needs_you
            _oc("needs_you", "hidden"),      # FN needs_you / FP hidden
            _oc("hidden", "needs_you"),      # FP needs_you / FN hidden
            _oc("hidden", "hidden"),         # TP hidden
        ]
    )
    m = compute_metrics(run)
    assert m.accuracy == 0.5
    assert m.per_lane["needs_you"].precision == 0.5
    assert m.per_lane["needs_you"].recall == 0.5
    assert abs(m.per_lane["needs_you"].f1 - 0.5) < 1e-9
    assert m.per_lane["hidden"].precision == 0.5
    assert m.per_lane["hidden"].recall == 0.5


def test_support_counts_true_labels():
    run = _run(
        [
            _oc("needs_you", "needs_you"),
            _oc("needs_you", "hidden"),
            _oc("informational", "informational"),
        ]
    )
    m = compute_metrics(run)
    assert m.per_lane["needs_you"].support == 2
    assert m.per_lane["informational"].support == 1
    assert m.per_lane["hidden"].support == 0


def test_cost_per_1000_scales_from_average():
    # 4 emails costing $0.01 total → $0.0025 avg → $2.50 per 1000.
    run = _run(
        [
            _oc("hidden", "hidden", cost_usd=0.01),
            _oc("hidden", "hidden", cost_usd=0.0),
            _oc("hidden", "hidden", cost_usd=0.0),
            _oc("hidden", "hidden", cost_usd=0.0),
        ]
    )
    m = compute_metrics(run)
    assert abs(m.cost_per_1000_usd - 2.5) < 1e-9


def test_escalation_rate_counts_tier2():
    run = _run(
        [
            _oc("hidden", "hidden", tier=1),
            _oc("hidden", "hidden", tier=2),
            _oc("hidden", "hidden", tier=2),
            _oc("hidden", "hidden", tier=1),
        ]
    )
    m = compute_metrics(run)
    assert m.escalation_rate == 0.5


def test_p95_latency():
    # 20 values 1..20; p95 ≈ 19.05.
    run = _run([_oc("hidden", "hidden", latency_ms=float(i)) for i in range(1, 21)])
    m = compute_metrics(run)
    assert 18.5 <= m.p95_latency_ms <= 20.0
    assert abs(m.mean_latency_ms - 10.5) < 1e-9


def test_missing_fixture_counted():
    run = _run(
        [
            _oc("hidden", "hidden", had_fixture=True),
            _oc("hidden", "informational", had_fixture=False),
        ]
    )
    m = compute_metrics(run)
    assert m.n_missing_fixture == 1
