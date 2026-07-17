"""``winnow bootstrap`` CLI tests.

Uses Typer's CLIRunner in-process to test the command directly — the
alternative (subprocess spawn) would double test time and give us no
better fidelity for a command that just does a DB query + insert.

Real-mode requires ``users`` to be empty at start; demo-mode is
forbidden entirely.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from winnow_api.cli import app
from winnow_api.config import get_settings
from winnow_api.db.models import User


@pytest.fixture
def real_mode(monkeypatch: pytest.MonkeyPatch, engine, db_url):
    """Force settings into real mode, point at the test DB.

    ``db_url`` (the raw string from WINNOW_TEST_DATABASE_URL) is used
    verbatim — ``str(engine.url)`` masks the password with ``***`` and
    the subprocess-free CLI in this test spawns SQLAlchemy against the
    settings string directly.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "mode", "real")
    monkeypatch.setattr(settings, "encryption_key", "x" * 44)  # dummy
    monkeypatch.setattr(settings, "llm_api_key", "sk-test")
    monkeypatch.setattr(settings, "database_url", db_url)


@pytest.fixture(autouse=True)
def _wipe_users(db: Session):
    db.query(User).delete()
    db.commit()
    yield
    db.rollback()
    db.query(User).delete()
    db.commit()


def test_bootstrap_creates_owner_row(real_mode, db: Session):
    runner = CliRunner()
    result = runner.invoke(app, ["bootstrap", "--email", "me@example.com"])
    assert result.exit_code == 0, result.output
    assert "Created owner row" in result.output

    users = db.query(User).all()
    assert len(users) == 1
    assert users[0].email == "me@example.com"


def test_bootstrap_refuses_in_demo_mode(monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "mode", "demo")
    monkeypatch.setattr(settings, "ip_hash_salt", "salt")

    runner = CliRunner()
    result = runner.invoke(app, ["bootstrap", "--email", "me@example.com"])
    assert result.exit_code == 1
    assert "WINNOW_MODE=demo" in result.output


def test_bootstrap_refuses_second_run(real_mode, db: Session):
    """The one-owner-per-install invariant is enforced at the CLI, not
    just at the DB level — a friendly error beats a UniqueViolation."""
    runner = CliRunner()
    first = runner.invoke(app, ["bootstrap", "--email", "me@example.com"])
    assert first.exit_code == 0

    second = runner.invoke(app, ["bootstrap", "--email", "other@example.com"])
    assert second.exit_code == 1
    assert "already has 1 row" in second.output


def test_bootstrap_requires_email():
    """--email is required; missing it should surface Typer's own message."""
    runner = CliRunner()
    result = runner.invoke(app, ["bootstrap"])
    assert result.exit_code != 0
