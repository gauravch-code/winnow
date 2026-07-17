"""Backfill + incremental sync for one Gmail account.

Two entry points:

- ``sync_full(days)`` — initial backfill of the last N days. Idempotent
  on retry: ``ingest_message`` no-ops on ``(user_id, gmail_message_id)``
  collisions.
- ``sync_incremental()`` — reads ``gmail_state.history_id``, calls
  ``history.list``, ingests each new message. On ``HistoryExpired``
  (Gmail's ~7-day retention on history IDs), transparently falls back
  to a 7-day backfill. Callers do not need to handle the exception.

State bookkeeping is stashed in ``users.gmail_state`` — a JSONB blob
with ``history_id``, ``last_sync_at``, ``watch_expiration``,
``watch_topic``. Kept unstructured because it's Gmail-specific; a
future provider would add its own key.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.orm import Session

from winnow_api.classifier import Classifier
from winnow_api.db.models import User
from winnow_api.gmail.client import GmailClient, HistoryExpired
from winnow_api.gmail.ingest import ingest_message

log = structlog.get_logger(__name__)


@dataclass
class SyncReport:
    ingested: int
    skipped_duplicate: int
    ended_history_id: str | None
    strategy: str  # "full" | "incremental" | "incremental-fallback-full"


class GmailSync:
    def __init__(self, client: GmailClient, db: Session, user: User, classifier: Classifier | None):
        self._client = client
        self._db = db
        self._user = user
        self._classifier = classifier

    def sync_full(self, days: int = 30) -> SyncReport:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        log.info("gmail_sync_full_started", user_id=str(self._user.id), days=days)
        ingested = 0
        skipped = 0
        for message_id in self._client.list_messages_since(since):
            msg = self._client.get_message(message_id)
            result = ingest_message(self._db, self._user.id, msg, self._classifier)
            if result is None:
                skipped += 1
            else:
                ingested += 1
        profile = self._client.get_profile()
        current_history_id = profile.get("historyId")
        self._save_state(history_id=current_history_id)
        self._db.commit()
        log.info(
            "gmail_sync_full_done",
            user_id=str(self._user.id),
            ingested=ingested,
            skipped=skipped,
            history_id=current_history_id,
        )
        return SyncReport(
            ingested=ingested,
            skipped_duplicate=skipped,
            ended_history_id=current_history_id,
            strategy="full",
        )

    def sync_incremental(self) -> SyncReport:
        state = self._user.gmail_state or {}
        start_id = state.get("history_id")
        if not start_id:
            log.info("gmail_no_history_id_falling_back_to_full", user_id=str(self._user.id))
            report = self.sync_full(days=30)
            report.strategy = "incremental-fallback-full"
            return report

        log.info(
            "gmail_sync_incremental_started",
            user_id=str(self._user.id),
            start_history_id=start_id,
        )
        try:
            new_message_ids = self._collect_new_message_ids(start_id)
        except HistoryExpired:
            log.warning(
                "gmail_history_expired_falling_back_to_full",
                user_id=str(self._user.id),
            )
            # 7 days matches Gmail's history retention — anything older
            # we couldn't have picked up incrementally anyway.
            report = self.sync_full(days=7)
            report.strategy = "incremental-fallback-full"
            return report

        ingested = 0
        skipped = 0
        for message_id in new_message_ids:
            msg = self._client.get_message(message_id)
            result = ingest_message(self._db, self._user.id, msg, self._classifier)
            if result is None:
                skipped += 1
            else:
                ingested += 1

        current_history_id = self._client.get_profile().get("historyId")
        self._save_state(history_id=current_history_id)
        self._db.commit()
        log.info(
            "gmail_sync_incremental_done",
            user_id=str(self._user.id),
            ingested=ingested,
            skipped=skipped,
            history_id=current_history_id,
        )
        return SyncReport(
            ingested=ingested,
            skipped_duplicate=skipped,
            ended_history_id=current_history_id,
            strategy="incremental",
        )

    def _collect_new_message_ids(self, start_id: str) -> list[str]:
        seen: list[str] = []
        for record in self._client.list_history(start_id):
            for added in record.get("messagesAdded", []) or []:
                mid = added.get("message", {}).get("id")
                if mid and mid not in seen:
                    seen.append(mid)
        return seen

    def _save_state(self, *, history_id: str | None) -> None:
        state = dict(self._user.gmail_state or {})
        if history_id:
            state["history_id"] = history_id
        state["last_sync_at"] = datetime.now(timezone.utc).isoformat()
        self._user.gmail_state = state
