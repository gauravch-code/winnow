"""check-fixtures-fresh CLI tests.

Locks the two behaviors that matter: fresh fixtures pass (exit 0), stale
fixtures fail (exit 1) with a report that names the guilty fixtures. We
patch the module's SEED_DIR / FIXTURE_DIR at import time to isolate
tests from the repo state.
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Load the freshness-check module dynamically because it lives under
# packages/seed-data/, not the winnow_api package tree.
_FRESH_MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "seed-data"
    / "check_fixtures_fresh.py"
)


@pytest.fixture
def freshness_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Import check_fixtures_fresh with SEED_DIR + FIXTURE_DIR pointed at
    a tmp scratch space. Import must happen after monkeypatching so the
    module reads the patched paths."""
    import sys

    spec = importlib.util.spec_from_file_location("check_fixtures_fresh", _FRESH_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules["check_fixtures_fresh"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    seed_dir = tmp_path / "emails"
    fixture_dir = tmp_path / "llm-responses"
    seed_dir.mkdir()
    fixture_dir.mkdir()
    monkeypatch.setattr(module, "SEED_DIR", seed_dir)
    monkeypatch.setattr(module, "FIXTURE_DIR", fixture_dir)
    yield module, seed_dir, fixture_dir


def _write_seed(seed_dir: Path, seed_id: str, subject: str = "hi") -> None:
    (seed_dir / f"{seed_id}.json").write_text(
        json.dumps(
            {
                "id": seed_id,
                "sender_email": "a@b.com",
                "sender_name": "Alice",
                "sender_domain": "b.com",
                "recipients": {"to": ["me@x"], "cc": [], "bcc": []},
                "subject": subject,
                "body_text": "hello",
                "snippet": "hello",
                "received_at": "2026-07-16T12:00:00+00:00",
                "thread_depth": 1,
                "has_unsubscribe": False,
                "is_reply": False,
                "category": "work",
                "ground_truth_lane": "needs_you",
            }
        ),
        encoding="utf-8",
    )


def _write_fixture(
    fixture_dir: Path,
    seed_id: str,
    *,
    prompt_hash: str,
    seed_email_hash: str,
    provider: str = "anthropic",
) -> None:
    (fixture_dir / f"{seed_id}.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "seed_email_id": seed_id,
                "generated_at": datetime(2026, 7, 16, tzinfo=timezone.utc).isoformat(),
                "generator": {
                    "provider": provider,
                    "model": "claude-opus-4-7",
                    "agent_version": "triage-agent@0.1.0",
                    "prompt_hash": prompt_hash,
                    "seed_email_hash": seed_email_hash,
                },
                "triage": {
                    "lane": "needs_you",
                    "confidence": 0.9,
                    "reasoning": "Direct ask from known collaborator.",
                    "signals": [],
                },
                "draft_reply": {"included": False, "assumptions": []},
                "trace": {
                    "agent_steps": [
                        {"step": 1, "tool": None, "thought": "x", "output_snippet": "y"},
                    ],
                    "tokens": {"input": 100, "output": 50},
                    "cost_usd_at_generation": 0.01,
                    "latency_ms_live": 1400,
                },
                "playback": {"simulated_latency_ms_range": [1000, 1500], "stream_chunks": None},
            }
        ),
        encoding="utf-8",
    )


def test_empty_dirs_return_zero(freshness_module):
    module, _, _ = freshness_module
    assert module.check() == 0


def test_fresh_real_fixtures_return_zero(freshness_module):
    module, seed_dir, fixture_dir = freshness_module
    from winnow_api.agents.prompts import prompt_hash as current_ph
    from winnow_seed_data.hashes import seed_email_hash
    from winnow_seed_data.seed_email_schema import SeedEmail

    _write_seed(seed_dir, "seed_001")
    seed = SeedEmail.model_validate_json((seed_dir / "seed_001.json").read_text())
    _write_fixture(
        fixture_dir,
        "seed_001",
        prompt_hash=current_ph(),
        seed_email_hash=seed_email_hash(seed),
    )
    assert module.check() == 0


def test_prompt_hash_drift_fails(freshness_module):
    module, seed_dir, fixture_dir = freshness_module
    from winnow_seed_data.hashes import seed_email_hash
    from winnow_seed_data.seed_email_schema import SeedEmail

    _write_seed(seed_dir, "seed_001")
    seed = SeedEmail.model_validate_json((seed_dir / "seed_001.json").read_text())
    _write_fixture(
        fixture_dir,
        "seed_001",
        prompt_hash="sha256:" + "0" * 64,  # deliberately wrong
        seed_email_hash=seed_email_hash(seed),
    )
    assert module.check() == 1


def test_seed_hash_drift_fails(freshness_module):
    module, seed_dir, fixture_dir = freshness_module
    from winnow_api.agents.prompts import prompt_hash as current_ph

    _write_seed(seed_dir, "seed_001")
    _write_fixture(
        fixture_dir,
        "seed_001",
        prompt_hash=current_ph(),
        seed_email_hash="sha256:" + "f" * 64,  # deliberately wrong
    )
    assert module.check() == 1


def test_stub_fixtures_ignored(freshness_module):
    """Stub fixtures have placeholder hashes; the gate must not fail on them."""
    module, seed_dir, fixture_dir = freshness_module

    _write_seed(seed_dir, "seed_001")
    _write_fixture(
        fixture_dir,
        "seed_001",
        prompt_hash="sha256:" + "0" * 64,
        seed_email_hash="sha256:" + "0" * 64,
        provider="stub",
    )
    assert module.check() == 0


def test_orphan_fixture_does_not_fail(freshness_module, capsys):
    """A fixture whose seed was removed is a warning, not a failure —
    orphans are cleaned up separately and shouldn't block merges."""
    module, seed_dir, fixture_dir = freshness_module
    from winnow_api.agents.prompts import prompt_hash as current_ph

    # no seed written; fixture references seed_002
    _write_fixture(
        fixture_dir,
        "seed_002",
        prompt_hash=current_ph(),
        seed_email_hash="sha256:" + "1" * 64,
    )
    assert module.check() == 0
    captured = capsys.readouterr()
    assert "Orphaned" in captured.err
