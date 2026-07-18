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

    if settings.mode == "demo":
        from pathlib import Path

        from winnow_api.classifier import Classifier
        from winnow_api.demo.fixtures import FixtureLoader

        loader = FixtureLoader(settings.fixture_dir)
        loader.load()
        app.state.fixture_loader = loader
        log.info("demo_fixtures_ready", count=len(loader))

        # Load the baseline tier-1 model. Absence is non-fatal — the
        # seeder falls back to ground-truth labels and the API still
        # boots, which keeps ``uv run pytest`` fast and lets first-time
        # contributors see the UI before running the training script.
        artifact_path = Path(__file__).resolve().parent / "classifier" / "artifacts" / "base.joblib"
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
                message="Falling back to seeded ground-truth lanes. Run `uv run python -m winnow_api.classifier.train`.",
            )

        # Demo tier-2 = pre-recorded fixtures. Live LLM calls are never
        # made in demo mode; that's the whole $0 guarantee.
        from winnow_api.agents.fixture_provider import FixtureProvider

        app.state.tier_2_provider = FixtureProvider(loader)

        # Warm the MiniLM embedding model at boot. It otherwise loads
        # lazily on the first /demo/emails request — ~15s cold, during
        # which a first-time visitor stares at a "Loading…" spinner that
        # can gateway-timeout. Paying that cost here (invisible startup
        # time) makes the first real request ~1-2s. Best-effort: a
        # failure here must not stop the API from booting.
        if app.state.classifier is not None:
            try:
                from winnow_api.classifier.embeddings import embed_one

                embed_one("warmup", "warming the embedding model at boot")
                log.info("embedding_model_warmed")
            except Exception as exc:  # noqa: BLE001 — warmup is optional
                log.warning("embedding_warmup_failed", error=str(exc))

    scheduler = None
    if settings.mode == "real":
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
    # Real mode — Gmail sync routes. Local import matches the demo-side
    # discipline (never pull the other mode's module graph into memory).
    from winnow_api.gmail.routes import router as gmail_router

    app.include_router(gmail_router)


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
