"""FixtureLoader unit tests.

Pure unit — no DB, no network. Uses ``tmp_path`` to build a synthetic
fixture directory per test.

These tests are the executable spec for the loader's contract:
- valid fixtures load; invalid ones are logged and skipped;
- filename must equal seed_email_id;
- missing dir is a soft failure (empty index, no exception);
- drift detection warns but still serves.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from winnow_api.demo.fixtures import FixtureLoader


_GOOD_HASH = "sha256:" + "a" * 64
_OTHER_HASH = "sha256:" + "b" * 64


def _valid_fixture_dict(seed_id: str = "seed_001") -> dict[str, Any]:
    """Minimal fixture that passes FixtureResponse validation.

    Kept as a factory rather than a module constant so each test gets a
    fresh dict it can mutate without leaking state.
    """
    return {
        "schema_version": "1",
        "seed_email_id": seed_id,
        "generated_at": datetime(2026, 7, 14, 18, 22, 11, tzinfo=timezone.utc).isoformat(),
        "generator": {
            "provider": "anthropic",
            "model": "claude-opus-4-7",
            "agent_version": "triage-agent@0.3.1",
            "prompt_hash": _GOOD_HASH,
            "seed_email_hash": _GOOD_HASH,
        },
        "triage": {
            "lane": "needs_you",
            "confidence": 0.87,
            "reasoning": "direct ask + known sender",
            "signals": [{"name": "direct_question", "weight": 0.34}],
        },
        "draft_reply": {
            "included": True,
            "subject": "Re: hi",
            "body_markdown": "hey",
            "tone": "collegial",
            "assumptions": [],
        },
        "trace": {
            "agent_steps": [
                {"step": 1, "tool": None, "thought": "classify", "output_snippet": "needs_you"}
            ],
            "tokens": {"input": 812, "output": 214},
            "cost_usd_at_generation": 0.0134,
            "latency_ms_live": 1423,
        },
        "playback": {
            "simulated_latency_ms_range": [1000, 1500],
            "stream_chunks": ["hey"],
        },
    }


def _write_fixture(dir_: Path, seed_id: str, overrides: dict[str, Any] | None = None) -> Path:
    data = _valid_fixture_dict(seed_id)
    if overrides:
        # Shallow merge is enough for the fields tests actually override.
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                data[key] = {**data[key], **value}
            else:
                data[key] = value
    path = dir_ / f"{seed_id}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --- happy path -------------------------------------------------------------


def test_loader_indexes_valid_fixtures_by_seed_id(tmp_path: Path):
    _write_fixture(tmp_path, "seed_001")
    _write_fixture(tmp_path, "seed_002")
    _write_fixture(tmp_path, "seed_003")

    loader = FixtureLoader(tmp_path)
    loader.load()

    assert len(loader) == 3
    assert loader.all_ids() == {"seed_001", "seed_002", "seed_003"}
    fixture = loader.get("seed_002")
    assert fixture is not None
    assert fixture.seed_email_id == "seed_002"
    assert fixture.triage.lane == "needs_you"


def test_get_returns_none_for_unknown_id(tmp_path: Path):
    _write_fixture(tmp_path, "seed_001")
    loader = FixtureLoader(tmp_path)
    loader.load()

    assert loader.get("seed_nonexistent") is None


# --- resilience: bad files must not take down the loader -------------------


def test_loader_skips_invalid_json(tmp_path: Path):
    _write_fixture(tmp_path, "seed_001")
    (tmp_path / "seed_bad.json").write_text("{not json", encoding="utf-8")

    loader = FixtureLoader(tmp_path)
    loader.load()

    # The valid one still loads; the broken file did not crash the loader.
    assert loader.all_ids() == {"seed_001"}


def test_loader_skips_schema_violation(tmp_path: Path):
    _write_fixture(tmp_path, "seed_001")
    # Confidence out of [0,1] — violates the FixtureResponse schema.
    _write_fixture(tmp_path, "seed_bad", overrides={"triage": {"confidence": 5.0}})

    loader = FixtureLoader(tmp_path)
    loader.load()

    assert loader.all_ids() == {"seed_001"}


def test_loader_rejects_extra_fields(tmp_path: Path):
    """extra='forbid' on every model — a typo in generate.py must fail loudly.

    This is not just resilience; it protects against silent schema drift
    where a new field is added to generate.py but the loader/consumer
    never learns about it.
    """
    _write_fixture(tmp_path, "seed_001", overrides={"unexpected_field": "surprise"})

    loader = FixtureLoader(tmp_path)
    loader.load()

    assert loader.all_ids() == set()


def test_loader_rejects_filename_seed_id_mismatch(tmp_path: Path):
    """Filename must equal seed_email_id.

    Otherwise the orchestrator would serve fixture A while claiming it
    came from email B. This is the exact bug ck_emails_demo_rows_have_seed_id
    is meant to prevent on the DB side; the loader enforces it on the
    file side.
    """
    # File is seed_042.json but the fixture inside says seed_003.
    data = _valid_fixture_dict("seed_003")
    (tmp_path / "seed_042.json").write_text(json.dumps(data), encoding="utf-8")

    loader = FixtureLoader(tmp_path)
    loader.load()

    assert loader.all_ids() == set()


def test_loader_missing_dir_is_soft_fail(tmp_path: Path):
    """Nonexistent fixture dir must not raise.

    In demo mode the API still boots; every tier-2 lookup returns None
    and the orchestrator emits an 'unavailable' response.
    """
    missing = tmp_path / "does-not-exist"
    loader = FixtureLoader(missing)
    loader.load()

    assert len(loader) == 0
    assert loader.get("anything") is None


def test_load_is_idempotent(tmp_path: Path):
    _write_fixture(tmp_path, "seed_001")
    loader = FixtureLoader(tmp_path)
    loader.load()
    loader.load()  # second call must no-op

    assert len(loader) == 1


def test_reset_allows_reload(tmp_path: Path):
    _write_fixture(tmp_path, "seed_001")
    loader = FixtureLoader(tmp_path)
    loader.load()
    assert loader.all_ids() == {"seed_001"}

    _write_fixture(tmp_path, "seed_002")
    loader.reset()
    loader.load()

    assert loader.all_ids() == {"seed_001", "seed_002"}


# --- freshness check --------------------------------------------------------


def test_verify_freshness_flags_prompt_drift(tmp_path: Path):
    _write_fixture(tmp_path, "seed_001")
    _write_fixture(tmp_path, "seed_002")
    loader = FixtureLoader(tmp_path)
    loader.load()

    # Both fixtures generated with _GOOD_HASH; current is _OTHER_HASH.
    stale = loader.verify_freshness(
        current_prompt_hash=_OTHER_HASH,
        current_seed_email_hashes={},
    )
    assert set(stale) == {"seed_001", "seed_002"}


def test_verify_freshness_flags_only_specific_seed_drift(tmp_path: Path):
    _write_fixture(tmp_path, "seed_001")
    _write_fixture(tmp_path, "seed_002")
    loader = FixtureLoader(tmp_path)
    loader.load()

    stale = loader.verify_freshness(
        current_prompt_hash=_GOOD_HASH,
        current_seed_email_hashes={"seed_002": _OTHER_HASH},
    )
    assert stale == ["seed_002"]


def test_verify_freshness_missing_seed_hash_is_skipped(tmp_path: Path):
    """A seed_email_id not in the mapping means we have nothing to compare
    against — treat as fresh rather than false-alarm."""
    _write_fixture(tmp_path, "seed_001")
    loader = FixtureLoader(tmp_path)
    loader.load()

    stale = loader.verify_freshness(
        current_prompt_hash=_GOOD_HASH,
        current_seed_email_hashes={},
    )
    assert stale == []


def test_verify_freshness_requires_load_first(tmp_path: Path):
    loader = FixtureLoader(tmp_path)
    with pytest.raises(RuntimeError, match="load"):
        loader.verify_freshness(_GOOD_HASH, {})


def test_verify_freshness_reports_all_reasons_for_one_fixture(tmp_path: Path):
    """When both prompt and seed hash changed, both are reported."""
    _write_fixture(tmp_path, "seed_001")
    loader = FixtureLoader(tmp_path)
    loader.load()

    stale = loader.verify_freshness(
        current_prompt_hash=_OTHER_HASH,
        current_seed_email_hashes={"seed_001": _OTHER_HASH},
    )
    # Only care that it's flagged once — reasons are in the log record.
    assert stale == ["seed_001"]
