"""Confidence-threshold routing tests.

The orchestrator is the routing kernel — if it ever misroutes, users
pay for tier-2 on trivial email OR miss LLM attention on the hard
cases that most need it. Both directions are tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from winnow_api.agents.schemas import Tier2AgentOutput, Tier2DraftReply
from winnow_api.classifier.inference import ClassifierResult, TopFeature
from winnow_api.triage import TriageRouteDecision, orchestrate_triage


class _FakeClassifier:
    def __init__(self, lane: str, confidence: float):
        self._lane = lane
        self._conf = confidence

    def predict_one(self, email: Any) -> ClassifierResult:
        return ClassifierResult(
            lane=self._lane,
            confidence=self._conf,
            class_probabilities={self._lane: self._conf},
            top_features=[TopFeature(name="fake", value=1.0, weight=0.5)],
            features={},
            latency_ms=1,
            classifier_version="fake-1",
        )


@dataclass
class _RecordingProvider:
    output: Tier2AgentOutput | None
    source: str
    reason: str | None = None
    call_count: int = 0

    async def run(self, email, tier_1):
        self.call_count += 1
        return self.output, self.source, self.reason


def _tier2_output(lane: str = "needs_you") -> Tier2AgentOutput:
    return Tier2AgentOutput(
        lane=lane,  # type: ignore[arg-type]
        confidence=0.82,
        reasoning="Direct ask from known collaborator with 48h deadline.",
        signals=[],
        draft_reply=Tier2DraftReply(included=False),
    )


@pytest.mark.asyncio
async def test_high_confidence_stays_tier_1():
    """Confidence above threshold → no LLM call, no escalation."""
    provider = _RecordingProvider(output=_tier2_output(), source="live")
    outcome = await orchestrate_triage(
        email=object(),
        classifier=_FakeClassifier("informational", 0.95),
        threshold=0.75,
        tier_2_provider=provider,
    )
    assert outcome.route == TriageRouteDecision.TIER_1_ONLY
    assert outcome.tier_2 is None
    assert outcome.tier_2_source is None
    assert provider.call_count == 0
    assert outcome.final_lane == "informational"


@pytest.mark.asyncio
async def test_low_confidence_escalates():
    provider = _RecordingProvider(output=_tier2_output("needs_you"), source="live")
    outcome = await orchestrate_triage(
        email=object(),
        classifier=_FakeClassifier("informational", 0.55),
        threshold=0.75,
        tier_2_provider=provider,
    )
    assert outcome.route == TriageRouteDecision.ESCALATED_TO_TIER_2
    assert outcome.tier_2 is not None
    assert outcome.tier_2_source == "live"
    assert provider.call_count == 1
    # Tier-2's lane wins over tier-1's when it produces a decision.
    assert outcome.final_lane == "needs_you"


@pytest.mark.asyncio
async def test_at_threshold_stays_tier_1():
    """Boundary case: confidence == threshold should not escalate.

    The threshold is *the point at which we trust tier-1*; equality
    should trust, not escalate. Otherwise a threshold of 0.75 secretly
    means 0.751."""
    provider = _RecordingProvider(output=_tier2_output(), source="live")
    outcome = await orchestrate_triage(
        email=object(),
        classifier=_FakeClassifier("hidden", 0.75),
        threshold=0.75,
        tier_2_provider=provider,
    )
    assert outcome.route == TriageRouteDecision.TIER_1_ONLY
    assert provider.call_count == 0


@pytest.mark.asyncio
async def test_force_tier_2_bypasses_threshold():
    """The escalate endpoint uses force=True to let visitors see the LLM
    tier even on emails tier-1 was confident about."""
    provider = _RecordingProvider(output=_tier2_output(), source="live")
    outcome = await orchestrate_triage(
        email=object(),
        classifier=_FakeClassifier("informational", 0.99),
        threshold=0.75,
        tier_2_provider=provider,
        force_tier_2=True,
    )
    assert outcome.route == TriageRouteDecision.ESCALATED_TO_TIER_2
    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_no_provider_returns_unavailable():
    """Real-mode deployments without an LLM key must still route cleanly."""
    outcome = await orchestrate_triage(
        email=object(),
        classifier=_FakeClassifier("informational", 0.55),
        threshold=0.75,
        tier_2_provider=None,
    )
    assert outcome.route == TriageRouteDecision.TIER_2_UNAVAILABLE
    assert outcome.tier_2 is None
    assert outcome.tier_2_source == "unavailable"
    assert outcome.tier_2_reason_unavailable is not None


@pytest.mark.asyncio
async def test_provider_unavailable_propagates():
    """When the provider returns unavailable (missing fixture, LLM outage),
    the outcome carries the reason for UI display."""
    provider = _RecordingProvider(
        output=None,
        source="unavailable",
        reason="no fixture for this email",
    )
    outcome = await orchestrate_triage(
        email=object(),
        classifier=_FakeClassifier("informational", 0.4),
        threshold=0.75,
        tier_2_provider=provider,
    )
    assert outcome.route == TriageRouteDecision.TIER_2_UNAVAILABLE
    assert outcome.tier_2_reason_unavailable == "no fixture for this email"
    assert outcome.final_lane == "informational"  # falls back to tier-1
