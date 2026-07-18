"""``winnow`` CLI entrypoint.

Registered via ``[project.scripts]`` in pyproject.toml, so ``uv pip
install -e apps/api`` puts a ``winnow`` binary on PATH.

Subcommands:
  winnow bootstrap             — create the owner user row (real mode only)
  winnow gmail authorize       — installed-app OAuth flow
  winnow gmail sync            — incremental sync
  winnow gmail sync --full     — initial N-day backfill
  winnow gmail listen          — polling loop as Pub/Sub fallback
  winnow gmail watch           — register Pub/Sub push subscription

Gmail subcommands import lazily so ``winnow bootstrap`` works even
before the Google client libraries are installed, and so the demo-mode
import guard doesn't fire when a demo-mode operator runs ``winnow``.
"""

from __future__ import annotations

import typer

from winnow_api.commands.bootstrap import bootstrap_cmd
from winnow_api.commands.eval_cli import eval_cmd
from winnow_api.commands.retrain_cli import retrain_cmd, rollback_cmd

app = typer.Typer(
    help="Winnow — local-first AI inbox triage.",
    no_args_is_help=True,
    add_completion=False,
)

app.command("bootstrap")(bootstrap_cmd)
app.command("retrain")(retrain_cmd)
app.command("rollback")(rollback_cmd)
app.command("eval")(eval_cmd)


@app.callback()
def _root() -> None:
    """Top-level Typer callback — reserved for future flags."""


# Lazy Gmail subgroup registration so we don't force-import the gmail
# module (and its import-time mode check) when the user only wants
# `winnow bootstrap`.
def _register_gmail() -> None:
    from winnow_api.commands.gmail_cli import gmail_app

    app.add_typer(gmail_app, name="gmail", help="Gmail sync commands (real mode only).")


try:
    _register_gmail()
except ImportError:
    # winnow_api.gmail intentionally refuses to import in demo mode.
    # The subgroup is simply absent — running `winnow gmail ...` in demo
    # mode prints Typer's standard "no such command" message, which is
    # a fine UX for what is a user error.
    pass


if __name__ == "__main__":
    app()
