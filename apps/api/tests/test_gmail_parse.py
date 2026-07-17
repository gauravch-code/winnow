"""Gmail message parser tests.

Pure unit — no network, no Google client. Uses captured raw payload
shapes to lock the mapping from Gmail's JSON to our ``GmailMessage``.

These tests require WINNOW_MODE=real because ``winnow_api.gmail`` is
gated. Skip cleanly otherwise so ``pytest`` on a demo-mode sandbox
still passes.
"""

from __future__ import annotations

import base64
import os

import pytest

if os.environ.get("WINNOW_MODE", "demo") != "real":
    pytest.skip(
        "winnow_api.gmail is real-mode only; set WINNOW_MODE=real to run these tests.",
        allow_module_level=True,
    )

from winnow_api.gmail.client import _parse_message  # noqa: E402


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii")


def _raw(
    *,
    headers: list[tuple[str, str]],
    snippet: str = "",
    body_text: str | None = None,
    body_html: str | None = None,
    label_ids: list[str] | None = None,
    message_id: str = "MSG-1",
    thread_id: str = "THR-1",
) -> dict:
    parts = []
    if body_text is not None:
        parts.append({"mimeType": "text/plain", "body": {"data": _b64(body_text)}})
    if body_html is not None:
        parts.append({"mimeType": "text/html", "body": {"data": _b64(body_html)}})
    payload: dict = {
        "headers": [{"name": n, "value": v} for n, v in headers],
    }
    if parts:
        payload["parts"] = parts
    return {
        "id": message_id,
        "threadId": thread_id,
        "snippet": snippet,
        "labelIds": label_ids or ["INBOX"],
        "payload": payload,
    }


def test_basic_parse():
    raw = _raw(
        headers=[
            ("From", "Alice Wonderland <alice@example.com>"),
            ("To", "me@example.com"),
            ("Subject", "Q3 doc"),
            ("Date", "Thu, 16 Jul 2026 09:00:00 +0000"),
        ],
        snippet="hi",
        body_text="See attached.",
    )
    msg = _parse_message(raw)
    assert msg.sender_email == "alice@example.com"
    assert msg.sender_name == "Alice Wonderland"
    assert msg.sender_domain == "example.com"
    assert msg.subject == "Q3 doc"
    assert msg.recipients == {"to": ["me@example.com"], "cc": [], "bcc": []}
    assert msg.body_text == "See attached."
    assert msg.thread_depth == 1
    assert msg.is_reply is False
    assert msg.has_unsubscribe is False


def test_reply_and_thread_depth():
    raw = _raw(
        headers=[
            ("From", "bob@example.com"),
            ("Subject", "Re: Q3 doc"),
            ("Date", "Thu, 16 Jul 2026 09:00:00 +0000"),
            ("In-Reply-To", "<abc@example.com>"),
            ("References", "<abc@example.com> <def@example.com> <ghi@example.com>"),
        ],
        body_text="",
    )
    msg = _parse_message(raw)
    assert msg.is_reply is True
    assert msg.thread_depth == 3


def test_unsubscribe_detected_from_header():
    raw = _raw(
        headers=[
            ("From", "newsletter@substack.com"),
            ("List-Unsubscribe", "<mailto:unsub@substack.com>"),
            ("Subject", "This week's issue"),
            ("Date", "Thu, 16 Jul 2026 09:00:00 +0000"),
        ],
        body_text="content",
    )
    msg = _parse_message(raw)
    assert msg.has_unsubscribe is True


def test_missing_subject_gets_placeholder():
    raw = _raw(
        headers=[
            ("From", "x@y.com"),
            ("Date", "Thu, 16 Jul 2026 09:00:00 +0000"),
        ],
        body_text="body",
    )
    msg = _parse_message(raw)
    assert msg.subject == "(no subject)"


def test_multiple_recipients_split():
    raw = _raw(
        headers=[
            ("From", "sender@x.com"),
            ("To", "me@x.com, you@y.com"),
            ("Cc", "cc1@x.com, cc2@y.com"),
            ("Subject", "s"),
            ("Date", "Thu, 16 Jul 2026 09:00:00 +0000"),
        ],
        body_text="b",
    )
    msg = _parse_message(raw)
    assert msg.recipients["to"] == ["me@x.com", "you@y.com"]
    assert msg.recipients["cc"] == ["cc1@x.com", "cc2@y.com"]


def test_html_only_body_falls_back_to_html_captured():
    raw = _raw(
        headers=[
            ("From", "a@b.com"),
            ("Subject", "s"),
            ("Date", "Thu, 16 Jul 2026 09:00:00 +0000"),
        ],
        body_html="<p>hi</p>",
    )
    msg = _parse_message(raw)
    assert msg.body_html == "<p>hi</p>"
    # No text/plain part, no root body — text is empty (classifier can
    # still work off subject + engineered features).
    assert msg.body_text == ""


def test_snippet_truncated_at_280():
    long_snippet = "x" * 500
    raw = _raw(
        headers=[("From", "a@b.com"), ("Subject", "s"), ("Date", "Thu, 16 Jul 2026 09:00:00 +0000")],
        snippet=long_snippet,
        body_text="",
    )
    msg = _parse_message(raw)
    assert len(msg.snippet) == 280
