"""Settings validation — pure unit tests.

Every test sets env vars explicitly via ``monkeypatch`` so a stray .env
in the working directory can't contaminate results. The DB-invariant
side of config is exercised in ``test_config_db.py`` (needs Postgres).
"""

from __future__ import annotations

import pytest

from winnow_api.config import Settings


@pytest.fixture(autouse=True)
def _clear_winnow_env(monkeypatch: pytest.MonkeyPatch):
    """Wipe any WINNOW_* env vars so tests start from a known-empty state."""
    for name in (
        "WINNOW_MODE",
        "WINNOW_DATABASE_URL",
        "WINNOW_ENCRYPTION_KEY",
        "WINNOW_LLM_API_KEY",
        "WINNOW_LLM_PROVIDER",
        "WINNOW_IP_HASH_SALT",
        "WINNOW_FIXTURE_DIR",
    ):
        monkeypatch.delenv(name, raising=False)


# --- real mode requires encryption + llm key -------------------------------


def test_real_mode_requires_encryption_key():
    with pytest.raises(Exception, match="WINNOW_ENCRYPTION_KEY"):
        Settings(
            mode="real",
            database_url="postgresql+psycopg://x",
            llm_api_key="k",
            # encryption_key missing
            _env_file=None,  # type: ignore[call-arg]
        )


def test_real_mode_requires_llm_api_key():
    with pytest.raises(Exception, match="WINNOW_LLM_API_KEY"):
        Settings(
            mode="real",
            database_url="postgresql+psycopg://x",
            encryption_key="e",
            _env_file=None,  # type: ignore[call-arg]
        )


def test_real_mode_reports_all_missing_vars_at_once():
    """A user with both vars missing should see both names, not just the first."""
    with pytest.raises(Exception) as exc_info:
        Settings(
            mode="real",
            database_url="postgresql+psycopg://x",
            _env_file=None,  # type: ignore[call-arg]
        )
    msg = str(exc_info.value)
    assert "WINNOW_ENCRYPTION_KEY" in msg
    assert "WINNOW_LLM_API_KEY" in msg


def test_real_mode_accepts_when_required_vars_present():
    s = Settings(
        mode="real",
        database_url="postgresql+psycopg://x",
        encryption_key="e",
        llm_api_key="k",
        _env_file=None,  # type: ignore[call-arg]
    )
    assert s.mode == "real"


def test_real_mode_does_not_require_ip_hash_salt():
    """Real mode has no demo sessions, so the salt is irrelevant."""
    s = Settings(
        mode="real",
        database_url="postgresql+psycopg://x",
        encryption_key="e",
        llm_api_key="k",
        _env_file=None,  # type: ignore[call-arg]
    )
    assert s.ip_hash_salt is None


# --- demo mode requires ip hash salt ---------------------------------------


def test_demo_mode_requires_ip_hash_salt():
    with pytest.raises(Exception, match="WINNOW_IP_HASH_SALT"):
        Settings(
            mode="demo",
            database_url="postgresql+psycopg://x",
            _env_file=None,  # type: ignore[call-arg]
        )


def test_demo_mode_accepts_when_salt_present():
    s = Settings(
        mode="demo",
        database_url="postgresql+psycopg://x",
        ip_hash_salt="salty",
        _env_file=None,  # type: ignore[call-arg]
    )
    assert s.mode == "demo"


def test_demo_mode_does_not_require_encryption_or_llm_key():
    """Demo has no Gmail refresh token to encrypt and no live LLM calls."""
    s = Settings(
        mode="demo",
        database_url="postgresql+psycopg://x",
        ip_hash_salt="salty",
        _env_file=None,  # type: ignore[call-arg]
    )
    assert s.encryption_key is None
    assert s.llm_api_key is None


# --- basic type / enum validation ------------------------------------------


def test_invalid_mode_rejected():
    with pytest.raises(Exception):
        Settings(
            mode="wat",  # type: ignore[arg-type]
            database_url="postgresql+psycopg://x",
            encryption_key="e",
            llm_api_key="k",
            _env_file=None,  # type: ignore[call-arg]
        )


def test_missing_mode_rejected():
    with pytest.raises(Exception):
        Settings(
            database_url="postgresql+psycopg://x",
            _env_file=None,  # type: ignore[call-arg]
        )


def test_missing_database_url_rejected():
    with pytest.raises(Exception):
        Settings(
            mode="demo",
            ip_hash_salt="salty",
            _env_file=None,  # type: ignore[call-arg]
        )
