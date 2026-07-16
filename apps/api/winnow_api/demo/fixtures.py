"""Pre-recorded tier-2 LLM response fixture loader.

Loaded once at FastAPI startup; O(1) lookup by ``seed_email_id`` on the
request path. This is what keeps the public demo at $0 — every tier-2
"call" resolves to a committed JSON file instead of a live LLM request.

Load semantics:

- Every ``.json`` file in ``fixture_dir`` is parsed and validated against
  ``FixtureResponse``. Invalid files are logged and skipped, not fatal —
  a broken fixture must not take the whole demo down.
- Filename must equal ``seed_email_id``. A mismatch is a load error;
  otherwise the orchestrator would serve fixture ``A`` while claiming it
  came from email ``B``.
- If ``fixture_dir`` is missing, the loader logs a warning and serves
  nothing. Every tier-2 lookup then returns ``None`` and the orchestrator
  emits an "unavailable" response.

Drift check (``verify_freshness``) is optional and advisory. It logs
structured warnings for fixtures whose stored ``prompt_hash`` or
``seed_email_hash`` no longer match the current values, but still serves
them. The hard gate against stale fixtures is CI's
``check-fixtures-fresh`` job, deferred to Step 6.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

import structlog
from pydantic import ValidationError

from winnow_seed_data.fixture_schema import FixtureResponse

log = structlog.get_logger(__name__)


class FixtureLoader:
    """In-memory index of pre-recorded tier-2 fixtures, keyed by seed_email_id."""

    def __init__(self, fixture_dir: Path) -> None:
        self.fixture_dir = Path(fixture_dir)
        self._fixtures: dict[str, FixtureResponse] = {}
        self._loaded = False

    def load(self) -> None:
        """Scan ``fixture_dir`` and populate the in-memory index.

        Safe to call once; subsequent calls no-op unless ``reset()`` is
        called first (only used in tests).
        """
        if self._loaded:
            return

        if not self.fixture_dir.exists():
            log.warning(
                "fixture_dir_missing",
                path=str(self.fixture_dir),
                message=(
                    "Fixture directory does not exist. Every tier-2 lookup will "
                    "return unavailable."
                ),
            )
            self._loaded = True
            return

        ok = 0
        bad = 0
        for path in sorted(self.fixture_dir.glob("*.json")):
            fixture = self._load_one(path)
            if fixture is None:
                bad += 1
                continue
            self._fixtures[fixture.seed_email_id] = fixture
            ok += 1

        log.info(
            "fixtures_loaded",
            ok=ok,
            bad=bad,
            dir=str(self.fixture_dir),
        )
        self._loaded = True

    def _load_one(self, path: Path) -> FixtureResponse | None:
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            log.error("fixture_read_failed", path=str(path), error=str(exc))
            return None

        try:
            fixture = FixtureResponse.model_validate(data)
        except ValidationError as exc:
            log.error(
                "fixture_schema_invalid",
                path=str(path),
                error=exc.errors(include_url=False),
            )
            return None

        if fixture.seed_email_id != path.stem:
            log.error(
                "fixture_id_mismatch",
                path=str(path),
                file_stem=path.stem,
                fixture_seed_email_id=fixture.seed_email_id,
                message="Filename must equal seed_email_id; fixture ignored.",
            )
            return None

        return fixture

    def verify_freshness(
        self,
        current_prompt_hash: str,
        current_seed_email_hashes: Mapping[str, str],
    ) -> list[str]:
        """Advisory drift check. Returns the list of stale seed_email_ids.

        The loader still serves stale fixtures; the CI job blocks merges.
        This method exists so a stale fixture surfaces in production
        logs, not only in CI where I might not be looking.

        ``current_seed_email_hashes`` is a mapping from seed_email_id to
        the current sha256 of that seed email's canonical form. Missing
        keys are skipped (no email means nothing to compare against).
        """
        if not self._loaded:
            raise RuntimeError("FixtureLoader.load() must be called before verify_freshness().")

        stale: list[str] = []
        for seed_id, fixture in self._fixtures.items():
            reasons: list[str] = []
            if fixture.generator.prompt_hash != current_prompt_hash:
                reasons.append("prompt_hash")
            expected = current_seed_email_hashes.get(seed_id)
            if expected is not None and fixture.generator.seed_email_hash != expected:
                reasons.append("seed_email_hash")

            if reasons:
                stale.append(seed_id)
                log.warning(
                    "fixture_stale",
                    seed_email_id=seed_id,
                    reasons=reasons,
                    message=(
                        "Fixture drift detected. Re-run "
                        "packages/seed-data/generate.py before the next merge."
                    ),
                )

        return stale

    def get(self, seed_email_id: str) -> FixtureResponse | None:
        """Return the fixture for ``seed_email_id`` or ``None`` if absent.

        ``None`` is the signal for the orchestrator to emit an
        "unavailable" tier-2 response and render the "run locally" card.
        """
        return self._fixtures.get(seed_email_id)

    def all_ids(self) -> set[str]:
        return set(self._fixtures.keys())

    def __len__(self) -> int:
        return len(self._fixtures)

    def reset(self) -> None:
        """Test-only. Clear state so ``load()`` can be re-run."""
        self._fixtures.clear()
        self._loaded = False
