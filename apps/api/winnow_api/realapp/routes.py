"""Real-mode dashboard endpoints (owner-scoped).

The self-hosted app has a single owner (one row in ``users``). These
endpoints read and mutate that owner's triaged mail:

- ``GET  /emails``                 list, newest first, optional ?lane= filter
- ``PATCH /emails/{id}/lane``      move between lanes
- ``POST /emails/{id}/archive``    → hidden lane + training signal
- ``POST /emails/{id}/star``       → needs_you lane + training signal
- ``POST /emails/{id}/escalate``   force tier-2 (live LLM, your key)

Every mutation that carries a triage signal writes a ``TrainingExample``
so the nightly retrainer learns from your real corrections. Ingestion
(Gmail sync) stays tier-1 only — escalation to the paid LLM is always an
explicit, on-demand click, never a surprise cost on every sync.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.orm import Session, aliased

from winnow_api.db.models import Action, Email, TriageDecision, User
from winnow_api.learning.action_labels import label_from_action
from winnow_api.learning.training_writer import write_training_example
from winnow_api.triage import orchestrate_triage

log = structlog.get_logger(__name__)

router = APIRouter(tags=["app"])

Lane = Literal["needs_you", "informational", "hidden"]


class EmailView(BaseModel):
    id: uuid.UUID
    gmail_message_id: str | None
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
    engine = request.app.state.engine
    session = Session(bind=engine, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()


def _owner(db: Session) -> User:
    """The single self-hosted owner. Guaranteed present in real mode by the
    boot invariant, but we surface a clear error rather than assume."""
    user = db.execute(select(User).limit(1)).scalar_one_or_none()
    if user is None:
        raise HTTPException(500, "No owner user. Run `winnow bootstrap` first.")
    return user


def _current_decision(db: Session, email_id: uuid.UUID, user_id: uuid.UUID) -> TriageDecision | None:
    return db.execute(
        select(TriageDecision).where(
            and_(
                TriageDecision.email_id == email_id,
                TriageDecision.user_id == user_id,
                TriageDecision.superseded_at.is_(None),
            )
        )
    ).scalar_one_or_none()


def _view(email: Email, decision: TriageDecision) -> EmailView:
    return EmailView(
        id=email.id,
        gmail_message_id=email.gmail_message_id,
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


@router.get("/emails", response_model=list[EmailView])
def list_emails(
    request: Request,
    lane: Lane | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[EmailView]:
    owner = _owner(db)

    latest = (
        select(TriageDecision)
        .where(
            and_(
                TriageDecision.user_id == owner.id,
                TriageDecision.superseded_at.is_(None),
            )
        )
        .subquery()
    )
    LatestDecision = aliased(TriageDecision, latest)

    stmt = (
        select(Email, LatestDecision)
        .join(LatestDecision, LatestDecision.email_id == Email.id)
        .where(Email.user_id == owner.id)
        .order_by(Email.received_at.desc())
    )
    if lane is not None:
        stmt = stmt.where(LatestDecision.lane == lane)

    rows = db.execute(stmt).all()
    return [_view(email, decision) for email, decision in rows]


def _relane(
    db: Session,
    owner: User,
    email: Email,
    to_lane: str,
    *,
    action_type: str,
    label_source_action: str,
) -> TriageDecision:
    """Shared path for lane move / archive / star: supersede the current
    decision, record the Action, write a training example, and insert the
    new user-labeled decision. Returns the new decision."""
    now = datetime.now(timezone.utc)
    current = _current_decision(db, email.id, owner.id)
    from_lane = current.lane if current else None

    if from_lane == to_lane and current is not None:
        return current  # no-op; don't clutter history

    if current is not None:
        current.superseded_at = now

    db.add(
        Action(
            email_id=email.id,
            user_id=owner.id,
            action_type=action_type,
            from_lane=from_lane,
            to_lane=to_lane,
        )
    )

    resolved = label_from_action(label_source_action, to_lane)
    if resolved is not None:
        write_training_example(
            db, email, label=resolved[0], label_source=resolved[1], user_id=owner.id
        )

    new_decision = TriageDecision(
        email_id=email.id,
        user_id=owner.id,
        lane=to_lane,
        confidence=1.0,  # user-labeled = ground truth
        tier=1,
        classifier_version="user-override",
        reasoning=f"You {action_type.replace('_', ' ')} this email.",
        latency_ms=0,
    )
    db.add(new_decision)
    db.commit()
    db.refresh(new_decision)
    return new_decision


def _get_owned_email(db: Session, owner: User, email_id: uuid.UUID) -> Email:
    email = db.execute(
        select(Email).where(and_(Email.id == email_id, Email.user_id == owner.id))
    ).scalar_one_or_none()
    if email is None:
        raise HTTPException(404, "Email not found")
    return email


@router.patch("/emails/{email_id}/lane", response_model=EmailView)
def move_email(
    email_id: uuid.UUID,
    body: MoveRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> EmailView:
    owner = _owner(db)
    email = _get_owned_email(db, owner, email_id)
    decision = _relane(
        db, owner, email, body.to_lane,
        action_type="lane_moved", label_source_action="lane_moved",
    )
    return _view(email, decision)


@router.post("/emails/{email_id}/archive", response_model=EmailView)
def archive_email(email_id: uuid.UUID, request: Request, db: Session = Depends(get_db)) -> EmailView:
    owner = _owner(db)
    email = _get_owned_email(db, owner, email_id)
    decision = _relane(
        db, owner, email, "hidden",
        action_type="archived", label_source_action="archived",
    )
    return _view(email, decision)


@router.post("/emails/{email_id}/star", response_model=EmailView)
def star_email(email_id: uuid.UUID, request: Request, db: Session = Depends(get_db)) -> EmailView:
    owner = _owner(db)
    email = _get_owned_email(db, owner, email_id)
    decision = _relane(
        db, owner, email, "needs_you",
        action_type="starred", label_source_action="starred",
    )
    return _view(email, decision)


@router.post("/emails/{email_id}/escalate", response_model=EscalateResponse)
async def escalate_email(
    email_id: uuid.UUID, request: Request, db: Session = Depends(get_db)
) -> EscalateResponse:
    """Force tier-2 for one email — a live LLM call with your own key.

    This is the only place the real app spends money, and only when you
    click it. Persists the tier-2 result (lane + draft) as a superseding
    decision so the dashboard stays consistent on refresh.
    """
    owner = _owner(db)
    email = _get_owned_email(db, owner, email_id)

    classifier = getattr(request.app.state, "classifier", None)
    tier_2_provider = getattr(request.app.state, "tier_2_provider", None)
    if classifier is None:
        raise HTTPException(503, "Classifier not loaded — cannot escalate.")
    if tier_2_provider is None:
        raise HTTPException(
            503,
            "Tier-2 is not configured. Set WINNOW_LLM_API_KEY (and "
            "WINNOW_LLM_PROVIDER) and restart to enable the LLM tier.",
        )

    # force_tier_2=True makes the threshold moot here, but we pass the
    # owner's configured threshold so the outcome object is coherent.
    outcome = await orchestrate_triage(
        email=email,
        classifier=classifier,
        threshold=owner.confidence_threshold,
        tier_2_provider=tier_2_provider,
        force_tier_2=True,
    )

    now = datetime.now(timezone.utc)
    current = _current_decision(db, email.id, owner.id)

    if outcome.tier_2 is not None:
        if current is not None:
            current.superseded_at = now
        draft = outcome.tier_2.draft_reply
        db.add(
            TriageDecision(
                email_id=email.id,
                user_id=owner.id,
                lane=outcome.tier_2.lane,
                confidence=outcome.tier_2.confidence,
                tier=2,
                tier_2_source=outcome.tier_2_source,
                classifier_version=None,
                top_features=[s.model_dump() for s in outcome.tier_2.signals],
                reasoning=outcome.tier_2.reasoning,
                agent_trace={
                    "draft_included": draft.included,
                    "draft_subject": draft.subject,
                    "draft_body_markdown": draft.body_markdown,
                    "draft_tone": draft.tone,
                    "draft_assumptions": list(draft.assumptions),
                    "route": outcome.route.value,
                },
                latency_ms=0,
            )
        )
        db.commit()
        return EscalateResponse(
            email_id=email.id,
            route=outcome.route.value,
            tier_2_source=outcome.tier_2_source or "live",
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

    return EscalateResponse(
        email_id=email.id,
        route=outcome.route.value,
        tier_2_source=outcome.tier_2_source or "unavailable",
        reason_unavailable=outcome.tier_2_reason_unavailable,
    )
