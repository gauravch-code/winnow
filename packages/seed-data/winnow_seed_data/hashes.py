"""Canonical hashing for fixture drift detection.

Two hashes are stored in every fixture and both are the input to CI's
``check-fixtures-fresh`` gate:

- ``seed_email_hash`` — deterministic hash of the seed email's
  canonical JSON form. Changes when the seed corpus is regenerated.
- ``prompt_hash`` — byte-for-byte hash of the tier-2 agent's system
  prompt. Changes when the prompt is edited.

Determinism is load-bearing: two runs of ``generate.py`` against the
same inputs must produce identical hashes, or CI would fail spuriously
on every PR. Uses ``json.dumps(sort_keys=True, separators=...)`` because
Pydantic's ``model_dump_json`` does not guarantee key ordering.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from winnow_seed_data.seed_email_schema import SeedEmail


def _canonical_json(payload: Any) -> str:
    """Sorted keys, compact separators, ISO datetimes.

    Kept private because the exact form is an implementation detail —
    callers only care that ``sha256(canonical_json(x)) == sha256(canonical_json(x))``.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,  # datetimes → ISO strings via SeedEmail.model_dump(mode='json')
    )


def seed_email_hash(seed: SeedEmail) -> str:
    """Canonical sha256 of a seed email. Prefixed 'sha256:' to match the
    fixture schema pattern."""
    dumped = seed.model_dump(mode="json")
    digest = hashlib.sha256(_canonical_json(dumped).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def bulk_seed_hashes(seeds: list[SeedEmail]) -> dict[str, str]:
    """Return {seed_email_id: hash} for a list of seeds. Convenience for the
    fixture loader's ``verify_freshness`` and the CI check."""
    return {s.id: seed_email_hash(s) for s in seeds}
