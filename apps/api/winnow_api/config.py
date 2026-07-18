"""Runtime configuration and boot-time invariants.

Two responsibilities:

1. **Settings**: typed wrapper over env vars via ``pydantic-settings``.
   Every env var Winnow reads is declared here. Missing/invalid values
   fail at import time, not deep in a request handler.

2. **Mode enforcement**: ``WINNOW_MODE=real|demo`` must be consistent
   with what's in the DB. Called from ``main.py``'s lifespan hook so a
   misconfigured process refuses to accept requests at all — never
   half-boots into a state where demo code touches real data or vice
   versa.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

Mode = Literal["real", "demo"]

# Default data directories: repo-relative for local dev. In Docker/Fly.io,
# override with WINNOW_FIXTURE_DIR / WINNOW_SEED_EMAIL_DIR to wherever the
# JSON files are mounted.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_FIXTURE_DIR = _REPO_ROOT / "packages" / "seed-data" / "llm-responses"
_DEFAULT_SEED_EMAIL_DIR = _REPO_ROOT / "packages" / "seed-data" / "emails"


class ModeMismatchError(RuntimeError):
    """DB state contradicts WINNOW_MODE. Refuse to boot."""


class Settings(BaseSettings):
    """All env vars Winnow reads.

    Keep this class the *only* place ``os.environ`` gets touched. If a
    module needs a config value, it takes ``Settings`` as a dependency.
    """

    model_config = SettingsConfigDict(
        env_prefix="WINNOW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mode: Mode = Field(description="'real' for self-hosted; 'demo' for public site.")
    database_url: str = Field(description="SQLAlchemy URL, e.g. postgresql+psycopg://…")

    # Required in real mode; unused in demo mode.
    encryption_key: str | None = Field(
        default=None,
        description="Fernet key for gmail_refresh_token. Required when mode=real.",
    )
    llm_api_key: str | None = Field(
        default=None,
        description="LLM provider API key. Required when mode=real.",
    )
    llm_provider: str = "anthropic"
    # Optional model override; None uses the provider's default from
    # winnow_api.agents.provider.DEFAULT_MODELS. Set e.g. "gpt-4o-mini"
    # for a cheaper OpenAI tier-2.
    llm_model: str | None = None

    # Required in demo mode; unused in real mode.
    ip_hash_salt: str | None = Field(
        default=None,
        description="HMAC-SHA256 salt for demo_sessions.ip_hash. Required when mode=demo.",
    )
    fixture_dir: Path = Field(
        default=_DEFAULT_FIXTURE_DIR,
        description="Directory of pre-recorded tier-2 fixtures. Consumed only in demo mode.",
    )
    seed_email_dir: Path = Field(
        default=_DEFAULT_SEED_EMAIL_DIR,
        description="Directory of synthetic seed emails. Consumed only in demo mode.",
    )
    demo_seed_count: int = Field(
        default=40,
        description="How many seed emails to load into each fresh demo session.",
    )
    demo_session_ttl_hours: int = Field(
        default=24,
        description="TTL for a demo session cookie and its DB rows.",
    )
    # Default from eval sweep; see docs/evals.md#threshold-selection.
    # Do not change without re-running the sweep. Demo mode uses this
    # because it has no per-user threshold (no users in demo mode).
    demo_confidence_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:3001"],
        description="Origins allowed for CORS. Only used in demo mode.",
    )
    # Gmail / Pub/Sub — real mode only.
    pubsub_audience: str | None = Field(
        default=None,
        description="Expected 'aud' claim on Pub/Sub push JWTs. Set to the webhook URL.",
    )
    gmail_backfill_days: int = Field(
        default=30,
        description="How many days to backfill on first sync.",
    )

    # Learning loop — real mode only.
    retrain_cron: str = Field(
        default="0 2 * * *",
        description="Cron for the nightly retrain job. UTC.",
    )
    retrain_min_examples: int = Field(
        default=20,
        description="Refuse to retrain until we have at least this many user-labeled examples.",
    )
    retrain_regression_threshold: float = Field(
        default=0.05,
        description="Reject a new model whose holdout accuracy is > threshold below the current one.",
        ge=0.0,
        le=1.0,
    )

    @model_validator(mode="after")
    def _check_mode_dependent_vars(self) -> "Settings":
        missing: list[str] = []
        if self.mode == "real":
            if not self.encryption_key:
                missing.append("WINNOW_ENCRYPTION_KEY")
            if not self.llm_api_key:
                missing.append("WINNOW_LLM_API_KEY")
        else:  # demo
            if not self.ip_hash_salt:
                missing.append("WINNOW_IP_HASH_SALT")
        if missing:
            raise ValueError(
                f"WINNOW_MODE={self.mode} requires: {', '.join(missing)}"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor. Uncached instantiation would reparse env on every call."""
    try:
        return Settings()  # type: ignore[call-arg]  # values come from env
    except ValidationError as exc:
        raise RuntimeError(
            f"Winnow config invalid — refusing to boot.\n{exc}"
        ) from exc


def enforce_mode_invariant(settings: Settings, db: Session) -> None:
    """Refuse to boot if WINNOW_MODE contradicts DB state.

    - ``demo`` mode with any row in ``users`` → refuse. The demo backend
      must never touch a real-user database, even accidentally in staging.
    - ``real`` mode with zero rows in ``users`` → refuse. The owner's row
      is the anchor for every user-scoped query; running without it means
      every incoming email would fail to persist and the failure would
      surface far from the root cause.

    Raises ``ModeMismatchError`` on violation. Called from the FastAPI
    lifespan hook; a failed check means the app never accepts requests.
    """
    from winnow_api.db.models import User

    try:
        user_count = db.execute(select(func.count()).select_from(User)).scalar_one()
    except ProgrammingError as exc:
        raise ModeMismatchError(
            "Could not read users table. Have you run `alembic upgrade head`?"
        ) from exc

    if settings.mode == "demo" and user_count > 0:
        raise ModeMismatchError(
            f"WINNOW_MODE=demo but users table has {user_count} row(s). "
            "Demo mode must never run against a real-user database. Refusing to boot."
        )
    if settings.mode == "real" and user_count == 0:
        raise ModeMismatchError(
            "WINNOW_MODE=real but users table is empty. Real mode requires the "
            "owner's user row to exist (bootstrap it before starting the API). "
            "Refusing to boot."
        )
