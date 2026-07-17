"""Classifier inference smoke tests.

Loads the shipped baseline artifact and checks output shape + basic
behavioural sanity. Skipped if the artifact isn't present (fresh clone
before running ``uv run python -m winnow_api.classifier.train``).

These are not accuracy tests — that's the eval harness's job (Step 10).
They just prove the runtime plumbing is intact: model loads without a
sklearn version mismatch, predictions produce well-formed
``ClassifierResult`` objects, and the top-feature attribution has the
expected shape.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from winnow_api.classifier import Classifier

ARTIFACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "winnow_api"
    / "classifier"
    / "artifacts"
    / "base.joblib"
)


pytestmark = pytest.mark.skipif(
    not ARTIFACT_PATH.exists(),
    reason="Baseline classifier artifact not present; run `uv run python -m winnow_api.classifier.train` first.",
)


@pytest.fixture(scope="module")
def clf() -> Classifier:
    return Classifier.load(ARTIFACT_PATH)


def _email(**overrides) -> SimpleNamespace:
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


def test_result_shape(clf: Classifier):
    r = clf.predict_one(_email(subject="Q3 doc — comments by Thursday?"))
    assert r.lane in {"needs_you", "informational", "hidden"}
    assert 0.0 <= r.confidence <= 1.0
    assert set(r.class_probabilities.keys()) == {"needs_you", "informational", "hidden"}
    assert abs(sum(r.class_probabilities.values()) - 1.0) < 1e-5
    assert r.classifier_version.startswith("base-")


def test_top_features_shape(clf: Classifier):
    r = clf.predict_one(_email(subject="dinner Saturday?"))
    assert len(r.top_features) == 5
    for tf in r.top_features:
        assert isinstance(tf.name, str)
        assert isinstance(tf.weight, float)
    # email_content_signal is always present (the embedding bucket).
    assert any(tf.name == "email_content_signal" for tf in r.top_features)


def test_top_features_sorted_by_abs_weight(clf: Classifier):
    r = clf.predict_one(_email(subject="dinner Saturday?"))
    abs_weights = [abs(tf.weight) for tf in r.top_features]
    assert abs_weights == sorted(abs_weights, reverse=True)


def test_receipt_lands_hidden(clf: Classifier):
    """A clear receipt from a receipt-domain should land in hidden.

    Weak behavioural check — if this ever fails the model has degraded
    badly enough to warrant a look, even absent a full eval harness.
    """
    r = clf.predict_one(
        _email(
            sender_domain="stripe.com",
            subject="Your receipt from Acme Co",
            body_text="Amount charged: $99.00\nCard ending 4242.",
            has_unsubscribe=True,
        )
    )
    assert r.lane == "hidden"


def test_batch_matches_single(clf: Classifier):
    e1 = _email(subject="dinner Saturday?", sender_domain="hey.com")
    e2 = _email(subject="[Stripe] Receipt", sender_domain="stripe.com")
    batch = clf.predict_many([e1, e2])
    solo_1 = clf.predict_one(e1)
    solo_2 = clf.predict_one(e2)
    assert batch[0].lane == solo_1.lane
    assert batch[1].lane == solo_2.lane
