"""``winnow gmail ...`` subcommands.

Kept in ``winnow_api.commands`` (not ``winnow_api.gmail``) so importing
this module in demo mode raises at the top of Typer's dispatch — not
buried under the click of a subcommand.
"""

from __future__ import annotations

import time
from pathlib import Path

import typer
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from winnow_api.config import get_settings
from winnow_api.db.models import User
from winnow_api.gmail import (
    GmailClient,
    GmailSync,
    authorize_installed_app,
    load_credentials_for_user,
)

gmail_app = typer.Typer(help="Gmail sync commands (real mode only).", no_args_is_help=True)


def _owner_or_die(db: Session) -> User:
    user = db.execute(select(User).limit(1)).scalar_one_or_none()
    if user is None:
        typer.secho(
            "No owner user found. Run `winnow bootstrap --email you@example.com` first.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    return user


@gmail_app.command("authorize")
def authorize_cmd(
    credentials_file: Path = typer.Option(
        ...,
        "--credentials-file",
        "-c",
        exists=True,
        readable=True,
        help="OAuth 2.0 credentials JSON downloaded from Google Cloud Console (desktop client).",
    ),
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Skip auto-opening the browser (print the URL instead).",
    ),
) -> None:
    """Run the installed-app OAuth flow and store the encrypted refresh token."""
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as db:
        user = _owner_or_die(db)
        authorize_installed_app(db, user, credentials_file, open_browser=not no_browser)
    typer.secho("OK — Gmail refresh token stored (encrypted). Next: `winnow gmail sync --full`.", fg=typer.colors.GREEN)


@gmail_app.command("sync")
def sync_cmd(
    full: bool = typer.Option(False, "--full", help="Force initial N-day backfill."),
    days: int = typer.Option(30, "--days", help="Backfill window for --full."),
) -> None:
    """Trigger a Gmail sync now. Default is incremental; --full backfills."""
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as db:
        user = _owner_or_die(db)
        creds = load_credentials_for_user(user)
        client = GmailClient(creds)
        sync = GmailSync(client, db, user, classifier=None)  # CLI runs without classifier for speed
        report = sync.sync_full(days=days) if full else sync.sync_incremental()

    typer.secho(
        f"Sync done: strategy={report.strategy} ingested={report.ingested} "
        f"skipped_dup={report.skipped_duplicate} history_id={report.ended_history_id}",
        fg=typer.colors.GREEN,
    )


@gmail_app.command("listen")
def listen_cmd(
    poll_interval: int = typer.Option(60, "--poll-interval", "-i", help="Seconds between polls."),
) -> None:
    """Polling fallback when Pub/Sub push isn't set up.

    Runs forever; Ctrl+C to stop. Each tick opens a fresh DB session so
    a hung sync doesn't hold connections indefinitely.
    """
    settings = get_settings()
    engine = create_engine(settings.database_url)
    typer.echo(f"Polling Gmail every {poll_interval}s. Ctrl+C to stop.")
    while True:
        try:
            with Session(engine) as db:
                user = _owner_or_die(db)
                creds = load_credentials_for_user(user)
                client = GmailClient(creds)
                report = GmailSync(client, db, user, classifier=None).sync_incremental()
                typer.echo(
                    f"[poll] ingested={report.ingested} skipped={report.skipped_duplicate} "
                    f"strategy={report.strategy}"
                )
        except KeyboardInterrupt:
            typer.echo("Stopping.")
            raise typer.Exit()
        except Exception as exc:  # noqa: BLE001
            typer.secho(f"[poll] error: {type(exc).__name__}: {exc}", fg=typer.colors.YELLOW, err=True)
        time.sleep(poll_interval)


@gmail_app.command("watch")
def watch_cmd(
    topic: str = typer.Option(..., "--topic", help="Full Pub/Sub topic name: projects/PROJECT/topics/NAME"),
) -> None:
    """Register the Gmail Pub/Sub watch. Renew before the 7-day expiration."""
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as db:
        user = _owner_or_die(db)
        creds = load_credentials_for_user(user)
        client = GmailClient(creds)
        response = client.start_watch(topic)
        state = dict(user.gmail_state or {})
        state["watch_expiration"] = response.get("expiration")
        state["watch_topic"] = topic
        # First historyId sync anchor.
        state.setdefault("history_id", response.get("historyId"))
        user.gmail_state = state
        db.commit()
    typer.secho(f"Watch registered. Expires: {response.get('expiration')}", fg=typer.colors.GREEN)
