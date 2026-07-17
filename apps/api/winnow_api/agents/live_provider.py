"""Live tier-2 provider — calls the real LLM via PydanticAI.

Only wired into the real app. In demo mode this is never instantiated;
``FixtureProvider`` reads pre-recorded responses instead.

Failure mode: if the agent call raises (network, auth, quota), the
provider surfaces it as ``source='unavailable'`` with a short reason
rather than propagating — the orchestrator's "unavailable" path is the
correct place to render a graceful UI, and we do not want a transient
LLM outage to crash the triage endpoint.
"""

from __future__ import annotations

from typing import Any

import structlog

from winnow_api.agents.schemas import Tier2AgentOutput
from winnow_api.agents.triage_agent import build_triage_agent, render_email_for_agent
from winnow_api.classifier import ClassifierResult

log = structlog.get_logger(__name__)


class LiveAgentProvider:
    def __init__(self, model: Any):
        # ``model`` is anything ``Agent(model=...)`` accepts.
        self._agent = build_triage_agent(model)

    async def run(
        self, email: Any, tier_1: ClassifierResult
    ) -> tuple[Tier2AgentOutput | None, str, str | None]:
        prompt = render_email_for_agent(
            sender_email=getattr(email, "sender_email", ""),
            sender_name=getattr(email, "sender_name", None),
            subject=getattr(email, "subject", ""),
            body_text=getattr(email, "body_text", ""),
            received_at_iso=getattr(email, "received_at").isoformat()
            if getattr(email, "received_at", None)
            else "",
            thread_depth=getattr(email, "thread_depth", 1),
            has_unsubscribe=bool(getattr(email, "has_unsubscribe", False)),
            is_reply=bool(getattr(email, "is_reply", False)),
            tier1_lane=tier_1.lane,
            tier1_confidence=tier_1.confidence,
        )
        try:
            result = await self._agent.run(prompt)
        except Exception as exc:  # noqa: BLE001 — provider boundary
            log.warning("tier_2_live_failed", error=str(exc), error_type=type(exc).__name__)
            return None, "unavailable", f"LLM call failed: {type(exc).__name__}"
        return result.output, "live", None
