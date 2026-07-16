"""Shared pytest fixtures.

The integration tests need a real Postgres — the whole point of
``test_dual_scoping_invariant.py`` is to prove that the *database*
rejects bad rows, so SQLite (which parses but doesn't enforce CHECK
identically for this pattern) is not an acceptable stand-in.

Set ``WINNOW_TEST_DATABASE_URL`` to a Postgres URL. Tests are skipped if
unset, so the suite still passes on a machine with no local Postgres.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from winnow_api.db import Base


@pytest.fixture(scope="session")
def db_url() -> str:
    url = os.environ.get("WINNOW_TEST_DATABASE_URL")
    if not url:
        pytest.skip("WINNOW_TEST_DATABASE_URL not set; skipping integration tests.")
    return url


@pytest.fixture(scope="session")
def engine(db_url: str):
    eng = create_engine(db_url, future=True)
    # Fresh schema per test session. Fine for CI; local devs run against a
    # scratch DB anyway.
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine) -> Session:
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
