"""Hash determinism tests.

Every fixture's ``seed_email_hash`` and ``prompt_hash`` must be
identical across runs given identical inputs — otherwise CI's freshness
gate would false-positive on every PR.
"""

from __future__ import annotations

from datetime import datetime, timezone

from winnow_api.agents.prompts import prompt_hash
from winnow_seed_data.hashes import bulk_seed_hashes, seed_email_hash
from winnow_seed_data.seed_email_schema import SeedEmail


def _seed(id_: str = "seed_001", **overrides) -> SeedEmail:
    defaults = dict(
        id=id_,
        sender_email="a@b.com",
        sender_name="Alice",
        sender_domain="b.com",
        recipients={"to": ["me@x"], "cc": [], "bcc": []},
        subject="hi",
        body_text="hello",
        snippet="hello",
        received_at=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        thread_depth=1,
        has_unsubscribe=False,
        is_reply=False,
        category="work",
        ground_truth_lane="needs_you",
    )
    defaults.update(overrides)
    return SeedEmail(**defaults)


def test_prompt_hash_is_deterministic():
    assert prompt_hash() == prompt_hash()


def test_prompt_hash_format():
    h = prompt_hash()
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64
    assert all(c in "0123456789abcdef" for c in h[len("sha256:"):])


def test_seed_hash_deterministic():
    s = _seed()
    assert seed_email_hash(s) == seed_email_hash(s)


def test_seed_hash_changes_when_content_changes():
    a = _seed(subject="hi")
    b = _seed(subject="hello")
    assert seed_email_hash(a) != seed_email_hash(b)


def test_seed_hash_stable_across_dict_key_order():
    """Key-ordering must not affect the hash — Pydantic and json can serialize
    with different orders across runs."""
    a = _seed(recipients={"to": ["me@x"], "cc": [], "bcc": []})
    b = _seed(recipients={"bcc": [], "cc": [], "to": ["me@x"]})
    assert seed_email_hash(a) == seed_email_hash(b)


def test_bulk_seed_hashes_shape():
    seeds = [_seed(id_=f"seed_{i:03d}") for i in range(1, 6)]
    out = bulk_seed_hashes(seeds)
    assert set(out.keys()) == {f"seed_{i:03d}" for i in range(1, 6)}
    for h in out.values():
        assert h.startswith("sha256:")


def test_datetime_serialized_stably():
    """Two SeedEmail instances built at different wall times but with the
    same received_at must hash identically — the receive time is the
    content, wall-clock time is not."""
    s = _seed()
    h1 = seed_email_hash(s)
    # rebuild identically
    s2 = _seed()
    h2 = seed_email_hash(s2)
    assert h1 == h2
