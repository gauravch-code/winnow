"""CI merge gate for tier-2 fixtures.

Compares the ``prompt_hash`` and ``seed_email_hash`` stored in every
committed fixture against the values computed from the *current* prompt
and seed corpus. A mismatch means the fixture is stale — someone
changed the prompt or a seed email but didn't regenerate the fixtures.

Exits 0 if all fixtures are fresh (or if there are no fixtures at all —
CI shouldn't fail on an empty state).

Exits 1 if any fixture is stale. The report lists exactly which
fixtures need regeneration and why, so the fix is one ``uv run python
packages/seed-data/generate.py --only ...`` away.

Usage:
    uv run python packages/seed-data/check_fixtures_fresh.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from winnow_api.agents.prompts import prompt_hash as current_prompt_hash
from winnow_seed_data.fixture_schema import FixtureResponse
from winnow_seed_data.hashes import bulk_seed_hashes
from winnow_seed_data.seed_email_schema import SeedEmail

SEED_DIR = Path(__file__).parent / "emails"
FIXTURE_DIR = Path(__file__).parent / "llm-responses"

# Stub fixtures live alongside real ones and are not subject to the
# prompt-hash check — they have their own placeholder hash. The freshness
# gate targets real LLM fixtures.
STUB_PROVIDER = "stub"


def _load_seeds() -> list[SeedEmail]:
    return [
        SeedEmail.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(SEED_DIR.glob("seed_*.json"))
    ]


def _load_fixtures() -> list[tuple[Path, FixtureResponse]]:
    fixtures: list[tuple[Path, FixtureResponse]] = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        try:
            fx = FixtureResponse.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"::error file={path}::Invalid fixture: {exc}", file=sys.stderr)
            continue
        fixtures.append((path, fx))
    return fixtures


def check() -> int:
    if not FIXTURE_DIR.exists():
        print("No fixture directory yet — nothing to check.")
        return 0

    fixtures = _load_fixtures()
    if not fixtures:
        print("No fixtures found — nothing to check.")
        return 0

    seeds = _load_seeds()
    seed_hashes = bulk_seed_hashes(seeds)
    seed_ids_present = {s.id for s in seeds}

    expected_prompt_hash = current_prompt_hash()
    stale: list[tuple[str, list[str]]] = []
    orphaned: list[str] = []
    checked_real = 0
    skipped_stub = 0

    for path, fx in fixtures:
        # Skip stub fixtures — they are placeholder content generated
        # without an LLM call, tracked separately.
        if fx.generator.provider == STUB_PROVIDER:
            skipped_stub += 1
            continue
        checked_real += 1

        reasons: list[str] = []
        if fx.seed_email_id not in seed_ids_present:
            orphaned.append(fx.seed_email_id)
            continue
        if fx.generator.prompt_hash != expected_prompt_hash:
            reasons.append(f"prompt_hash drift (fixture={fx.generator.prompt_hash[:23]}..., expected={expected_prompt_hash[:23]}...)")
        expected_seed_hash = seed_hashes.get(fx.seed_email_id)
        if expected_seed_hash and fx.generator.seed_email_hash != expected_seed_hash:
            reasons.append("seed_email_hash drift (seed content changed)")
        if reasons:
            stale.append((fx.seed_email_id, reasons))

    if orphaned:
        print("Orphaned fixtures (no matching seed email):", file=sys.stderr)
        for sid in orphaned:
            print(f"  - {sid}", file=sys.stderr)

    if stale:
        print(f"\n{len(stale)} stale fixture(s):", file=sys.stderr)
        for sid, reasons in stale:
            print(f"  {sid}:", file=sys.stderr)
            for r in reasons:
                print(f"    - {r}", file=sys.stderr)
        print(
            "\nRegenerate with:  uv run python packages/seed-data/generate.py "
            f"--only {','.join(sid for sid, _ in stale)}",
            file=sys.stderr,
        )
        return 1
    if orphaned:
        # Orphans are a soft signal — don't fail CI, but do warn.
        print("(Orphans logged as warnings only; CI is not failing on them.)")
    if checked_real == 0:
        print(
            f"No real (non-stub) fixtures found — {skipped_stub} stub fixture(s) skipped. "
            "Freshness gate has nothing to enforce yet."
        )
    else:
        print(
            f"All {checked_real} real fixture(s) fresh against current prompt + seed corpus "
            f"({skipped_stub} stub(s) skipped)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(check())
