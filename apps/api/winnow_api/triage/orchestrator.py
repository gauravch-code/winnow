"""Confidence-threshold routing: tier-1 → maybe tier-2.

The orchestrator's job is a single decision: was tier-1's confidence
high enough to trust, or does this email deserve LLM attention? Kept
deliberately dumb — no retries, no fallback chains, no caching. That
kind of ceremony belongs at the API layer where it can be observed and
turned off; not here in the routing kernel.

Returns a ``TriageOutcome`` that carries both tiers' results (tier-1
always ran; tier-2 may or may not have) plus the routing decision
itself. Callers persist whichever pieces they care about.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol

from winnow_api.agents.schemas import Tier2AgentOutput
from winnow_api.classifier import ClassifierResult


class TriageRouteDecision(str, Enum):
    TIER_1_ONLY = "tier_1_only"
    ESCALATED_TO_TIER_2 = "escalated_to_tier_2"
    TIER_2_UNAVAILABLE = "tier_2_unavailable"


@dataclass
class TriageOutcome:
    route: TriageRouteDecision
    tier_1: ClassifierResult
    tier_2: Tier2AgentOutput | None
    tier_2_source: str | None  # 'live' | 'prerecorded' | 'unavailable' | None
    tier_2_reason_unavailable: str | None = None

    @property
    def final_lane(self) -> str:
        """The lane the caller should surface to the user."""
        if self.tier_2 is not None:
            return self.tier_2.lane
        return self.tier_1.lane

    @property
    def final_confidence(self) -> float:
        if self.tier_2 is not None:
            return self.tier_2.confidence
        return self.tier_1.confidence


class Tier2Provider(Protocol):
    """Anything that can produce a Tier2AgentOutput for one email.

    Two production impls:
    - ``LiveAgentProvider`` — calls PydanticAI's ``Agent.run``.
    - ``FixtureProvider`` — reads from ``FixtureLoader`` in demo mode.
    """

    async def run(self, email: Any, tier_1: ClassifierResult) -> tuple[Tier2AgentOutput | None, str, str | None]:
        """Return ``(output, source, reason_unavailable)``.

        ``source`` is 'live' | 'prerecorded' | 'unavailable'. When
        source == 'unavailable', ``output`` is None and
        ``reason_unavailable`` explains why (for the UI's graceful message).
        """
        ...


async def orchestrate_triage(
    *,
    email: Any,
    classifier: Any,
    threshold: float,
    tier_2_provider: Tier2Provider | None,
    force_tier_2: bool = False,
) -> TriageOutcome:
    """Route one email through tier-1 and (optionally) tier-2.

    ``force_tier_2`` bypasses the confidence threshold — used by the
    demo's explicit "escalate" button so visitors can see the LLM tier
    on demand, and by the eval harness to compare tiers directly.
    """
    tier_1 = classifier.predict_one(email)

    should_escalate = force_tier_2 or tier_1.confidence < threshold
    if not should_escalate:
        return TriageOutcome(
            route=TriageRouteDecision.TIER_1_ONLY,
            tier_1=tier_1,
            tier_2=None,
            tier_2_source=None,
        )

    if tier_2_provider is None:
        return TriageOutcome(
            route=TriageRouteDecision.TIER_2_UNAVAILABLE,
            tier_1=tier_1,
            tier_2=None,
            tier_2_source="unavailable",
            tier_2_reason_unavailable="Tier-2 is disabled in this deployment.",
        )

    output, source, reason = await tier_2_provider.run(email, tier_1)
    if output is None:
        return TriageOutcome(
            route=TriageRouteDecision.TIER_2_UNAVAILABLE,
            tier_1=tier_1,
            tier_2=None,
            tier_2_source=source,
            tier_2_reason_unavailable=reason,
        )

    return TriageOutcome(
        route=TriageRouteDecision.ESCALATED_TO_TIER_2,
        tier_1=tier_1,
        tier_2=output,
        tier_2_source=source,
    )
