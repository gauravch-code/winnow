"""Real-mode Gmail HTTP surface.

Registered by ``main.py`` only when WINNOW_MODE=real. Two endpoints:

- ``POST /gmail/webhook`` — Pub/Sub push receiver. Verifies the JWT
  and triggers an incremental sync. Returns 204 fast so Pub/Sub
  doesn't retry — sync happens in the response cycle for now
  (a background task queue is a Step 9 concern).
- ``POST /gmail/sync`` — manual trigger; useful when Pub/Sub isn't
  set up or during dev.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from winnow_api.db.models import User
from winnow_api.gmail.client import GmailClient
from winnow_api.gmail.oauth import load_credentials_for_user
from winnow_api.gmail.pubsub import (
    InvalidPubSubToken,
    decode_pubsub_envelope,
    verify_pubsub_jwt,
)
from winnow_api.gmail.sync import GmailSync

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/gmail", tags=["gmail"])


def get_db(request: Request) -> Session:
    engine = request.app.state.engine
    session = Session(bind=engine, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()


def _owner(db: Session) -> User:
    user = db.execute(select(User).limit(1)).scalar_one_or_none()
    if user is None:
        raise HTTPException(500, "No owner user. Run `winnow bootstrap` first.")
    return user


class SyncSummary(BaseModel):
    ingested: int
    skipped_duplicate: int
    ended_history_id: str | None
    strategy: str


@router.post("/sync", response_model=SyncSummary)
def sync_now(request: Request, db: Session = Depends(get_db)) -> SyncSummary:
    """Manual incremental sync. First call falls back to a 30-day backfill."""
    user = _owner(db)
    creds = load_credentials_for_user(user)
    client = GmailClient(creds)
    classifier = getattr(request.app.state, "classifier", None)
    report = GmailSync(client, db, user, classifier).sync_incremental()
    return SyncSummary(**report.__dict__)


@router.post("/webhook", status_code=204)
async def pubsub_webhook(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> None:
    """Pub/Sub push receiver.

    Verifies the JWT audience against WINNOW_PUBSUB_AUDIENCE (the URL
    Google was configured to push to). Rejects anything that fails.
    """
    settings = request.app.state.settings
    expected_audience = settings.pubsub_audience
    if not expected_audience:
        raise HTTPException(500, "WINNOW_PUBSUB_AUDIENCE not configured; refusing webhook.")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    try:
        verify_pubsub_jwt(authorization.split(" ", 1)[1], expected_audience)
    except InvalidPubSubToken as exc:
        log.warning("pubsub_invalid_token", error=str(exc))
        raise HTTPException(401, "Invalid Pub/Sub token") from exc

    body = await request.json()
    try:
        payload = decode_pubsub_envelope(body)
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, f"Bad Pub/Sub envelope: {exc}") from exc

    log.info("pubsub_notification_received", history_id=payload.get("historyId"))

    user = _owner(db)
    creds = load_credentials_for_user(user)
    client = GmailClient(creds)
    classifier = getattr(request.app.state, "classifier", None)
    GmailSync(client, db, user, classifier).sync_incremental()
