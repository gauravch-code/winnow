"""Tier-2 agent output schema tests.

The schema is the contract between the LLM (constrained via structured
output), the fixture generator, and the demo's fixture reader. Anything
that lets a bad shape through is a silent bug in one of those three
paths.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from winnow_api.agents.prompts import prompt_hash
from winnow_api.agents.schemas import (
    Tier2AgentOutput,
    Tier2DraftReply,
    Tier2Signal,
)


def _base_kwargs() -> dict:
    return dict(
        lane="needs_you",
        confidence=0.9,
        reasoning="Direct ask from a known collaborator with a 48h deadline.",
        signals=[Tier2Signal(name="direct_question", weight=0.3)],
        draft_reply=Tier2DraftReply(included=False),
    )


def test_valid_shape_accepted():
    output = Tier2AgentOutput(**_base_kwargs())
    assert output.lane == "needs_you"


def test_confidence_bounded():
    for bad in (-0.01, 1.01, 5.0):
        with pytest.raises(ValidationError):
            Tier2AgentOutput(**{**_base_kwargs(), "confidence": bad})


def test_signal_weight_bounded():
    for bad in (-1.5, 1.5):
        with pytest.raises(ValidationError):
            Tier2Signal(name="x", weight=bad)


def test_lane_enum_enforced():
    with pytest.raises(ValidationError):
        Tier2AgentOutput(**{**_base_kwargs(), "lane": "spam"})


def test_reasoning_minimum_length():
    """Empty or near-empty reasoning is not useful in the explainability
    panel — the schema forces the LLM to write something substantive."""
    with pytest.raises(ValidationError):
        Tier2AgentOutput(**{**_base_kwargs(), "reasoning": "ok"})


def test_signals_capped_at_6():
    """Six is arbitrary but tight enough that the panel doesn't blur."""
    too_many = [Tier2Signal(name=f"s{i}", weight=0.1) for i in range(10)]
    with pytest.raises(ValidationError):
        Tier2AgentOutput(**{**_base_kwargs(), "signals": too_many})


def test_draft_tone_enum():
    with pytest.raises(ValidationError):
        Tier2DraftReply(included=True, tone="snarky")  # type: ignore[arg-type]


def test_extra_fields_forbidden():
    """A drift on either side (agent adds a field / consumer expects one
    that's missing) fails loudly instead of being silently dropped."""
    with pytest.raises(ValidationError):
        Tier2AgentOutput(**_base_kwargs(), extra_thing="hi")  # type: ignore[call-arg]


def test_prompt_hash_stable_and_prefixed():
    """Two calls must return the same hash; format must match the fixture
    schema's prompt_hash pattern (^sha256:[0-9a-f]{64}$)."""
    h1 = prompt_hash()
    h2 = prompt_hash()
    assert h1 == h2
    assert h1.startswith("sha256:")
    assert len(h1) == len("sha256:") + 64
