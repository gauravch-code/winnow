"""SQLAlchemy models for Winnow.

Design invariants enforced at the DB level:

- **Dual-scope XOR**: every row in ``emails``, ``triage_decisions``,
  ``actions``, and ``training_examples`` has exactly one of
  (``user_id``, ``session_id``) set. Enforced by CHECK constraints and
  locked in by ``tests/test_dual_scoping_invariant.py``.

- **Demo emails require a seed reference**: session-scoped emails must
  carry ``seed_email_id`` so the tier-2 fixture loader can find their
  pre-recorded response.

Everything user-scoped is deleted by CASCADE when a user is dropped;
everything session-scoped is deleted by CASCADE when the nightly GC job
removes an expired ``demo_sessions`` row.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from winnow_api.db.base import Base, new_uuid


class User(Base):
    """Real Winnow user. In production there is exactly one row (me).

    ``llm_api_key`` is intentionally NOT stored here — the process reads it
    from the ``WINNOW_LLM_API_KEY`` env var at startup. One real user,
    no reason to build a key-management surface.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=new_uuid,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)

    # Encrypted with cryptography.fernet using WINNOW_ENCRYPTION_KEY.
    # Stored as the Fernet token string (URL-safe base64 bytes decoded to str).
    gmail_refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    llm_provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="anthropic")

    # Default from eval sweep; see docs/evals.md#threshold-selection.
    # Do not change without re-running the sweep.
    confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.75")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DemoSession(Base):
    """Ephemeral per-visitor state for the public demo.

    ``id`` doubles as the session cookie value handed to the browser.
    ``ip_hash`` is HMAC-SHA256(WINNOW_IP_HASH_SALT, ip) — a plain SHA256 of
    an IPv4 address is reversible via a ~4B-entry rainbow table in seconds.
    """

    __tablename__ = "demo_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=new_uuid,
        server_default=text("gen_random_uuid()"),
    )
    ip_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_demo_sessions_expires_at", "expires_at"),)


# --- Dual-scoped tables ------------------------------------------------------
#
# The (user_id XOR session_id) invariant is enforced by a CHECK constraint on
# every table below. Any weakening of that constraint is caught by
# tests/test_dual_scoping_invariant.py.


class Email(Base):
    __tablename__ = "emails"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=new_uuid,
        server_default=text("gen_random_uuid()"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("demo_sessions.id", ondelete="CASCADE"), nullable=True
    )

    # Fixture key for demo-scoped rows; identifies which pre-recorded LLM
    # response applies. Null for real-user rows.
    seed_email_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    gmail_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    gmail_thread_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    sender_email: Mapped[str] = mapped_column(Text, nullable=False)
    sender_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender_domain: Mapped[str] = mapped_column(Text, nullable=False)

    recipients: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {to, cc, bcc}

    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)

    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    thread_depth: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    has_unsubscribe: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_reply: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "(user_id IS NULL) <> (session_id IS NULL)",
            name="ck_emails_dual_scope_xor",
        ),
        CheckConstraint(
            "(session_id IS NULL) OR (seed_email_id IS NOT NULL)",
            name="ck_emails_demo_rows_have_seed_id",
        ),
        Index(
            "uq_emails_user_gmail_msg",
            "user_id",
            "gmail_message_id",
            unique=True,
            postgresql_where="user_id IS NOT NULL",
        ),
        Index(
            "ix_emails_session_received",
            "session_id",
            "received_at",
            postgresql_where="session_id IS NOT NULL",
        ),
        Index(
            "ix_emails_user_received",
            "user_id",
            "received_at",
            postgresql_where="user_id IS NOT NULL",
        ),
    )


