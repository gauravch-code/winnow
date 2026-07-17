"""APScheduler wrapper for the nightly retrain job.

Wrapped so the FastAPI lifespan hook can start/stop it cleanly and
tests can inject their own trigger (or none at all). The scheduler is
real-mode only — demo mode has no persistent classifier to update.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from winnow_api.config import Settings
from winnow_api.db.models import User
from winnow_api.learning.retrainer import Retrainer

log = structlog.get_logger(__name__)


def start_nightly_retrain(
    scheduler: AsyncIOScheduler,
    settings: Settings,
    seed_dir: Path,
) -> None:
    """Register the nightly retrain job with the given scheduler."""
    trigger = CronTrigger.from_crontab(settings.retrain_cron)

    def _job() -> None:
        # Fresh engine + session per job — the scheduler runs on a
        # different loop; sharing the app's Session pool would risk
        # cross-thread leaks that only manifest under sustained load.
        engine = create_engine(settings.database_url, future=True)
        with Session(engine) as db:
            user = db.execute(select(User).limit(1)).scalar_one_or_none()
            if user is None:
                log.warning("retrain_skipped_no_owner")
                return
            retrainer = Retrainer(
                db=db,
                user=user,
                seed_dir=seed_dir,
                min_examples=settings.retrain_min_examples,
                regression_threshold=settings.retrain_regression_threshold,
            )
            report = retrainer.run()
            log.info(
                "nightly_retrain_finished",
                outcome=report.outcome.value,
                accuracy=report.holdout_accuracy,
                n_examples=report.n_training_examples,
            )
        engine.dispose()

    scheduler.add_job(
        _job,
        trigger=trigger,
        id="nightly_retrain",
        replace_existing=True,
    )
    log.info("nightly_retrain_scheduled", cron=settings.retrain_cron)
