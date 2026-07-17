"""``winnow retrain`` and ``winnow rollback`` subcommands."""

from __future__ import annotations

import typer
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from winnow_api.config import get_settings
from winnow_api.db.models import User
from winnow_api.learning.artifacts import rollback_to_previous
from winnow_api.learning.retrainer import Retrainer


def retrain_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="Evaluate but don't rotate artifacts."),
    force: bool = typer.Option(False, "--force", help="Deploy even if the new model regresses."),
) -> None:
    """Trigger a retrain now."""
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as db:
        user = db.execute(select(User).limit(1)).scalar_one_or_none()
        if user is None:
            typer.secho("No owner user. Run `winnow bootstrap` first.", err=True, fg=typer.colors.RED)
            raise typer.Exit(1)
        retrainer = Retrainer(
            db=db,
            user=user,
            seed_dir=settings.seed_email_dir,
            min_examples=settings.retrain_min_examples,
            regression_threshold=settings.retrain_regression_threshold,
        )
        report = retrainer.run(force=force, dry_run=dry_run)
    color = typer.colors.GREEN if report.rejection_reason is None else typer.colors.YELLOW
    typer.secho(
        f"outcome={report.outcome.value} "
        f"holdout_acc={report.holdout_accuracy} "
        f"prev_active_acc={report.previous_active_accuracy} "
        f"n_train={report.n_training_examples} n_holdout={report.n_holdout}",
        fg=color,
    )
    if report.rejection_reason:
        typer.secho(report.rejection_reason, fg=typer.colors.YELLOW)


def rollback_cmd() -> None:
    """Swap the currently-active artifact with the previous one."""
    ok = rollback_to_previous()
    if not ok:
        typer.secho("Nothing to roll back to — no previous artifact.", err=True, fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.secho("Rolled back to previous artifact.", fg=typer.colors.GREEN)
