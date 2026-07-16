"""Locks the (user_id XOR session_id) invariant on every dual-scoped table.

If this test ever fails, the CHECK constraint has been weakened somewhere
and real data can bleed into demo data (or vice versa). This is the single
most load-bearing invariant in the schema — every product query assumes it.

Covers both failure modes:
- both scopes set (the common bug)
- neither scope set (the sneakier bug — a row belonging to nobody)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from winnow_api.db.models import (
    Action,
    DemoSession,
    Email,
    TrainingExample,
    TriageDecision,
    User,
)


@pytest.fixture
def real_user(db: Session) -> User:
    u = User(email=f"me-{uuid.uuid4()}@example.com")
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def demo_sess(db: Session) -> DemoSession:
    s = DemoSession(
        ip_hash="hmac-sha256-of-something",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(s)
    db.commit()
    return s


@pytest.fixture
def seed_email(db: Session, real_user: User) -> Email:
    """A committed email owned by the real user, used as a parent FK target."""
    e = Email(
        user_id=real_user.id,
        sender_email="alice@example.com",
        sender_domain="example.com",
        recipients={"to": ["me@example.com"], "cc": [], "bcc": []},
        subject="hi",
        body_text="hello",
        received_at=datetime.now(timezone.utc),
    )
    db.add(e)
    db.commit()
    return e


def _email_kwargs() -> dict:
    return dict(
        sender_email="a@b.com",
        sender_domain="b.com",
        recipients={"to": ["me@example.com"], "cc": [], "bcc": []},
        subject="x",
        body_text="y",
        received_at=datetime.now(timezone.utc),
    )


# --- Email ------------------------------------------------------------------


def test_email_rejects_both_scopes(db, real_user, demo_sess):
    db.add(
        Email(
            user_id=real_user.id,
            session_id=demo_sess.id,
            seed_email_id="seed_001",
            **_email_kwargs(),
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_email_rejects_neither_scope(db):
    db.add(Email(user_id=None, session_id=None, **_email_kwargs()))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_email_demo_row_requires_seed_id(db, demo_sess):
    """Session-scoped emails must reference a seed email so tier-2 lookup works."""
    db.add(
        Email(
            session_id=demo_sess.id,
            seed_email_id=None,
            **_email_kwargs(),
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# --- TriageDecision ---------------------------------------------------------


def _triage_kwargs(email_id: uuid.UUID) -> dict:
    return dict(
        email_id=email_id,
        lane="needs_you",
        confidence=0.9,
        tier=1,
        latency_ms=5,
    )


def test_triage_rejects_both_scopes(db, real_user, demo_sess, seed_email):
    db.add(
        TriageDecision(
            user_id=real_user.id,
            session_id=demo_sess.id,
            **_triage_kwargs(seed_email.id),
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_triage_rejects_neither_scope(db, seed_email):
    db.add(TriageDecision(user_id=None, session_id=None, **_triage_kwargs(seed_email.id)))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# --- Action -----------------------------------------------------------------


def test_action_rejects_both_scopes(db, real_user, demo_sess, seed_email):
    db.add(
        Action(
            user_id=real_user.id,
            session_id=demo_sess.id,
            email_id=seed_email.id,
            action_type="archived",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_action_rejects_neither_scope(db, seed_email):
    db.add(
        Action(
            user_id=None,
            session_id=None,
            email_id=seed_email.id,
            action_type="archived",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# --- TrainingExample --------------------------------------------------------


def test_training_rejects_both_scopes(db, real_user, demo_sess, seed_email):
    db.add(
        TrainingExample(
            user_id=real_user.id,
            session_id=demo_sess.id,
            email_id=seed_email.id,
            label="needs_you",
            label_source="user_move",
            features={},
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_training_rejects_neither_scope(db, seed_email):
    db.add(
        TrainingExample(
            user_id=None,
            session_id=None,
            email_id=seed_email.id,
            label="needs_you",
            label_source="user_move",
            features={},
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# --- Happy paths (proving the constraint isn't over-restrictive) ------------


def test_email_accepts_user_only(db, real_user):
    db.add(Email(user_id=real_user.id, **_email_kwargs()))
    db.commit()  # must not raise


def test_email_accepts_session_only(db, demo_sess):
    db.add(
        Email(session_id=demo_sess.id, seed_email_id="seed_001", **_email_kwargs())
    )
    db.commit()  # must not raise
