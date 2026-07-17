"""Tier-2 LLM agent output schema.

Structured output the PydanticAI agent is constrained to produce. Shape
is compatible with the ``TriageDecisionFixture`` + ``DraftReply``
sub-objects in ``winnow_seed_data.fixture_schema`` — the fixture
generator (Step 6) wraps this output into a full fixture, and the
demo's tier-2 path deserializes fixtures back into this same type so
downstream code is oblivious to live-vs-prerecorded.

Kept in ``winnow_api.agents`` (not ``winnow_seed_data``) because the
prompt + agent are API-side artifacts; the seed-data package should
stay dependency-light so ``generate.py`` can import it without pulling
in the full API stack.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Lane = Literal["needs_you", "informational", "hidden"]


class Tier2Signal(BaseModel):
    """A named factor the agent considered, with signed weight in [-1, 1]."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    weight: float = Field(ge=-1.0, le=1.0)


class Tier2DraftReply(BaseModel):
    """Present-but-empty when the agent decides no reply is warranted.

    ``included=False`` means the fields below are ignored — the UI hides
    the draft panel entirely rather than showing a blank one.
    """

    model_config = ConfigDict(extra="forbid")

    included: bool
    subject: str | None = None
    body_markdown: str | None = None
    tone: Literal["collegial", "brief", "warm", "formal"] | None = None
    assumptions: list[str] = Field(
        default_factory=list,
        description="Things the draft assumes about the user (e.g. 'user will attend Thursday review').",
    )


class Tier2AgentOutput(BaseModel):
    """What the PydanticAI triage agent returns for one email.

    Shape mirrors ``TriageDecisionFixture`` + ``DraftReply`` so the same
    downstream renderer works for live and pre-recorded responses.
    """

    model_config = ConfigDict(extra="forbid")

    lane: Lane
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(
        min_length=10,
        description="One or two sentences on why this lane. User-visible in the explainability panel.",
    )
    signals: list[Tier2Signal] = Field(
        default_factory=list,
        max_length=6,
        description="Top factors the agent weighed. Empty list is valid; a jumble of ten is not.",
    )
    draft_reply: Tier2DraftReply
