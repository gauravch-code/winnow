"""End-to-end sync test with a mocked Gmail client.

The mocked client returns hand-authored raw payloads. The sync engine
then walks the real DB path: Email rows land, TriageDecisions land, and
``gmail_state.history_id`` advances. This locks the ingestion contract
without needing a real Gmail account.

Requires WINNOW_MODE=real because we import ``winnow_api.gmail.sync``
which is gated. Skips cleanly under WINNOW_MODE=demo.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

if os.environ.get("WINNOW_MODE", "demo") != "real":
    pytest.skip(
        "winnow_api.gmail is real-mode only; set WINNOW_MODE=real to run.",
        allow_module_level=True,
    )

from sqlalchemy.orm import Session

from winnow_api.db.models import Email, TriageDecision, User
from winnow_api.gmail.client import GmailMessage, HistoryExpired
from winnow_api.gmail.sync import GmailSync


class _MockGmailClient:
    """In-memory Gmail. Deterministic, no network."""

    def __init__(self, messages: list[GmailMessage], history_id: str = "12345"):
        self._messages = {m.gmail_message_id: m for m in messages}
        self._history_id = history_id
        self._history_records: list[dict] = []
        self._raise_history_expired = False

    def enqueue_history(self, message_id: str) -> None:
        self._history_records.append(
            {"messagesAdded": [{"message": {"id": message_id}}]}
        )

    def raise_history_expired(self) -> None:
        self._raise_history_expired = True

    def get_profile(self) -> dict:
        return {"emailAddress": "me@example.com", "historyId": self._history_id}

    def list_messages_since(self, since, page_size: int = 100):
        return iter(self._messages.keys())

    def list_history(self, start_history_id: str):
        if self._raise_history_expired:
            raise HistoryExpired("stale")
        return iter(self._history_records)

    def get_message(self, message_id: str) -> GmailMessage:
        return self._messages[message_id]


def _msg(gid: str = "M1", subject: str = "hi", sender: str = "a@b.com") -> GmailMessage:
    domain = sender.split("@")[1] if "@" in sender else ""
    return GmailMessage(
        gmail_message_id=gid,
        gmail_thread_id=f"T-{gid}",
        sender_email=sender,
        sender_name=None,
        sender_domain=domain,
        recipients={"to": ["me@example.com"], "cc": [], "bcc": []},
        subject=subject,
        body_text="body",
        body_html=None,
        snippet=subject[:80],
        received_at=datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc),
        thread_depth=1,
        has_unsubscribe=False,
        is_reply=False,
        label_ids=["INBOX"],
    )


@pytest.fixture
def owner(db: Session) -> User:
    db.query(User).delete()
    db.commit()
    u = User(email=f"owner-{uuid.uuid4()}@example.com")
    db.add(u)
    db.commit()
    yield u
    db.query(User).delete()
    db.commit()


def test_full_sync_ingests_messages_and_advances_history(owner: User, db: Session):
    client = _MockGmailClient(
        [_msg("M1", "one"), _msg("M2", "two")],
        history_id="H-100",
    )
    sync = GmailSync(client, db, owner, classifier=None)  # type: ignore[arg-type]

    report = sync.sync_full(days=30)

    assert report.strategy == "full"
    assert report.ingested == 2
    assert report.skipped_duplicate == 0
    assert report.ended_history_id == "H-100"

    emails = db.query(Email).filter(Email.user_id == owner.id).all()
    assert {e.gmail_message_id for e in emails} == {"M1", "M2"}

    decisions = db.query(TriageDecision).filter(TriageDecision.user_id == owner.id).all()
    assert len(decisions) == 2

    db.refresh(owner)
    assert owner.gmail_state["history_id"] == "H-100"
    assert "last_sync_at" in owner.gmail_state


def test_second_full_sync_is_idempotent(owner: User, db: Session):
    """Rerunning full sync on the same messages must not double-insert."""
    client = _MockGmailClient([_msg("M1"), _msg("M2")], history_id="H-1")
    sync = GmailSync(client, db, owner, classifier=None)  # type: ignore[arg-type]
    first = sync.sync_full()
    second = sync.sync_full()

    assert first.ingested == 2
    assert second.ingested == 0
    assert second.skipped_duplicate == 2
    assert db.query(Email).filter(Email.user_id == owner.id).count() == 2


def test_incremental_sync_only_ingests_history_messages(owner: User, db: Session):
    client = _MockGmailClient(
        [_msg("M-old"), _msg("M-new")],
        history_id="H-200",
    )
    # Seed state so incremental doesn't fall back to full.
    owner.gmail_state = {"history_id": "H-100"}
    db.commit()

    # Only M-new appears in history — M-old already existed before H-100.
    client.enqueue_history("M-new")

    sync = GmailSync(client, db, owner, classifier=None)  # type: ignore[arg-type]
    report = sync.sync_incremental()

    assert report.strategy == "incremental"
    assert report.ingested == 1
    ingested_ids = [e.gmail_message_id for e in db.query(Email).filter(Email.user_id == owner.id).all()]
    assert ingested_ids == ["M-new"]

    db.refresh(owner)
    assert owner.gmail_state["history_id"] == "H-200"


def test_incremental_falls_back_to_full_when_history_expired(owner: User, db: Session):
    client = _MockGmailClient([_msg("M1"), _msg("M2")], history_id="H-300")
    owner.gmail_state = {"history_id": "H-ancient"}
    db.commit()
    client.raise_history_expired()

    sync = GmailSync(client, db, owner, classifier=None)  # type: ignore[arg-type]
    report = sync.sync_incremental()

    assert report.strategy == "incremental-fallback-full"
    assert report.ingested == 2
    db.refresh(owner)
    assert owner.gmail_state["history_id"] == "H-300"


def test_incremental_without_prior_history_falls_back_to_full(owner: User, db: Session):
    client = _MockGmailClient([_msg("M1")], history_id="H-1")
    # owner.gmail_state is None
    sync = GmailSync(client, db, owner, classifier=None)  # type: ignore[arg-type]
    report = sync.sync_incremental()
    assert report.strategy == "incremental-fallback-full"
    assert report.ingested == 1
