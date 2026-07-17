"""``winnow bootstrap`` — create the owner user row.

Winnow's real-mode invariant is "exactly one user row exists — the
owner." Before ``winnow bootstrap`` runs, the API refuses to boot in
real mode. After it runs, the API happily starts.

The command is deliberately narrow:
- Real mode only (refuses in demo mode).
- Refuses if any user row already exists — otherwise a stray re-run
  could create a second owner and silently violate the invariant.
- Idempotency check is on the users table, not the email, so
  --email=other@example.com after a first bootstrap is also blocked.
"""

from __future__ import annotations

import sys

import typer
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from winnow_api.config import get_settings
from winnow_api.db.models import User


def bootstrap_cmd(
    email: str = typer.Option(..., "--email", "-e", help="Owner email address."),
) -> None:
    """Create the owner user row."""
    settings = get_settings()
    if settings.mode != "real":
        typer.secho(
            f"winnow bootstrap refuses to run in WINNOW_MODE={settings.mode}. "
            "This command creates a real owner; set WINNOW_MODE=real first.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    engine = create_engine(settings.database_url)
    with Session(engine) as db:
        existing_count = db.execute(select(func.count()).select_from(User)).scalar_one()
        if existing_count > 0:
            existing = db.execute(select(User.email).limit(1)).scalar_one()
            typer.secho(
                f"Refusing: users table already has {existing_count} row(s) "
                f"(first: {existing}). Winnow supports one owner per install.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)

        user = User(email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
        typer.secho(
            f"Created owner row: id={user.id} email={user.email}",
            fg=typer.colors.GREEN,
        )
        typer.echo("Next: `winnow gmail authorize --credentials-file <path>`")
