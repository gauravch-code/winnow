"""Pydantic schema for pre-recorded tier-2 LLM response fixtures.

Fixtures live at ``packages/seed-data/llm-responses/{seed_email_id}.json``
and are generated once by ``packages/seed-data/generate.py`` against my
own Anthropic key. The demo backend loads them into memory at startup
and serves them in place of live LLM calls.

The fixture's ``triage`` sub-object mirrors the PydanticAI agent's real
structured output, so downstream code is oblivious to which path
produced the payload. Any drift is caught at boot (runtime warning) and
in CI (``check-fixtures-fresh`` job — see docs/architecture.md).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Lane = Literal["needs_you", "informational", "hidden"]
Sha256Hex = str  # constrained via pattern in fields that use it

_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


class GeneratorInfo(BaseModel):
    """Metadata about the run that produced this fixture.

    ``prompt_hash`` and ``seed_email_hash`` let CI detect when the agent
    prompt or the seed email has changed and this fixture is now stale.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    agent_version: str
    prompt_hash: Sha256Hex = Field(pattern=_SHA256_PATTERN)
    seed_email_hash: Sha256Hex = Field(pattern=_SHA256_PATTERN)


class TriageSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    weight: float


class TriageDecisionFixture(BaseModel):
    """Shape-compatible with the live tier-2 PydanticAI output."""

    model_config = ConfigDict(extra="forbid")

    lane: Lane
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    signals: list[TriageSignal] = Field(default_factory=list)


class DraftReply(BaseModel):
    """Present-but-empty when the agent decided no reply was warranted."""

    model_config = ConfigDict(extra="forbid")

    included: bool
    subject: str | None = None
    body_markdown: str | None = None
    tone: str | None = None
    assumptions: list[str] = Field(default_factory=list)


class AgentStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int
    tool: str | None = None
    thought: str
    output_snippet: str


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: int
    output: int


class TraceInfo(BaseModel):
    """What the live tier-2 path emits into ``triage_decisions.agent_trace``.

    ``cost_usd_at_generation`` is aggregated on the marketing site as
    "this demo would have cost $X.XX to serve live."
    """

    model_config = ConfigDict(extra="forbid")

    agent_steps: list[AgentStep]
    tokens: TokenUsage
    cost_usd_at_generation: float
    latency_ms_live: int


class PlaybackHints(BaseModel):
    """Consumed only by the demo orchestrator, not the real app.

    If ``stream_chunks`` is None the orchestrator yields the whole body
    once after the simulated latency instead of streaming.
    """

    model_config = ConfigDict(extra="forbid")

    simulated_latency_ms_range: tuple[int, int] = (1000, 1500)
    stream_chunks: list[str] | None = None


class FixtureResponse(BaseModel):
    """Root schema for a single ``{seed_email_id}.json`` fixture file."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"]
    seed_email_id: str
    generated_at: datetime
    generator: GeneratorInfo
    triage: TriageDecisionFixture
    draft_reply: DraftReply
    trace: TraceInfo
    playback: PlaybackHints = Field(default_factory=PlaybackHints)
