"""Dataset split, pure_llm strategy, report writer, and one full run_eval.

The metrics math is covered fast in test_eval_metrics. Here we cover:
- the split is deterministic + stratified + correctly sized;
- pure_llm reads the fixture lane (no classifier needed);
- the report writer round-trips a hand-built report to valid MD/JSON;
- one end-to-end run_eval against the real corpus + committed fixtures
  (slower — trains a classifier via MiniLM — but proves the pieces fit).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from winnow_api.eval.dataset import load_split
from winnow_api.eval.strategies import pure_llm

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SEED_DIR = _REPO_ROOT / "packages" / "seed-data" / "emails"
_FIXTURE_DIR = _REPO_ROOT / "packages" / "seed-data" / "llm-responses"

_HAS_CORPUS = _SEED_DIR.exists() and any(_SEED_DIR.glob("seed_*.json"))
pytestmark = pytest.mark.skipif(
    not _HAS_CORPUS, reason="synthetic corpus not generated"
)


# --- dataset split --------------------------------------------------------


def test_split_is_deterministic():
    a = load_split(seed_dir=_SEED_DIR, random_state=42)
    b = load_split(seed_dir=_SEED_DIR, random_state=42)
    assert [s.id for s in a.test] == [s.id for s in b.test]


def test_split_sizes_and_disjoint():
    split = load_split(seed_dir=_SEED_DIR, test_fraction=0.30)
    total = len(split.train) + len(split.test)
    assert total == 200
    assert 0.28 <= len(split.test) / total <= 0.32
    train_ids = {s.id for s in split.train}
    test_ids = {s.id for s in split.test}
    assert train_ids.isdisjoint(test_ids)


def test_split_is_stratified():
    """Each lane's share in the test set should track the full corpus."""
    split = load_split(seed_dir=_SEED_DIR, test_fraction=0.30)
    from collections import Counter

    test_counts = Counter(s.ground_truth_lane for s in split.test)
    # All three lanes represented (corpus has 36/124/40 → all non-trivial).
    assert set(test_counts) == {"needs_you", "informational", "hidden"}
    assert all(v > 0 for v in test_counts.values())


# --- pure_llm strategy (no classifier) -----------------------------------


class _FakeFixtureLoader:
    def __init__(self, lanes: dict[str, str]):
        self._lanes = lanes

    def get(self, seed_id: str):
        lane = self._lanes.get(seed_id)
        if lane is None:
            return None
        return SimpleNamespace(
            triage=SimpleNamespace(lane=lane),
            trace=SimpleNamespace(latency_ms_live=1400, cost_usd_at_generation=0.01),
        )


def test_pure_llm_uses_fixture_lane():
    emails = [
        SimpleNamespace(id="seed_001", ground_truth_lane="needs_you", subject="a", body_text="b"),
        SimpleNamespace(id="seed_002", ground_truth_lane="hidden", subject="c", body_text="d"),
    ]
    loader = _FakeFixtureLoader({"seed_001": "needs_you", "seed_002": "hidden"})
    run = pure_llm(loader, emails)  # type: ignore[arg-type]
    assert run.y_pred == ["needs_you", "hidden"]
    assert all(o.tier == 2 for o in run.outcomes)
    assert all(o.cost_usd == 0.01 for o in run.outcomes)


def test_pure_llm_missing_fixture_flagged():
    emails = [SimpleNamespace(id="seed_x", ground_truth_lane="hidden", subject="a", body_text="b")]
    loader = _FakeFixtureLoader({})  # no fixture
    run = pure_llm(loader, emails)  # type: ignore[arg-type]
    assert run.outcomes[0].had_fixture is False
    assert run.outcomes[0].cost_usd == 0.0


# --- report writer round-trip --------------------------------------------


