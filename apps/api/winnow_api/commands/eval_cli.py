"""``winnow eval`` — regenerate the published eval numbers.

Runs the harness against the current classifier recipe + committed
fixtures, then writes docs/evals.md and apps/site/app/evals/results.json.
Mode-agnostic: reads only seed data and fixtures, no DB, no owner row.
"""

from __future__ import annotations

import typer

from winnow_api.config import get_settings
from winnow_api.eval import run_eval
from winnow_api.eval.report_writer import write_all


def eval_cmd(
    threshold: float = typer.Option(0.75, "--threshold", "-t", help="Tiered routing threshold."),
    test_fraction: float = typer.Option(0.30, "--test-fraction", help="Held-out fraction."),
    seed: int = typer.Option(42, "--seed", help="Split random seed (reproducibility)."),
) -> None:
    """Run the eval harness and write docs/evals.md + results.json."""
    settings = get_settings()
    report = run_eval(
        fixture_dir=settings.fixture_dir,
        seed_dir=settings.seed_email_dir,
        threshold=threshold,
        test_fraction=test_fraction,
        random_state=seed,
    )
    json_path, md_path = write_all(report)

    typer.secho(
        f"Eval complete — provenance={report.tier_2_provenance}, "
        f"n_test={report.n_test}",
        fg=typer.colors.GREEN,
    )
    for name, m in report.strategies.items():
        typer.echo(
            f"  {name:16s} acc={m['accuracy']:.3f} "
            f"macro_f1={m['macro_f1']:.3f} "
            f"lat={m['mean_latency_ms']:.1f}ms "
            f"cost/1k=${m['cost_per_1000_usd']:.4f} "
            f"escalated={m['escalation_rate']:.1%}"
        )
    typer.echo(f"Wrote {md_path}")
    typer.echo(f"Wrote {json_path}")
