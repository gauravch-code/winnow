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

    try:
        yield
    finally:
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