def test_report_writer_produces_valid_outputs(tmp_path: Path):
    from winnow_api.eval.harness import EvalReport
    from winnow_api.eval import report_writer

    report = EvalReport(
        generated_at="2026-07-18T00:00:00+00:00",
        n_train=140,
        n_test=60,
        seed=42,
        test_fraction=0.30,
        threshold=0.75,
        tier_2_provenance="stub",
        strategies={
            "pure_classifier": {
                "name": "pure_classifier", "n": 60, "accuracy": 1.0, "macro_f1": 1.0,
                "per_lane": {
                    "needs_you": {"precision": 1.0, "recall": 1.0, "f1": 1.0, "support": 11},
                    "informational": {"precision": 1.0, "recall": 1.0, "f1": 1.0, "support": 37},
                    "hidden": {"precision": 1.0, "recall": 1.0, "f1": 1.0, "support": 12},
                },
                "mean_latency_ms": 5.0, "p95_latency_ms": 5.0,
                "cost_per_1000_usd": 0.0, "escalation_rate": 0.0, "n_missing_fixture": 0,
            },
            "pure_llm": {
                "name": "pure_llm", "n": 60, "accuracy": 1.0, "macro_f1": 1.0,
                "per_lane": {
                    "needs_you": {"precision": 1.0, "recall": 1.0, "f1": 1.0, "support": 11},
                    "informational": {"precision": 1.0, "recall": 1.0, "f1": 1.0, "support": 37},
                    "hidden": {"precision": 1.0, "recall": 1.0, "f1": 1.0, "support": 12},
                },
                "mean_latency_ms": 1200.0, "p95_latency_ms": 1200.0,
                "cost_per_1000_usd": 5.3, "escalation_rate": 1.0, "n_missing_fixture": 0,
            },
            "tiered": {
                "name": "tiered", "n": 60, "accuracy": 1.0, "macro_f1": 1.0,
                "per_lane": {
                    "needs_you": {"precision": 1.0, "recall": 1.0, "f1": 1.0, "support": 11},
                    "informational": {"precision": 1.0, "recall": 1.0, "f1": 1.0, "support": 37},
                    "hidden": {"precision": 1.0, "recall": 1.0, "f1": 1.0, "support": 12},
                },
                "mean_latency_ms": 5.5, "p95_latency_ms": 5.5,
                "cost_per_1000_usd": 0.0, "escalation_rate": 0.0, "n_missing_fixture": 0,
            },
        },
        threshold_sweep=[
            {"threshold": 0.75, "escalation_rate": 0.0, "accuracy": 1.0, "macro_f1": 1.0,
             "cost_per_1000_usd": 0.0, "mean_latency_ms": 5.0},
        ],
        notes=["a note"],
    )
    json_path = tmp_path / "results.json"
    md_path = tmp_path / "evals.md"
    report_writer.write_results_json(report, json_path)
    report_writer.write_markdown(report, md_path)

    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["tier_2_provenance"] == "stub"
    assert set(loaded["strategies"]) == {"pure_classifier", "pure_llm", "tiered"}

    md = md_path.read_text(encoding="utf-8")
    assert "Tier-2 is stubbed" in md  # caveat banner rendered for stub runs
    assert "## Threshold selection" in md  # anchor cited by config.py comment


# --- full run_eval integration (slower) ----------------------------------


@pytest.mark.skipif(
    not (_FIXTURE_DIR.exists() and any(_FIXTURE_DIR.glob("*.json"))),
    reason="fixtures not generated",
)
def test_run_eval_end_to_end():
    from winnow_api.eval import run_eval

    report = run_eval(
        seed_dir=_SEED_DIR,
        fixture_dir=_FIXTURE_DIR,
        threshold=0.75,
        test_fraction=0.30,
        random_state=42,
    )
    assert set(report.strategies) == {"pure_classifier", "pure_llm", "tiered"}
    assert report.n_test + report.n_train == 200
    # Classifier accuracy is a real measured fraction.
    acc = report.strategies["pure_classifier"]["accuracy"]
    assert 0.0 <= acc <= 1.0
    # Pure-LLM always escalates; pure-classifier never does.
    assert report.strategies["pure_llm"]["escalation_rate"] == 1.0
    assert report.strategies["pure_classifier"]["escalation_rate"] == 0.0
    # Committed fixtures are stubs today.
    assert report.tier_2_provenance in {"stub", "live"}
    assert len(report.threshold_sweep) >= 3
