"""initial schema: users, demo_sessions, emails, triage_decisions, actions, training_examples, classifier_models

Revision ID: 0001
Revises:
Create Date: 2026-07-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- users ---------------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("gmail_refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("llm_provider", sa.Text(), nullable=False, server_default="anthropic"),
        sa.Column(
            "confidence_threshold",
            sa.Float(),
            nullable=False,
            server_default="0.75",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ---- demo_sessions -------------------------------------------------
    op.create_table(
        "demo_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("ip_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_demo_sessions_expires_at", "demo_sessions", ["expires_at"])

    # ---- emails --------------------------------------------------------
    op.create_table(
        "emails",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("demo_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("seed_email_id", sa.Text(), nullable=True),
        sa.Column("gmail_message_id", sa.Text(), nullable=True),
        sa.Column("gmail_thread_id", sa.Text(), nullable=True),
        sa.Column("sender_email", sa.Text(), nullable=False),
        sa.Column("sender_name", sa.Text(), nullable=True),
        sa.Column("sender_domain", sa.Text(), nullable=False),
        sa.Column("recipients", postgresql.JSONB(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("thread_depth", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "has_unsubscribe", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("is_reply", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (session_id IS NULL)",
            name="ck_emails_dual_scope_xor",
        ),
        sa.CheckConstraint(
            "(session_id IS NULL) OR (seed_email_id IS NOT NULL)",
            name="ck_emails_demo_rows_have_seed_id",
        ),
    )
    op.create_index(
        "uq_emails_user_gmail_msg",
        "emails",
        ["user_id", "gmail_message_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_emails_session_received",
        "emails",
        ["session_id", "received_at"],
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )
    op.create_index(
        "ix_emails_user_received",
        "emails",
        ["user_id", "received_at"],
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )

    # ---- triage_decisions ----------------------------------------------
    op.create_table(
        "triage_decisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "email_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("emails.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("demo_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("lane", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("tier", sa.SmallInteger(), nullable=False),
        sa.Column("tier_2_source", sa.Text(), nullable=True),
        sa.Column("classifier_version", sa.Text(), nullable=True),
        sa.Column("top_features", postgresql.JSONB(), nullable=True),
        sa.Column("agent_trace", postgresql.JSONB(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (session_id IS NULL)",
            name="ck_triage_dual_scope_xor",
        ),
        sa.CheckConstraint(
            "lane IN ('needs_you','informational','hidden')",
            name="ck_triage_lane_enum",
        ),
        sa.CheckConstraint("tier IN (1, 2)", name="ck_triage_tier_range"),
        sa.CheckConstraint(
            "tier_2_source IS NULL OR tier_2_source IN ('live','prerecorded','unavailable')",
            name="ck_triage_source_enum",
        ),
    )
    op.create_index(
        "ix_triage_email_decided", "triage_decisions", ["email_id", "decided_at"]
    )
    op.create_index(
        "ix_triage_session",
        "triage_decisions",
        ["session_id"],
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )

    # ---- actions -------------------------------------------------------
    op.create_table(
        "actions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "email_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("emails.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("demo_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("from_lane", sa.Text(), nullable=True),
        sa.Column("to_lane", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (session_id IS NULL)",
            name="ck_actions_dual_scope_xor",
        ),
        sa.CheckConstraint(
            "action_type IN ('lane_moved','archived','starred','draft_edited',"
            "'draft_discarded','marked_read','snoozed')",
            name="ck_actions_type_enum",
        ),
    )
    op.create_index(
        "ix_actions_user_occurred",
        "actions",
        ["user_id", "occurred_at"],
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_actions_session_occurred",
        "actions",
        ["session_id", "occurred_at"],
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )

    # ---- training_examples --------------------------------------------
    op.create_table(
        "training_examples",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "email_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("emails.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("demo_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("label_source", sa.Text(), nullable=False),
        sa.Column("features", postgresql.JSONB(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column("embedding_dim", sa.Integer(), nullable=True),
        sa.Column(
            "embedding_dtype", sa.Text(), nullable=True, server_default="float32"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (session_id IS NULL)",
            name="ck_training_dual_scope_xor",
        ),
        sa.CheckConstraint(
            "label IN ('needs_you','informational','hidden')",
            name="ck_training_label_enum",
        ),
        sa.CheckConstraint(
            "label_source IN ('user_move','user_archive','initial_seed')",
            name="ck_training_source_enum",
        ),
        sa.CheckConstraint(
            "(embedding IS NULL) OR (embedding_dim IS NOT NULL AND embedding_dtype IS NOT NULL)",
            name="ck_training_embedding_metadata",
        ),
    )
    op.create_index(
        "ix_training_user",
        "training_examples",
        ["user_id"],
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_training_session",
        "training_examples",
        ["session_id"],
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )

    # ---- classifier_models --------------------------------------------
    op.create_table(
        "classifier_models",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("model_blob", sa.LargeBinary(), nullable=False),
        sa.Column("sklearn_version", sa.Text(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column(
            "trained_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.UniqueConstraint("user_id", "version", name="uq_classifier_user_version"),
    )
    op.create_index(
        "ix_classifier_user_active",
        "classifier_models",
        ["user_id", "is_active"],
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    op.drop_table("classifier_models")
    op.drop_table("training_examples")
    op.drop_table("actions")
    op.drop_table("triage_decisions")
    op.drop_table("emails")
    op.drop_table("demo_sessions")
    op.drop_table("users")
