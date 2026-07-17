"""Seed a fresh demo session with N synthetic emails.

Called lazily on the first ``GET /demo/emails`` for a session. Idempotent —
a session that already owns emails is left alone.

Initial lane assignments come from real tier-1 classifier inference
against the seed emails' content — the demo shows what a fresh Winnow
install would do on a fresh inbox, not what the ground-truth labels say.
User PATCH overrides always win (they're stored as a superseding
``TriageDecision`` with ``classifier_version='user-override'``).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from winnow_api.classifier import Classifier
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
    classifier: Classifier | None,
) -> int:
    """Insert ``count`` emails + initial triage decisions if the session is empty.

    Returns the number of emails inserted (0 if already seeded).

    If ``classifier`` is None, falls back to each seed email's
    ``ground_truth_lane`` — used only in tests that don't want to load
    the ~90MB embedding model.
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

    # Build all Email rows first; classify in a single batch (one embedding
    # pass, one predict call) rather than N per-email round trips.
    emails: list[Email] = []
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
        emails.append(email)
    db.flush()  # populate email.id for FK targets

    if classifier is not None:
        results = classifier.predict_many(emails)
        for email, seed, result in zip(emails, seeds, results):
            db.add(
                TriageDecision(
                    email_id=email.id,
                    session_id=session_id,
                    lane=result.lane,
                    confidence=result.confidence,
                    tier=1,
                    classifier_version=result.classifier_version,
                    top_features=result.top_features_json(),
                    reasoning=_reasoning(result),
                    latency_ms=result.latency_ms,
                )
            )
    else:
        for email, seed in zip(emails, seeds):
            db.add(
                TriageDecision(
                    email_id=email.id,
                    session_id=session_id,
                    lane=seed.ground_truth_lane,
                    confidence=0.99,
                    tier=1,
                    classifier_version="seeded-ground-truth",
                    top_features=[
                        {"name": "seed_ground_truth", "value": 1.0, "weight": 1.0}
                    ],
                    reasoning=f"Initial seeded lane from category={seed.category}.",
                    latency_ms=0,
                )
            )

    db.commit()
    log.info(
        "demo_session_seeded",
        session_id=str(session_id),
        count=len(emails),
        classifier=classifier.version if classifier else "ground-truth",
    )
    return len(emails)


def _reasoning(result) -> str:
    """One-line human summary. Explainability panel gets the full top_features."""
    top = result.top_features[0] if result.top_features else None
    if top is None:
        return f"Classified as {result.lane} at {result.confidence:.0%} confidence."
    direction = "positive" if top.weight > 0 else "negative"
    return (
        f"Classified as {result.lane} at {result.confidence:.0%} confidence; "
        f"strongest signal: {top.name} ({direction})."
    )
