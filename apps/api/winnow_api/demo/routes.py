"""Demo-mode HTTP surface.

Three endpoints, all scoped to the current session:

- ``GET /demo/emails`` — auto-seeds on first hit, returns all emails
  with the current lane (latest non-superseded triage decision).
- ``PATCH /demo/emails/{email_id}/lane`` — records the user move as an
  ``Action`` and a new ``TriageDecision``; supersedes the previous one.
- ``POST /demo/emails/{email_id}/escalate`` — force tier-2. Reads from
  the fixture loader (or returns ``tier_2_source='unavailable'`` if the
  email has no pre-recorded response). Never makes a live LLM call.

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
from winnow_api.learning.action_labels import label_from_action
from winnow_api.learning.training_writer import write_training_example
from winnow_api.triage import TriageRouteDecision, orchestrate_triage

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
    classifier_version: str | None
    reasoning: str | None
    top_features: list[dict] | None


class MoveRequest(BaseModel):
    to_lane: Lane


class EscalateResponse(BaseModel):
    """Result of a forced tier-2 lookup. ``tier_2_source`` tells the UI
    whether to badge the response as pre-recorded or (in a hypothetical
    live-key demo) as live."""

    email_id: uuid.UUID
    route: str
    tier_2_source: str
    reason_unavailable: str | None = None
    lane: Lane | None = None
    confidence: float | None = None
    reasoning: str | None = None
    draft_included: bool | None = None
    draft_subject: str | None = None
    draft_body_markdown: str | None = None
    draft_tone: str | None = None
    draft_assumptions: list[str] | None = None
    signals: list[dict] | None = None


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
    classifier = getattr(request.app.state, "classifier", None)
    ensure_session_seeded(
        db, sid, settings.seed_email_dir, settings.demo_seed_count, classifier
    )

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

    return [_view(email, decision) for email, decision in rows]


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
    # Feed the learning loop: user's explicit correction is the strongest
    # possible training signal. Session-scoped rows cascade-delete with
    # the session, so this doesn't leak visitor labels into the owner's
    # future retrains.
    resolved = label_from_action("lane_moved", body.to_lane)
    if resolved is not None:
        write_training_example(
            db,
            email,
            label=resolved[0],
            label_source=resolved[1],
            session_id=sid,
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


@router.post("/emails/{email_id}/escalate", response_model=EscalateResponse)
async def escalate_email(
    email_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> EscalateResponse:
    """Force tier-2 for one email regardless of tier-1 confidence.

    Persists the tier-2 result as a superseding ``TriageDecision`` when
    it comes back (either lane or "unavailable" is recorded so the UI
    stays consistent on refresh). Demo mode always reads from the
    fixture loader; there are no live LLM calls here.
    """
    sid = _session_id(request)
    email = db.execute(
        select(Email).where(and_(Email.id == email_id, Email.session_id == sid))
    ).scalar_one_or_none()
    if email is None:
        raise HTTPException(404, "Email not found in this session")

    classifier = getattr(request.app.state, "classifier", None)
    tier_2_provider = getattr(request.app.state, "tier_2_provider", None)
    if classifier is None:
        raise HTTPException(503, "Classifier not loaded — cannot escalate.")

    settings = request.app.state.settings
    outcome = await orchestrate_triage(
        email=email,
        classifier=classifier,
        threshold=settings.demo_confidence_threshold,
        tier_2_provider=tier_2_provider,
        force_tier_2=True,
    )

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
    if current is not None:
        current.superseded_at = now

    if outcome.tier_2 is not None:
        decision = TriageDecision(
            email_id=email.id,
            session_id=sid,
            lane=outcome.tier_2.lane,
            confidence=outcome.tier_2.confidence,
            tier=2,
            tier_2_source=outcome.tier_2_source,
            classifier_version=None,
            top_features=[s.model_dump() for s in outcome.tier_2.signals],
            reasoning=outcome.tier_2.reasoning,
            agent_trace={
                "draft_included": outcome.tier_2.draft_reply.included,
                "route": outcome.route.value,
            },
            latency_ms=0,
        )
        db.add(decision)
        db.commit()

        draft = outcome.tier_2.draft_reply
        response = EscalateResponse(
            email_id=email.id,
            route=outcome.route.value,
            tier_2_source=outcome.tier_2_source or "unknown",
            lane=outcome.tier_2.lane,  # type: ignore[arg-type]
            confidence=outcome.tier_2.confidence,
            reasoning=outcome.tier_2.reasoning,
            signals=[s.model_dump() for s in outcome.tier_2.signals],
            draft_included=draft.included,
            draft_subject=draft.subject if draft.included else None,
            draft_body_markdown=draft.body_markdown if draft.included else None,
            draft_tone=draft.tone if draft.included else None,
            draft_assumptions=list(draft.assumptions) if draft.included else None,
        )
        return response

    # tier-2 unavailable — record an unavailable decision so the UI can
    # show the graceful "no fixture" state without re-querying.
    if current is not None:
        # No lane change; undo the supersede we did above.
        current.superseded_at = None
    db.commit()

    return EscalateResponse(
        email_id=email.id,
        route=outcome.route.value,
        tier_2_source=outcome.tier_2_source or "unavailable",
        reason_unavailable=outcome.tier_2_reason_unavailable,
    )


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
        classifier_version=decision.classifier_version,
        reasoning=decision.reasoning,
        top_features=decision.top_features,
    )
