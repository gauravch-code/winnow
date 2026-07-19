"""Real-mode dashboard endpoint tests.

Builds a minimal FastAPI app that mounts the realapp router against the
test database, so we exercise the actual HTTP surface (list / lane /
archive / star / escalate) without importing main.py's import-time mode
branching. Owner-scoped throughout.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from winnow_api.agents.schemas import Tier2AgentOutput, Tier2DraftReply, Tier2Signal
from winnow_api.classifier.inference import ClassifierResult, TopFeature
from winnow_api.db.models import (
    Action,
    Email,
    TrainingExample,
    TriageDecision,
    User,
)
from winnow_api.realapp import router


@pytest.fixture
def owner(db: Session) -> User:
    db.query(TrainingExample).delete()
    db.query(Action).delete()
    db.query(TriageDecision).delete()
    db.query(Email).delete()
    db.query(User).delete()
    db.commit()
    u = User(email=f"owner-{uuid.uuid4()}@example.com")
    db.add(u)
    db.commit()
    yield u
    db.query(TrainingExample).delete()
    db.query(Action).delete()
    db.query(TriageDecision).delete()
    db.query(Email).delete()
    db.query(User).delete()
    db.commit()


def _add_email(db: Session, owner: User, subject: str, lane: str, gmail_id: str) -> Email:
    email = Email(
        user_id=owner.id,
        gmail_message_id=gmail_id,
        sender_email="a@b.com",
        sender_domain="b.com",
        recipients={"to": ["me@example.com"], "cc": [], "bcc": []},
        subject=subject,
        body_text="body",
        snippet=subject,
        received_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
        thread_depth=1,
        has_unsubscribe=False,
        is_reply=False,
    )
    db.add(email)
    db.flush()
    db.add(
        TriageDecision(
            email_id=email.id,
            user_id=owner.id,
            lane=lane,
            confidence=0.9,
            tier=1,
            classifier_version="base-0.1",
            reasoning="seeded",
            latency_ms=1,
        )
    )
    db.commit()
    return email


class _FakeClassifier:
    def predict_one(self, email: Any) -> ClassifierResult:
        return ClassifierResult(
            lane="informational",
            confidence=0.4,
            class_probabilities={"informational": 0.4, "needs_you": 0.35, "hidden": 0.25},
            top_features=[TopFeature(name="fake", value=1.0, weight=0.2)],
            features={},
            latency_ms=1,
            classifier_version="fake",
        )


class _FakeTier2Provider:
    """Returns a fixed tier-2 output with a draft — stands in for the live LLM."""

    async def run(self, email: Any, tier_1: ClassifierResult):
        out = Tier2AgentOutput(
            lane="needs_you",
            confidence=0.83,
            reasoning="Direct ask with a near-term deadline.",
            signals=[Tier2Signal(name="direct_question", weight=0.4)],
            draft_reply=Tier2DraftReply(
                included=True,
                subject="Re: hi",
                body_markdown="Sure — I'll take a look today.",
                tone="collegial",
                assumptions=["user can reply without more context"],
            ),
        )
        return out, "live", None


@pytest.fixture
def client(engine, db_url, monkeypatch, owner):
    """A TestClient over an app that mounts the realapp router with a
    classifier + tier-2 provider on app.state."""
    from winnow_api.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "mode", "real", raising=False)

    app = FastAPI()
    app.include_router(router)
    app.state.engine = engine
    app.state.settings = settings
    app.state.classifier = _FakeClassifier()
    app.state.tier_2_provider = _FakeTier2Provider()
    with TestClient(app) as c:
        yield c


# --- list -----------------------------------------------------------------


def test_list_emails_returns_owner_mail(client, db, owner):
    _add_email(db, owner, "one", "needs_you", "M1")
    _add_email(db, owner, "two", "hidden", "M2")

    r = client.get("/emails")
    assert r.status_code == 200
    data = r.json()
    assert {e["subject"] for e in data} == {"one", "two"}
    assert all("gmail_message_id" in e for e in data)


def test_list_lane_filter(client, db, owner):
    _add_email(db, owner, "a", "needs_you", "M1")
    _add_email(db, owner, "b", "hidden", "M2")

    r = client.get("/emails", params={"lane": "hidden"})
    assert [e["subject"] for e in r.json()] == ["b"]


# --- lane move ------------------------------------------------------------


def test_move_lane_writes_action_decision_and_training(client, db, owner):
    email = _add_email(db, owner, "hi", "informational", "M1")

    r = client.patch(f"/emails/{email.id}/lane", json={"to_lane": "needs_you"})
    assert r.status_code == 200
    assert r.json()["lane"] == "needs_you"

    # Superseding decision is now the current one.
    current = (
        db.query(TriageDecision)
        .filter(
            TriageDecision.email_id == email.id,
            TriageDecision.superseded_at.is_(None),
        )
        .one()
    )
    assert current.lane == "needs_you"
    assert current.classifier_version == "user-override"

    # Action + training example recorded.
    action = db.query(Action).filter(Action.email_id == email.id).one()
    assert action.action_type == "lane_moved"
    te = db.query(TrainingExample).filter(TrainingExample.email_id == email.id).one()
    assert te.label == "needs_you"
    assert te.label_source == "user_move"
    assert te.user_id == owner.id


def test_move_to_same_lane_is_noop(client, db, owner):
    email = _add_email(db, owner, "hi", "hidden", "M1")
    r = client.patch(f"/emails/{email.id}/lane", json={"to_lane": "hidden"})
    assert r.status_code == 200
    # No new action / training rows for a no-op.
    assert db.query(Action).filter(Action.email_id == email.id).count() == 0
    assert db.query(TrainingExample).filter(TrainingExample.email_id == email.id).count() == 0


# --- archive / star -------------------------------------------------------


def test_archive_moves_to_hidden_with_training(client, db, owner):
    email = _add_email(db, owner, "receipt", "informational", "M1")
    r = client.post(f"/emails/{email.id}/archive")
    assert r.status_code == 200
    assert r.json()["lane"] == "hidden"
    te = db.query(TrainingExample).filter(TrainingExample.email_id == email.id).one()
    assert te.label == "hidden"
    assert te.label_source == "user_archive"


def test_star_moves_to_needs_you_with_training(client, db, owner):
    email = _add_email(db, owner, "important", "informational", "M1")
    r = client.post(f"/emails/{email.id}/star")
    assert r.status_code == 200
    assert r.json()["lane"] == "needs_you"
    te = db.query(TrainingExample).filter(TrainingExample.email_id == email.id).one()
    assert te.label == "needs_you"
    assert te.label_source == "user_star"


# --- escalate -------------------------------------------------------------


def test_escalate_persists_tier2_and_draft(client, db, owner):
    email = _add_email(db, owner, "Q3 doc?", "informational", "M1")
    r = client.post(f"/emails/{email.id}/escalate")
    assert r.status_code == 200
    body = r.json()
    assert body["tier_2_source"] == "live"
    assert body["lane"] == "needs_you"
    assert body["draft_included"] is True
    assert body["draft_subject"] == "Re: hi"

    decision = (
        db.query(TriageDecision)
        .filter(TriageDecision.email_id == email.id, TriageDecision.superseded_at.is_(None))
        .one()
    )
    assert decision.tier == 2
    assert decision.tier_2_source == "live"
    assert decision.agent_trace["draft_included"] is True


def test_escalate_503_without_provider(client, db, owner):
    # Drop the provider to simulate a deployment with no LLM key.
    client.app.state.tier_2_provider = None
    email = _add_email(db, owner, "hi", "informational", "M1")
    r = client.post(f"/emails/{email.id}/escalate")
    assert r.status_code == 503


def test_unknown_email_404(client, db, owner):
    r = client.patch(f"/emails/{uuid.uuid4()}/lane", json={"to_lane": "hidden"})
    assert r.status_code == 404
