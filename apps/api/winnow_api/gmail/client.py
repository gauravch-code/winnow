"""Thin Gmail v1 client for Winnow's ingestion path.

Wraps ``google-api-python-client`` so the rest of Winnow's Gmail code
can pretend it's calling ordinary Python methods instead of a JSON RPC
that occasionally 500s. Not an abstraction over Gmail — a translation
of the specific calls Winnow actually makes into a testable seam.

All methods take a live ``Credentials`` from ``oauth.load_credentials_for_user``.
The Google library refreshes the access token on the first request
after credential construction.
"""

from __future__ import annotations

import base64
import email.utils
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

import structlog
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

log = structlog.get_logger(__name__)


@dataclass
class GmailMessage:
    """Normalized shape used by the ingester. Not a Pydantic model on
    purpose — this is a data-transfer object between Gmail's payload
    and our ``Email`` ORM row, not a public API surface."""

    gmail_message_id: str
    gmail_thread_id: str
    sender_email: str
    sender_name: str | None
    sender_domain: str
    recipients: dict[str, list[str]]
    subject: str
    body_text: str
    body_html: str | None
    snippet: str
    received_at: datetime
    thread_depth: int
    has_unsubscribe: bool
    is_reply: bool
    label_ids: list[str]


class HistoryExpired(RuntimeError):
    """Gmail rejected our historyId as too old (~7d). Caller should full-sync."""


class GmailClient:
    def __init__(self, credentials) -> None:  # noqa: ANN001 — google-auth type varies
        # cache_discovery=False avoids a filesystem-cache warning on every
        # build() call; we don't reuse discovery docs across processes.
        self._svc = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    # --- profile / watch bookkeeping ---------------------------------------

    def get_profile(self) -> dict:
        return self._svc.users().getProfile(userId="me").execute()

    def start_watch(self, topic_name: str) -> dict:
        """Register the Pub/Sub push subscription. Returns
        {historyId, expiration} which the caller stashes in gmail_state."""
        return (
            self._svc.users()
            .watch(userId="me", body={"topicName": topic_name, "labelIds": ["INBOX"]})
            .execute()
        )

    def stop_watch(self) -> None:
        self._svc.users().stop(userId="me").execute()

    # --- list + fetch ------------------------------------------------------

    def list_messages_since(self, since: datetime, page_size: int = 100) -> Iterator[str]:
        """Yield message ids received after ``since``.

        Used for the initial backfill. Gmail's ``q=after:<unix>`` query
        is second-precision and treats the boundary inclusively.
        """
        query = f"after:{int(since.timestamp())}"
        token = None
        while True:
            resp = (
                self._svc.users()
                .messages()
                .list(userId="me", q=query, maxResults=page_size, pageToken=token)
                .execute()
            )
            for m in resp.get("messages", []):
                yield m["id"]
            token = resp.get("nextPageToken")
            if not token:
                return

    def list_history(self, start_history_id: str) -> Iterator[dict]:
        """Yield history records since ``start_history_id``.

        Raises ``HistoryExpired`` if Gmail returns 404 (historyId older
        than the ~7-day retention window). Caller must full-sync.
        """
        token = None
        while True:
            try:
                resp = (
                    self._svc.users()
                    .history()
                    .list(
                        userId="me",
                        startHistoryId=start_history_id,
                        historyTypes=["messageAdded"],
                        pageToken=token,
                    )
                    .execute()
                )
            except HttpError as exc:
                if exc.resp.status == 404:
                    raise HistoryExpired(
                        f"historyId {start_history_id} is expired; full sync required."
                    ) from exc
                raise
            for h in resp.get("history", []):
                yield h
            token = resp.get("nextPageToken")
            if not token:
                return

    def get_message(self, message_id: str) -> GmailMessage:
        raw = (
            self._svc.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        return _parse_message(raw)


# --- payload parsing -------------------------------------------------------


def _parse_message(raw: dict) -> GmailMessage:
    """Extract the fields Winnow actually stores from Gmail's message payload.

    Kept as a module-level function (not a client method) so it's unit
    testable against captured raw payloads without a live client.
    """
    headers = {h["name"].lower(): h["value"] for h in raw.get("payload", {}).get("headers", [])}
    sender_raw = headers.get("from", "")
    sender_name, sender_email_addr = email.utils.parseaddr(sender_raw)
    sender_domain = sender_email_addr.split("@")[-1].lower() if "@" in sender_email_addr else ""

    to_list = _split_addrs(headers.get("to", ""))
    cc_list = _split_addrs(headers.get("cc", ""))
    bcc_list = _split_addrs(headers.get("bcc", ""))

    date_hdr = headers.get("date")
    received = email.utils.parsedate_to_datetime(date_hdr) if date_hdr else datetime.now(timezone.utc)
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)

    body_text, body_html = _extract_bodies(raw.get("payload", {}))

    has_unsubscribe = "list-unsubscribe" in headers or "unsubscribe" in body_text.lower()
    is_reply = bool(headers.get("in-reply-to") or headers.get("references"))

    # Rough thread-depth signal: Gmail's References header carries the
    # chain of message ids. Nothing precise, but "1 vs many" is what
    # the featurizer cares about.
    refs = headers.get("references", "")
    thread_depth = max(1, len(refs.split()) if refs else 1)

    return GmailMessage(
        gmail_message_id=raw["id"],
        gmail_thread_id=raw.get("threadId", raw["id"]),
        sender_email=sender_email_addr,
        sender_name=sender_name or None,
        sender_domain=sender_domain,
        recipients={"to": to_list, "cc": cc_list, "bcc": bcc_list},
        subject=headers.get("subject", "(no subject)"),
        body_text=body_text,
        body_html=body_html,
        snippet=raw.get("snippet", "")[:280],
        received_at=received,
        thread_depth=thread_depth,
        has_unsubscribe=has_unsubscribe,
        is_reply=is_reply,
        label_ids=raw.get("labelIds", []),
    )


def _split_addrs(header_value: str) -> list[str]:
    if not header_value:
        return []
    return [addr for _, addr in email.utils.getaddresses([header_value]) if addr]


def _extract_bodies(payload: dict) -> tuple[str, str | None]:
    """Depth-first walk over MIME parts. Returns (text, html_or_None).

    Multipart/alternative typically has text/plain + text/html; we take
    the first of each we find. Winnow's classifier only reads text_body,
    but html_body is stored so the UI can render richer previews later.
    """
    text_body: str | None = None
    html_body: str | None = None

    def visit(part: dict) -> None:
        nonlocal text_body, html_body
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and text_body is None and mime == "text/plain":
            text_body = _b64_utf8(data)
        elif data and html_body is None and mime == "text/html":
            html_body = _b64_utf8(data)
        for child in part.get("parts", []) or []:
            visit(child)

    visit(payload)

    # Fallback: some senders (poorly configured, or newsletters) put the
    # whole body in a non-multipart root. Use it as text if plain is empty.
    if text_body is None:
        data = payload.get("body", {}).get("data")
        if data:
            text_body = _b64_utf8(data)

    return text_body or "", html_body


def _b64_utf8(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode("ascii")).decode("utf-8", errors="replace")
