"""Demo-mode tier-2 provider — reads pre-recorded fixtures.

Zero live LLM calls. Every tier-2 lookup resolves through
``FixtureLoader.get(seed_email_id)``; a hit returns the stored triage +
draft as if the LLM produced it (with a simulated 1000–1500ms delay so
the UX matches a real call), a miss returns ``source='unavailable'``
with the graceful "run locally to see this" message.

Simulated latency is a real behavioural feature, not a debug knob: it's
the honest UX of a real tier-2 call and hiding it would make the demo
lie about the tradeoffs of the tiered architecture.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import structlog

from winnow_api.agents.schemas import (
    Tier2AgentOutput,
    Tier2DraftReply,
    Tier2Signal,
)
from winnow_api.classifier import ClassifierResult
from winnow_api.demo.fixtures import FixtureLoader

log = structlog.get_logger(__name__)

_UNAVAILABLE_MESSAGE = (
    "This email doesn't have a pre-recorded tier-2 response yet. "
    "Run Winnow locally with your own API key to see the LLM agent handle it."
)


class FixtureProvider:
    def __init__(self, loader: FixtureLoader, simulate_latency: bool = True):
        self._loader = loader
        self._simulate = simulate_latency

    async def run(
        self, email: Any, tier_1: ClassifierResult
    ) -> tuple[Tier2AgentOutput | None, str, str | None]:
        seed_id = getattr(email, "seed_email_id", None)
        if not seed_id:
            return None, "unavailable", _UNAVAILABLE_MESSAGE

        fixture = self._loader.get(seed_id)
        if fixture is None:
            log.info("tier_2_fixture_miss", seed_email_id=seed_id)
            return None, "unavailable", _UNAVAILABLE_MESSAGE

        if self._simulate:
            lo, hi = fixture.playback.simulated_latency_ms_range
            await asyncio.sleep(random.uniform(lo, hi) / 1000.0)

        # Deserialize the fixture's triage + draft into agent-output shape.
        output = Tier2AgentOutput(
            lane=fixture.triage.lane,
            confidence=fixture.triage.confidence,
            reasoning=fixture.triage.reasoning,
            signals=[
                Tier2Signal(name=s.name, weight=s.weight) for s in fixture.triage.signals
            ],
            draft_reply=Tier2DraftReply(
                included=fixture.draft_reply.included,
                subject=fixture.draft_reply.subject,
                body_markdown=fixture.draft_reply.body_markdown,
                tone=fixture.draft_reply.tone,  # type: ignore[arg-type]
                assumptions=list(fixture.draft_reply.assumptions),
            ),
        )
        return output, "prerecorded", None
