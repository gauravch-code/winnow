"""FastAPI entrypoint.

Wiring order matters: Starlette forbids ``add_middleware`` after the
lifespan starts, so middleware and routers are registered at import
time (using settings loaded from env). The lifespan hook only performs
*runtime* setup — engine creation, DB invariant check, fixture loading —
and refuses to yield if anything is inconsistent.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from winnow_api.config import enforce_mode_invariant, get_settings

log = structlog.get_logger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("winnow_boot", mode=settings.mode)

    engine = create_engine(settings.database_url, future=True)
    with Session(engine) as db:
        enforce_mode_invariant(settings, db)

    app.state.settings = settings
    app.state.engine = engine

    # --- tier-1 classifier: needed in BOTH modes -----------------------
    # (demo seeds/classifies visitor sessions; real mode classifies
    # ingested Gmail and powers /emails + escalate). Loading it only in
    # demo mode was a real bug — real-mode sync fell back to the
    # no-classifier path and labeled everything "informational".
    _load_classifier(app)

    if settings.mode == "demo":
        from winnow_api.demo.fixtures import FixtureLoader

        loader = FixtureLoader(settings.fixture_dir)
        loader.load()
        app.state.fixture_loader = loader
        log.info("demo_fixtures_ready", count=len(loader))

        # Demo tier-2 = pre-recorded fixtures. Live LLM calls are never
        # made in demo mode; that's the whole $0 guarantee.
        from winnow_api.agents.fixture_provider import FixtureProvider

        app.state.tier_2_provider = FixtureProvider(loader)

    _warm_embeddings(app)

    scheduler = None
    if settings.mode == "real":
        # Real tier-2 = live LLM with the owner's key. Built here so the
        # /emails/{id}/escalate endpoint has a provider on app.state.
        _configure_live_tier2(app, settings)
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        from winnow_api.learning.scheduler import start_nightly_retrain

        scheduler = AsyncIOScheduler()
        start_nightly_retrain(scheduler, settings, settings.seed_email_dir)
        scheduler.start()
        app.state.scheduler = scheduler

    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        engine.dispose()


def _load_classifier(app: FastAPI) -> None:
    """Load the baseline tier-1 model onto app.state (both modes).

    Absence is non-fatal — demo falls back to seeded labels, real mode
    logs a warning and returns low-confidence decisions until the model
    is trained (`uv run python -m winnow_api.classifier.train`).
    """
    from pathlib import Path

    from winnow_api.classifier import Classifier

    artifact_path = (
        Path(__file__).resolve().parent / "classifier" / "artifacts" / "base.joblib"
    )
    if artifact_path.exists():
        app.state.classifier = Classifier.load(artifact_path, version_label="base-0.1")
        log.info(
            "classifier_loaded",
            version=app.state.classifier.version,
            metrics=app.state.classifier.model.training_metrics,
        )
    else:
        app.state.classifier = None
        log.warning(
            "classifier_artifact_missing",
            path=str(artifact_path),
            message="Run `uv run python -m winnow_api.classifier.train`.",
        )


def _warm_embeddings(app: FastAPI) -> None:
    """Pay MiniLM's ~15s cold load at boot, not on the first request."""
    if getattr(app.state, "classifier", None) is None:
        return
    try:
        from winnow_api.classifier.embeddings import embed_one

        embed_one("warmup", "warming the embedding model at boot")
        log.info("embedding_model_warmed")
    except Exception as exc:  # noqa: BLE001 — warmup is optional
        log.warning("embedding_warmup_failed", error=str(exc))


def _configure_live_tier2(app: FastAPI, settings) -> None:  # noqa: ANN001
    """Wire the live LLM provider for real-mode escalation.

    PydanticAI reads the provider's *standard* env var (OPENAI_API_KEY /
    ANTHROPIC_API_KEY) from the environment, not our WINNOW_LLM_API_KEY.
    So we bridge: copy WINNOW_LLM_API_KEY into the right standard var
    based on the configured provider, then build the agent. Without this
    bridge the key would be validated at boot but never actually reach
    the LLM. If no key is set, tier-2 stays unconfigured and escalate
    returns a clear 503 (tier-1 still works fully).
    """
    import os

    if not settings.llm_api_key:
        app.state.tier_2_provider = None
        log.info("live_tier2_disabled", reason="no WINNOW_LLM_API_KEY")
        return

    provider = settings.llm_provider.strip().lower()
    _ENV_BY_PROVIDER = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    env_name = _ENV_BY_PROVIDER.get(provider)
    if env_name and not os.environ.get(env_name):
        os.environ[env_name] = settings.llm_api_key

    from winnow_api.agents.live_provider import LiveAgentProvider
    from winnow_api.agents.provider import get_model

    model = get_model(provider, settings.llm_model)
    app.state.tier_2_provider = LiveAgentProvider(model)
    log.info("live_tier2_ready", provider=provider, model=settings.llm_model or "default")


app = FastAPI(title="Winnow API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if settings.mode == "demo":
    # Local imports so the real app never touches the demo module graph.
    from winnow_api.demo.routes import router as demo_router
    from winnow_api.demo.session import DemoSessionMiddleware

    # Engine isn't built yet (that happens in lifespan). The middleware
    # reads from app.state at request time via a closure.
    def _session_factory() -> Session:
        return Session(bind=app.state.engine, expire_on_commit=False)

    app.add_middleware(
        DemoSessionMiddleware,
        session_factory=_session_factory,
        settings=settings,
    )
    app.include_router(demo_router)
else:
    # Real mode — Gmail sync routes + the dashboard's email API. Local
    # imports match the demo-side discipline (never pull the other mode's
    # module graph into memory).
    from winnow_api.gmail.routes import router as gmail_router
    from winnow_api.realapp import router as realapp_router

    app.include_router(gmail_router)
    app.include_router(realapp_router)


# Scheduler is registered in the lifespan (below) so the loop is up
# and the DB engine exists before the first job could fire.
_scheduler = None  # type: ignore[var-annotated]


@app.get("/health")
async def health() -> dict[str, str | int]:
    payload: dict[str, str | int] = {"status": "ok", "mode": settings.mode}
    if settings.mode == "demo":
        payload["fixtures_loaded"] = len(app.state.fixture_loader)
    return payload


logging.basicConfig(level=logging.INFO)
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
)
