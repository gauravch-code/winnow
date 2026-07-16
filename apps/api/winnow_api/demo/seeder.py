"""Seed a fresh demo session with N synthetic emails.

Called lazily on the first ``GET /demo/emails`` for a session. Idempotent —
a session that already owns emails is left alone.

Initial lane assignment uses each seed email's ``ground_truth_lane`` so
the demo has a plausible starting state before the classifier is trained.
Once the classifier tier lands (Step 4), this initial assignment is
replaced by real tier-1 inference.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from winnow_api.db.models import Email, TriageDecision
from winnow_seed_data.seed_email_schema import SeedEmail

log = structlog.get_logger(__name__)


def _load_seeds(seed_dir: Path, limit: int) -> list[SeedEmail]:
    files = sorted(seed_dir.glob("seed_*.json"))[:limit]
    seeds: list[SeedEmail] = []
    for path in files:
        seeds.append(SeedEmail.model_validate_json(path.read_text(encoding="utf-8")))
    return seeds


def ensure_session_seeded(
    db: Session,
    session_id: uuid.UUID,
    seed_dir: Path,
    count: int,
) -> int:
    """Insert ``count`` emails + initial triage decisions if the session is empty.

    Returns the number of emails inserted (0 if already seeded).
    """
    existing = db.execute(
        select(Email.id).where(Email.session_id == session_id).limit(1)
    ).first()
    if existing is not None:
        return 0

    seeds = _load_seeds(seed_dir, count)
    if not seeds:
        log.warning("no_seed_emails_found", seed_dir=str(seed_dir))
        return 0

    inserted = 0
    for seed in seeds:
        email = Email(
            session_id=session_id,
            seed_email_id=seed.id,
            sender_email=seed.sender_email,
            sender_name=seed.sender_name,
            sender_domain=seed.sender_domain,
            recipients=seed.recipients,
            subject=seed.subject,
            body_text=seed.body_text,
            snippet=seed.snippet,
            received_at=seed.received_at,
            thread_depth=seed.thread_depth,
            has_unsubscribe=seed.has_unsubscribe,
            is_reply=seed.is_reply,
        )
        db.add(email)
        db.flush()  # need email.id for the FK

        # Placeholder tier-1 decision using ground truth. Replaced by real
        # classifier inference in Step 4. Not marked prerecorded — this is
        # not a tier-2 pathway.
        decision = TriageDecision(
            email_id=email.id,
            session_id=session_id,
            lane=seed.ground_truth_lane,
            confidence=0.99,  # placeholder; classifier tier will overwrite
            tier=1,
            classifier_version="seeded-ground-truth",
            top_features=[{"name": "seed_ground_truth", "value": seed.category, "weight": 1.0}],
            reasoning=f"Initial seeded lane from category={seed.category}.",
            latency_ms=0,
        )
        db.add(decision)
        inserted += 1

    db.commit()
    log.info("demo_session_seeded", session_id=str(session_id), count=inserted)
    return inserted