class TriageDecision(Base):
    __tablename__ = "triage_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=new_uuid,
        server_default=text("gen_random_uuid()"),
    )

    email_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("emails.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("demo_sessions.id", ondelete="CASCADE"), nullable=True
    )

    lane: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    tier: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # NULL when tier=1; one of live|prerecorded|unavailable when tier=2.
    tier_2_source: Mapped[str | None] = mapped_column(Text, nullable=True)

    classifier_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    top_features: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    agent_trace: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(user_id IS NULL) <> (session_id IS NULL)",
            name="ck_triage_dual_scope_xor",
        ),
        CheckConstraint(
            "lane IN ('needs_you','informational','hidden')",
            name="ck_triage_lane_enum",
        ),
        CheckConstraint("tier IN (1, 2)", name="ck_triage_tier_range"),
        CheckConstraint(
            "tier_2_source IS NULL OR tier_2_source IN ('live','prerecorded','unavailable')",
            name="ck_triage_source_enum",
        ),
        Index("ix_triage_email_decided", "email_id", "decided_at"),
        Index(
            "ix_triage_session",
            "session_id",
            postgresql_where="session_id IS NOT NULL",
        ),
    )


class Action(Base):
    __tablename__ = "actions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=new_uuid,
        server_default=text("gen_random_uuid()"),
    )

    email_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("emails.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("demo_sessions.id", ondelete="CASCADE"), nullable=True
    )

    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    from_lane: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_lane: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "(user_id IS NULL) <> (session_id IS NULL)",
            name="ck_actions_dual_scope_xor",
        ),
        CheckConstraint(
            "action_type IN ('lane_moved','archived','starred','draft_edited',"
            "'draft_discarded','marked_read','snoozed')",
            name="ck_actions_type_enum",
        ),
        Index(
            "ix_actions_user_occurred",
            "user_id",
            "occurred_at",
            postgresql_where="user_id IS NOT NULL",
        ),
        Index(
            "ix_actions_session_occurred",
            "session_id",
            "occurred_at",
            postgresql_where="session_id IS NOT NULL",
        ),
    )


class TrainingExample(Base):
    """Materialized training row for the classifier.

    ``embedding`` holds raw bytes from ``numpy.ndarray.tobytes()`` — no pickle.
    ``embedding_dim`` and ``embedding_dtype`` are the round-trip metadata
    needed to reconstruct the ndarray without trusting the reader to
    hard-code MiniLM's 384-dim float32 shape.
    """

    __tablename__ = "training_examples"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=new_uuid,
        server_default=text("gen_random_uuid()"),
    )

    email_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("emails.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("demo_sessions.id", ondelete="CASCADE"), nullable=True
    )

    label: Mapped[str] = mapped_column(Text, nullable=False)
    label_source: Mapped[str] = mapped_column(Text, nullable=False)

    features: Mapped[dict] = mapped_column(JSONB, nullable=False)

    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    embedding_dim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_dtype: Mapped[str | None] = mapped_column(
        Text, nullable=True, server_default="float32"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "(user_id IS NULL) <> (session_id IS NULL)",
            name="ck_training_dual_scope_xor",
        ),
        CheckConstraint(
            "label IN ('needs_you','informational','hidden')",
            name="ck_training_label_enum",
        ),
        CheckConstraint(
            "label_source IN ('user_move','user_archive','initial_seed')",
            name="ck_training_source_enum",
        ),
        # If embedding is present, its metadata must be too. Enforces
        # round-trippability at the DB level rather than trusting callers.
        CheckConstraint(
            "(embedding IS NULL) OR (embedding_dim IS NOT NULL AND embedding_dtype IS NOT NULL)",
            name="ck_training_embedding_metadata",
        ),
        Index(
            "ix_training_user",
            "user_id",
            postgresql_where="user_id IS NOT NULL",
        ),
        Index(
            "ix_training_session",
            "session_id",
            postgresql_where="session_id IS NOT NULL",
        ),
    )


class ClassifierModel(Base):
    """Persisted classifier artifact. Real users only.

    Demo sessions train an in-process, LRU-bounded model instead — the model
    is small (a session's worth of examples) and the visitor is gone in 24h.

    ``sklearn_version`` is checked at load time. Deserializing a joblib blob
    trained against a different sklearn version is undefined behavior; if
    versions don't match the loader raises rather than silently returning
    a subtly wrong pipeline.
    """

    __tablename__ = "classifier_models"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=new_uuid,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(Text, nullable=False)
    model_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sklearn_version: Mapped[str] = mapped_column(Text, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    __table_args__ = (
        UniqueConstraint("user_id", "version", name="uq_classifier_user_version"),
        Index(
            "ix_classifier_user_active",
            "user_id",
            "is_active",
            postgresql_where="is_active",
        ),
    )
