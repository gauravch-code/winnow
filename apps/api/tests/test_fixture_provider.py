"""FixtureProvider tests — the demo's tier-2 path.

Two scenarios matter and both are exercised:
1. Fixture present → returns Tier2AgentOutput with source='prerecorded'
   and (in production) simulated latency.
2. Fixture absent → returns unavailable with the "run locally" message.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from winnow_api.agents.fixture_provider import FixtureProvider
from winnow_api.classifier.inference import ClassifierResult, TopFeature
from winnow_api.demo.fixtures import FixtureLoader


_GOOD_HASH = "sha256:" + "a" * 64


def _fixture_dict(seed_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "seed_email_id": seed_id,
        "generated_at": datetime(2026, 7, 14, tzinfo=timezone.utc).isoformat(),
        "generator": {
            "provider": "anthropic",
            "model": "claude-opus-4-7",
            "agent_version": "triage-agent@0.1.0",
            "prompt_hash": _GOOD_HASH,
            "seed_email_hash": _GOOD_HASH,
        },
        "triage": {
            "lane": "needs_you",
            "confidence": 0.84,
            "reasoning": "Direct ask from a known collaborator with a 48h deadline.",
            "signals": [{"name": "direct_question", "weight": 0.32}],
        },
        "draft_reply": {
            "included": True,
            "subject": "Re: hi",
            "body_markdown": "Sure, sending Thursday.",
            "tone": "collegial",
            "assumptions": ["user will attend Thursday review"],
        },
        "trace": {
            "agent_steps": [
                {"step": 1, "tool": None, "thought": "classify", "output_snippet": "needs_you"},
            ],
            "tokens": {"input": 100, "output": 50},
            "cost_usd_at_generation": 0.01,
            "latency_ms_live": 1400,
        },
        "playback": {
            "simulated_latency_ms_range": [0, 0],  # zero latency for tests
            "stream_chunks": None,
        },
    }


def _tier1() -> ClassifierResult:
    return ClassifierResult(
        lane="informational",
        confidence=0.4,
        class_probabilities={"informational": 0.4, "needs_you": 0.35, "hidden": 0.25},
        top_features=[TopFeature(name="fake", value=1.0, weight=0.1)],
        features={},
        latency_ms=1,
        classifier_version="fake",
    )


@pytest.fixture
def loader_with_fixture(tmp_path: Path) -> FixtureLoader:
    (tmp_path / "seed_001.json").write_text(
        json.dumps(_fixture_dict("seed_001")), encoding="utf-8"
    )
    loader = FixtureLoader(tmp_path)
    loader.load()
    return loader


@pytest.mark.asyncio
async def test_fixture_hit_returns_prerecorded(loader_with_fixture: FixtureLoader):
    provider = FixtureProvider(loader_with_fixture, simulate_latency=False)
    email = SimpleNamespace(seed_email_id="seed_001")

    output, source, reason = await provider.run(email, _tier1())
    assert source == "prerecorded"
    assert reason is None
    assert output is not None
    assert output.lane == "needs_you"
    assert output.draft_reply.included is True
    assert output.draft_reply.body_markdown == "Sure, sending Thursday."
    assert output.draft_reply.assumptions == ["user will attend Thursday review"]


@pytest.mark.asyncio
async def test_fixture_miss_returns_unavailable_with_message(loader_with_fixture: FixtureLoader):
    provider = FixtureProvider(loader_with_fixture, simulate_latency=False)
    email = SimpleNamespace(seed_email_id="seed_999")

    output, source, reason = await provider.run(email, _tier1())
    assert output is None
    assert source == "unavailable"
    assert reason is not None
    assert "locally" in reason.lower() or "pre-recorded" in reason.lower()


@pytest.mark.asyncio
async def test_email_without_seed_id_returns_unavailable(tmp_path: Path):
    """User-added emails (Step 3's 'add new email' button) won't have a
    seed_email_id — provider must degrade gracefully, not crash."""
    loader = FixtureLoader(tmp_path)
    loader.load()
    provider = FixtureProvider(loader, simulate_latency=False)
    email = SimpleNamespace(seed_email_id=None)

    output, source, _ = await provider.run(email, _tier1())
    assert output is None
    assert source == "unavailable"


@pytest.mark.asyncio
async def test_provider_reader_dispatches_to_correct_email(tmp_path: Path):
    """Two fixtures loaded; each email routes to its own fixture."""
    (tmp_path / "seed_A.json").write_text(
        json.dumps(_fixture_dict("seed_A")), encoding="utf-8"
    )
    dict_b = _fixture_dict("seed_B")
    dict_b["triage"]["lane"] = "hidden"
    dict_b["draft_reply"]["included"] = False
    (tmp_path / "seed_B.json").write_text(json.dumps(dict_b), encoding="utf-8")

    loader = FixtureLoader(tmp_path)
    loader.load()
    provider = FixtureProvider(loader, simulate_latency=False)

    out_a, _, _ = await provider.run(SimpleNamespace(seed_email_id="seed_A"), _tier1())
    out_b, _, _ = await provider.run(SimpleNamespace(seed_email_id="seed_B"), _tier1())
    assert out_a.lane == "needs_you"
    assert out_b.lane == "hidden"
    assert out_b.draft_reply.included is False
