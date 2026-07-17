"""Engineered features for the tier-1 triage classifier.

Kept deliberately small (~20 features): each has a clean human-readable
name so the explainability panel can say "this landed in Hidden because
`sender_is_receipt` and `has_unsubscribe`" instead of "embedding dim 137
lit up." The subject/body embedding vector picks up everything these
lexical features miss.

Feature vector layout is a public contract — the classifier is trained
against ``ENGINEERED_FEATURE_NAMES`` in order, and inference relies on
the same order at score time. Adding features means bumping model
version.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# Domain buckets. Chosen for interpretability, not coverage — anything
# unknown falls into "other" and the classifier leans on embeddings.
_NOTIFICATION_DOMAINS = {
    "github.com", "gitlab.com", "slack.com", "linear.app", "notion.so",
    "google.com", "atlassian.com", "figma.com", "sentry.io", "vercel.com",
}
_RECEIPT_DOMAINS = {
    "stripe.com", "uber.com", "lyft.com", "amazon.com", "airbnb.com",
    "doordash.com", "instacart.com", "paypal.com", "square.com",
}
_PERSONAL_TLDS = {"gmail.com", "protonmail.com", "hey.com", "icloud.com", "outlook.com"}
_SUSPICIOUS_TLDS = {".xyz", ".top", ".biz", ".click", ".gq", ".tk"}

_URGENCY_WORDS = {
    "urgent", "asap", "immediately", "today", "tomorrow", "deadline",
    "eod", "cob", "please", "action required", "final", "reminder",
}

# Order-stable list. Do not reorder — model coefficients depend on this.
ENGINEERED_FEATURE_NAMES: list[str] = [
    "has_unsubscribe",
    "is_reply",
    "thread_depth_capped",
    "log_subject_length",
    "log_body_length",
    "subject_question_marks",
    "body_question_marks",
    "urgency_word_count",
    "sender_is_notification_domain",
    "sender_is_receipt_domain",
    "sender_is_personal_domain",
    "sender_is_suspicious_tld",
    "recipient_count",
    "cc_count",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
]


@dataclass
class EmailFeatureInput:
    """The subset of email fields the featurizer reads.

    Kept as a plain dataclass so this module has no SQLAlchemy or
    Pydantic dependency — the featurizer works equally well against a
    DB row, a synthetic seed, or a live Gmail payload.
    """

    sender_domain: str
    subject: str
    body_text: str
    recipients: dict[str, list[str]]
    received_at: datetime
    thread_depth: int
    has_unsubscribe: bool
    is_reply: bool

    @classmethod
    def from_any(cls, obj: Any) -> "EmailFeatureInput":
        """Adapter for anything that has the expected fields (ORM, Pydantic, dict)."""
        get = obj.get if isinstance(obj, dict) else lambda k, default=None: getattr(obj, k, default)  # noqa: E731
        return cls(
            sender_domain=get("sender_domain"),
            subject=get("subject") or "",
            body_text=get("body_text") or "",
            recipients=get("recipients") or {},
            received_at=get("received_at"),
            thread_depth=get("thread_depth") or 1,
            has_unsubscribe=bool(get("has_unsubscribe")),
            is_reply=bool(get("is_reply")),
        )


def extract_features(email: Any) -> dict[str, float]:
    """Return a name→value dict, order-agnostic. Used for storage in JSONB.

    ``to_vector`` converts this dict into the model's expected numeric
    vector in ``ENGINEERED_FEATURE_NAMES`` order.
    """
    e = EmailFeatureInput.from_any(email)

    received = e.received_at
    if received is None:
        received = datetime.now(timezone.utc)
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)
    hour = received.hour
    dow = received.weekday()

    subject = e.subject
    body = e.body_text
    text = f"{subject}\n{body}".lower()

    to_list = e.recipients.get("to", []) or []
    cc_list = e.recipients.get("cc", []) or []

    domain = (e.sender_domain or "").lower()
    is_suspicious = any(domain.endswith(t) for t in _SUSPICIOUS_TLDS)

    return {
        "has_unsubscribe": float(e.has_unsubscribe),
        "is_reply": float(e.is_reply),
        "thread_depth_capped": float(min(e.thread_depth, 10)),
        "log_subject_length": math.log1p(len(subject)),
        "log_body_length": math.log1p(len(body)),
        "subject_question_marks": float(subject.count("?")),
        "body_question_marks": float(body.count("?")),
        "urgency_word_count": float(sum(1 for w in _URGENCY_WORDS if w in text)),
        "sender_is_notification_domain": float(domain in _NOTIFICATION_DOMAINS),
        "sender_is_receipt_domain": float(domain in _RECEIPT_DOMAINS),
        "sender_is_personal_domain": float(domain in _PERSONAL_TLDS),
        "sender_is_suspicious_tld": float(is_suspicious),
        "recipient_count": float(len(to_list) + len(cc_list)),
        "cc_count": float(len(cc_list)),
        "hour_sin": math.sin(2 * math.pi * hour / 24),
        "hour_cos": math.cos(2 * math.pi * hour / 24),
        "dow_sin": math.sin(2 * math.pi * dow / 7),
        "dow_cos": math.cos(2 * math.pi * dow / 7),
    }


def to_vector(features: dict[str, float]) -> list[float]:
    """Project a features dict onto the fixed ``ENGINEERED_FEATURE_NAMES`` order."""
    return [features[name] for name in ENGINEERED_FEATURE_NAMES]
