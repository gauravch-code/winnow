"""expand training_examples.label_source and add classifier_metrics_history

Two changes for the learning loop:

- ``training_examples.label_source`` is expanded to accept every action
  that produces a labeled example. The old CHECK constraint
  ('user_move','user_archive','initial_seed') is dropped and replaced
  with the wider set. Kept as a CHECK rather than an ENUM so schema
  evolution stays cheap.

- ``classifier_metrics_history`` records one row per retrain attempt
  (deployed or rejected), with per-lane holdout precision/recall/f1
  plus the accuracy the currently-active model got on the same
  holdout — that's what makes the "did the new model regress?" gate
  auditable after the fact.

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LABEL_SOURCE_VALUES = (
    "initial_seed",
    "user_move",
    "user_archive",
    "user_star",
    "user_draft_edit",
    "user_snooze",
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_training_source_enum", "training_examples", type_="check"
    )
    op.create_check_constraint(
        "ck_training_source_enum",
        "training_examples",
        "label_source IN ("
        + ",".join(f"'{v}'" for v in LABEL_SOURCE_VALUES)
        + ")",
    )

    op.create_table(
        "classifier_metrics_history",
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
        sa.Column("classifier_version", sa.Text(), nullable=False),
        sa.Column(
            "trained_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("n_training_examples", sa.Integer(), nullable=False),
        sa.Column("n_holdout", sa.Integer(), nullable=False),
        sa.Column("holdout_accuracy", sa.Float(), nullable=False),
        # Full holdout confusion matrix stashed as JSONB — lets an eval
        # dashboard show per-lane precision/recall without joining
        # another table.
        sa.Column("per_lane_metrics", postgresql.JSONB(), nullable=False),
        # NULL if this was the first retrain (no active model to compare).
        sa.Column("previous_active_accuracy", sa.Float(), nullable=True),
        sa.Column("deployed", sa.Boolean(), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_metrics_user_trained",
        "classifier_metrics_history",
        ["user_id", "trained_at"],
    )


def downgrade() -> None:
    op.drop_table("classifier_metrics_history")
    op.drop_constraint(
        "ck_training_source_enum", "training_examples", type_="check"
    )
    op.create_check_constraint(
        "ck_training_source_enum",
        "training_examples",
        "label_source IN ('user_move','user_archive','initial_seed')",
    )
