"""Demo-mode HTTP surface.

Two endpoints only, both scoped to the current session:

- ``GET /demo/emails`` — auto-seeds on first hit, returns all emails
  with the current lane (latest non-superseded triage decision).
- ``PATCH /demo/emails/{email_id}/lane`` — records the user move as an
  ``Action`` and a new ``TriageDecision``; supersedes the previous one.

Kept in one file because the surface area is intentionally tiny — this
is a demo, not a REST API.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.orm import Session, aliased

from winnow_api.db.models import Action, DemoSession, Email, TriageDecision
from winnow_api.demo.seeder import ensure_session_seeded

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])

Lane = Literal["needs_you", "informational", "hidden"]


class EmailView(BaseModel):
    id: uuid.UUID
    seed_email_id: str | None
    sender_email: str
    sender_name: str | None
    subject: str
    snippet: str
    received_at: datetime
    lane: Lane
    confidence: float
    tier: int


class MoveRequest(BaseModel):
    to_lane: Lane


def get_db(request: Request) -> Session:
    """Per-request Session bound to the app's engine."""
    engine = request.app.state.engine
    session = Session(bind=engine, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()


def _session_id(request: Request) -> uuid.UUID:
    sid = getattr(request.state, "session_id", None)
    if sid is None:
        raise HTTPException(500, "Session middleware did not run")
    return sid


@router.get("/emails", response_model=list[EmailView])
def list_emails(request: Request, db: Session = Depends(get_db)) -> list[EmailView]:
    sid = _session_id(request)

    settings = request.app.state.settings
    ensure_session_seeded(db, sid, settings.seed_email_dir, settings.demo_seed_count)

    # Latest non-superseded decision per email, joined with the email row.
    latest = (
        select(TriageDecision)
        .where(
            and_(
                TriageDecision.session_id == sid,
                TriageDecision.superseded_at.is_(None),
            )
        )
        .subquery()
    )
    LatestDecision = aliased(TriageDecision, latest)

    rows = db.execute(
        select(Email, LatestDecision)
        .join(LatestDecision, LatestDecision.email_id == Email.id)
        .where(Email.session_id == sid)
        .order_by(Email.received_at.desc())
    ).all()

    return [
        EmailView(
            id=email.id,
            seed_email_id=email.seed_email_id,
            sender_email=email.sender_email,
            sender_name=email.sender_name,
            subject=email.subject,
            snippet=email.snippet or "",
            received_at=email.received_at,
            lane=decision.lane,  # type: ignore[arg-type]
            confidence=decision.confidence,
            tier=decision.tier,
        )
        for email, decision in rows
    ]


@router.patch("/emails/{email_id}/lane", response_model=EmailView)
def move_email(
    email_id: uuid.UUID,
    body: MoveRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> EmailView:
    sid = _session_id(request)

    email = db.execute(
        select(Email).where(and_(Email.id == email_id, Email.session_id == sid))
    ).scalar_one_or_none()
    if email is None:
        raise HTTPException(404, "Email not found in this session")

    now = datetime.now(timezone.utc)
    current = db.execute(
        select(TriageDecision).where(
            and_(
                TriageDecision.email_id == email.id,
                TriageDecision.session_id == sid,
                TriageDecision.superseded_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    from_lane = current.lane if current else None
    if from_lane == body.to_lane:
        # No-op move — return the current state without cluttering history.
        assert current is not None
        return _view(email, current)

    if current is not None:
        current.superseded_at = now

    db.add(
        Action(
            email_id=email.id,
            session_id=sid,
            action_type="lane_moved",
            from_lane=from_lane,
            to_lane=body.to_lane,
        )
    )
    new_decision = TriageDecision(
        email_id=email.id,
        session_id=sid,
        lane=body.to_lane,
        confidence=1.0,  # user-labeled = ground truth for this session
        tier=1,
        classifier_version="user-override",
        reasoning="User moved email to this lane.",
        latency_ms=0,
    )
    db.add(new_decision)
    db.commit()
    db.refresh(new_decision)
    return _view(email, new_decision)


def _view(email: Email, decision: TriageDecision) -> EmailView:
    return EmailView(
        id=email.id,
        seed_email_id=email.seed_email_id,
        sender_email=email.sender_email,
        sender_name=email.sender_name,
        subject=email.subject,
        snippet=email.snippet or "",
        received_at=email.received_at,
        lane=decision.lane,  # type: ignore[arg-type]
        confidence=decision.confidence,
        tier=decision.tier,
    )
