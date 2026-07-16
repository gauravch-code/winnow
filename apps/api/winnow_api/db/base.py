"""Declarative base and shared column types.

Kept in its own module so Alembic's env.py can import ``Base`` without
pulling in the full model graph (avoids circular imports during autogenerate).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import DeclarativeBase

try:
    from uuid_utils import uuid7 as _uuid7
except ImportError:  # pragma: no cover - fallback only if uuid_utils missing
    _uuid7 = None


def new_uuid() -> uuid.UUID:
    """Time-ordered UUIDv7 when available, uuid4 fallback.

    UUIDv7 gives us index-friendly primary keys without requiring a
    Postgres extension (Postgres 16 has no native uuidv7()).
    """
    if _uuid7 is None:
        return uuid.uuid4()
    return uuid.UUID(str(_uuid7()))


class Base(DeclarativeBase):
    pass
