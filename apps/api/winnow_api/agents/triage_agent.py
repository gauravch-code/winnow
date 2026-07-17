"""PydanticAI tier-2 triage agent factory.

Kept as a factory (not a module-level singleton) so tests can build
their own agents with ``TestModel`` or ``FunctionModel`` without
touching env vars, and so the real-mode app can rebuild the agent when
the user's provider/threshold settings change.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from winnow_api.agents.prompts import TRIAGE_SYSTEM_PROMPT
from winnow_api.agents.schemas import Tier2AgentOutput

AGENT_VERSION = "triage-agent@0.1.0"


def build_triage_agent(model: Any | None = None) -> Agent[None, Tier2AgentOutput]:
    """Return an Agent that emits ``Tier2AgentOutput`` for a single email.

    ``model`` accepts anything ``Agent(...)`` does: a string like
    ``'anthropic:claude-opus-4-7'``, a PydanticAI model instance, or a
    test double. When ``None``, PydanticAI resolves from env.
    """
    return Agent(
        model=model,
        output_type=Tier2AgentOutput,
        system_prompt=TRIAGE_SYSTEM_PROMPT,
    )


def render_email_for_agent(
    *,
    sender_email: str,
    sender_name: str | None,
    subject: str,
    body_text: str,
    received_at_iso: str,
    thread_depth: int,
    has_unsubscribe: bool,
    is_reply: bool,
    tier1_lane: str | None,
    tier1_confidence: float | None,
) -> str:
    """Render a single email + tier-1's guess as the user prompt.

    Includes tier-1's tentative lane and confidence so the agent knows
    what the classifier was uncertain about — otherwise the LLM would
    redo work tier-1 already did well and might miss the specific
    edge-case tier-1 punted on.
    """
    display_sender = f"{sender_name} <{sender_email}>" if sender_name else sender_email
    tier1_note = (
        f"tier-1 classifier tentatively said {tier1_lane!r} "
        f"(confidence {tier1_confidence:.0%})"
        if tier1_lane and tier1_confidence is not None
        else "tier-1 classifier did not produce a decision"
    )
    return (
        f"From: {display_sender}\n"
        f"Subject: {subject}\n"
        f"Received: {received_at_iso}\n"
        f"Thread depth: {thread_depth}  |  is_reply: {is_reply}  |  "
        f"has_unsubscribe: {has_unsubscribe}\n"
        f"Note: {tier1_note}\n"
        f"\n--- body ---\n"
        f"{body_text}\n"
    )
