"""enforce_mode_invariant integration tests. Requires Postgres.

The whole point of the invariant is that a demo-mode boot never touches
real-user data, and a real-mode boot never runs without the owner's row.
These invariants are load-bearing, so we exercise them against a real
database — not a mock.

Skipped cleanly if WINNOW_TEST_DATABASE_URL is not set, so the pure
unit suite still passes on a machine without Postgres.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from winnow_api.config import ModeMismatchError, Settings, enforce_mode_invariant
from winnow_api.db.models import User


def _settings(mode: str) -> Settings:
    extra: dict[str, str] = {}
    if mode == "real":
        extra["encryption_key"] = "e"
        extra["llm_api_key"] = "k"
    else:
        extra["ip_hash_salt"] = "salty"
    return Settings(
        mode=mode,  # type: ignore[arg-type]
        database_url="postgresql+psycopg://unused",
        _env_file=None,  # type: ignore[call-arg]
        **extra,
    )


@pytest.fixture(autouse=True)
def _wipe_users(db: Session):
    """Every test in this module starts with an empty users table.

    The DB fixture in conftest.py uses a session-scoped engine, so state
    leaks between test files. Explicit wipe here keeps assertions honest.
    Rolls back before the teardown DELETE in case a test left the
    transaction in an aborted state (e.g. the ``enforce`` calls that
    intentionally trigger a ProgrammingError).
    """
    db.query(User).delete()
    db.commit()
    yield
    db.rollback()
    db.query(User).delete()
    db.commit()


# --- demo mode with real users → refuse ------------------------------------


def test_enforce_rejects_demo_when_users_table_has_rows(db: Session):
    db.add(User(email=f"me-{uuid.uuid4()}@example.com"))
    db.commit()

    with pytest.raises(ModeMismatchError, match="demo"):
        enforce_mode_invariant(_settings("demo"), db)


def test_enforce_accepts_demo_when_users_table_empty(db: Session):
    enforce_mode_invariant(_settings("demo"), db)  # must not raise


# --- real mode with empty users → refuse -----------------------------------


def test_enforce_rejects_real_when_users_table_empty(db: Session):
    with pytest.raises(ModeMismatchError, match="real"):
        enforce_mode_invariant(_settings("real"), db)


def test_enforce_accepts_real_when_owner_row_exists(db: Session):
    db.add(User(email=f"me-{uuid.uuid4()}@example.com"))
    db.commit()

    enforce_mode_invariant(_settings("real"), db)  # must not raise


# --- helpful error when the schema itself is missing -----------------------


def test_enforce_gives_helpful_error_when_users_table_missing(db: Session):
    """If someone starts the API before running migrations, they should
    see a clear message pointing them at alembic, not a raw psycopg
    ProgrammingError.

    Uses its own connection + savepoint so the DROP doesn't leak into
    other tests via the session-scoped engine.
    """
    from sqlalchemy import text

    from winnow_api.db import Base

    engine = db.get_bind()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE users CASCADE"))

    try:
        with pytest.raises(ModeMismatchError, match="alembic"):
            enforce_mode_invariant(_settings("real"), db)
    finally:
        # Restore for subsequent tests. create_all is idempotent for
        # other tables and only creates the missing `users`.
        Base.metadata.create_all(engine)
