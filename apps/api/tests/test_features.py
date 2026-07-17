"""Feature extractor unit tests.

The feature vector is a public contract with the trained model — if any
of these tests break, every existing classifier artifact is stale.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from types import SimpleNamespace

from winnow_api.classifier.features import (
    ENGINEERED_FEATURE_NAMES,
    extract_features,
    to_vector,
)


def _email(**overrides) -> SimpleNamespace:
    """Minimal email-shaped object with sensible defaults."""
    defaults = dict(
        sender_domain="example.com",
        subject="hi",
        body_text="hello",
        recipients={"to": ["me@x"], "cc": []},
        received_at=datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc),
        thread_depth=1,
        has_unsubscribe=False,
        is_reply=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_all_names_present_and_no_extras():
    """Feature dict keys must equal ENGINEERED_FEATURE_NAMES exactly.

    A drift here means the model coefficient vector no longer lines up
    with the featurizer output — silent wrong predictions follow.
    """
    features = extract_features(_email())
    assert set(features.keys()) == set(ENGINEERED_FEATURE_NAMES)


def test_to_vector_preserves_order():
    features = extract_features(_email())
    vector = to_vector(features)
    for name, value in zip(ENGINEERED_FEATURE_NAMES, vector):
        assert value == features[name]


def test_deterministic():
    a = extract_features(_email())
    b = extract_features(_email())
    assert a == b


def test_naive_datetime_is_treated_as_utc():
    """Real Gmail sometimes returns naive datetimes. Featurizer must not crash."""
    naive = datetime(2026, 7, 16, 14, 0)  # no tzinfo
    features = extract_features(_email(received_at=naive))
    # Hour 14 UTC → sin(2π*14/24) ≈ -0.87
    assert math.isclose(features["hour_sin"], math.sin(2 * math.pi * 14 / 24), rel_tol=1e-6)


def test_missing_received_at_defaults_to_now():
    features = extract_features(_email(received_at=None))
    # Just check we got numeric values, not NaN.
    assert -1.001 <= features["hour_sin"] <= 1.001
    assert -1.001 <= features["dow_cos"] <= 1.001


def test_notification_domain_flagged():
    features = extract_features(_email(sender_domain="github.com"))
    assert features["sender_is_notification_domain"] == 1.0
    assert features["sender_is_receipt_domain"] == 0.0


def test_receipt_domain_flagged():
    features = extract_features(_email(sender_domain="stripe.com"))
    assert features["sender_is_receipt_domain"] == 1.0
    assert features["sender_is_notification_domain"] == 0.0


def test_suspicious_tld_flagged():
    features = extract_features(_email(sender_domain="airdrop.xyz"))
    assert features["sender_is_suspicious_tld"] == 1.0


def test_urgency_words_counted_case_insensitive():
    features = extract_features(
        _email(subject="URGENT: reply ASAP", body_text="please respond today")
    )
    # urgent, asap, please, today -> 4
    assert features["urgency_word_count"] >= 4


def test_question_marks_counted_separately_in_subject_and_body():
    features = extract_features(
        _email(subject="what??", body_text="really? really? really?")
    )
    assert features["subject_question_marks"] == 2.0
    assert features["body_question_marks"] == 3.0


def test_empty_body_does_not_crash():
    features = extract_features(_email(body_text=""))
    assert features["log_body_length"] == 0.0


def test_thread_depth_capped_at_10():
    features = extract_features(_email(thread_depth=42))
    assert features["thread_depth_capped"] == 10.0


def test_accepts_dict_input():
    """``EmailFeatureInput.from_any`` supports dicts, ORM objects, and Pydantic."""
    features = extract_features(
        dict(
            sender_domain="stripe.com",
            subject="receipt",
            body_text="$10",
            recipients={"to": ["me@x"]},
            received_at=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
            thread_depth=1,
            has_unsubscribe=True,
            is_reply=False,
        )
    )
    assert features["sender_is_receipt_domain"] == 1.0
    assert features["has_unsubscribe"] == 1.0
