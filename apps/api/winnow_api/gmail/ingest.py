"""One Gmail message → one Email row + one TriageDecision.

Owns the mapping between Gmail's raw payload shape and Winnow's
``Email`` ORM row, plus the call into the triage orchestrator so
ingestion and classification stay one atomic operation. Doing it
elsewhere would risk half-classified rows if the classifier crashed
after the Email was persisted.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from winnow_api.classifier import Classifier
from winnow_api.db.models import Email, TriageDecision
from winnow_api.gmail.client import GmailMessage

log = structlog.get_logger(__name__)


def ingest_message(
    db: Session,
    user_id: uuid.UUID,
    msg: GmailMessage,
    classifier: Classifier | None,
) -> tuple[Email, TriageDecision] | None:
    """Insert ``msg`` as an Email + initial TriageDecision.

    Idempotent on ``(user_id, gmail_message_id)`` — the unique index is
    enforced by ``uq_emails_user_gmail_msg`` in migration 0001, but we
    also do an explicit lookup so callers get a friendly None instead
    of an IntegrityError on the retry path.
    """
    existing = db.execute(
        select(Email).where(
            Email.user_id == user_id,
            Email.gmail_message_id == msg.gmail_message_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None

    email_row = Email(
        user_id=user_id,
        gmail_message_id=msg.gmail_message_id,
        gmail_thread_id=msg.gmail_thread_id,
        sender_email=msg.sender_email,
        sender_name=msg.sender_name,
        sender_domain=msg.sender_domain,
        recipients=msg.recipients,
        subject=msg.subject,
        body_text=msg.body_text,
        body_html=msg.body_html,
        snippet=msg.snippet,
        received_at=msg.received_at,
        thread_depth=msg.thread_depth,
        has_unsubscribe=msg.has_unsubscribe,
        is_reply=msg.is_reply,
    )
    db.add(email_row)
    db.flush()  # populate email_row.id for the TriageDecision FK

    if classifier is None:
        # Fallback used only in tests that don't want to load MiniLM.
        # In production, main.py always provides a classifier.
        decision = TriageDecision(
            email_id=email_row.id,
            user_id=user_id,
            lane="informational",
            confidence=0.0,
            tier=1,
            classifier_version="no-classifier",
            reasoning="Ingested without classifier available.",
            latency_ms=0,
        )
    else:
        result = classifier.predict_one(email_row)
        decision = TriageDecision(
            email_id=email_row.id,
            user_id=user_id,
            lane=result.lane,
            confidence=result.confidence,
            tier=1,
            classifier_version=result.classifier_version,
            top_features=result.top_features_json(),
            reasoning=(
                f"Classified as {result.lane} at {result.confidence:.0%} confidence."
            ),
            latency_ms=result.latency_ms,
        )
    db.add(decision)
    return email_row, decision
