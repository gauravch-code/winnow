"""add users.gmail_state JSONB

gmail_state carries the ephemeral state Winnow needs to keep Gmail sync
running: the last historyId we synced through, the last sync timestamp,
and the Pub/Sub watch expiration. Kept as a JSONB blob rather than
separate columns because these fields are Gmail-specific — if we ever
support another provider its state would need a different shape.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("gmail_state", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "gmail_state")
