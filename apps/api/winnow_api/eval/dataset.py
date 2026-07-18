"""Held-out dataset split for the eval harness.

Deterministic stratified split of the 200 seed emails. We train a fresh
classifier on the train half and evaluate every strategy on the test
half — evaluating on the shipped model's own training data would inflate
the classifier's numbers and make the comparison dishonest.

The split is seeded so the published numbers are reproducible: anyone
who runs `winnow eval` gets the same test set and the same figures.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sklearn.model_selection import train_test_split

from winnow_seed_data.seed_email_schema import SeedEmail

# eval/dataset.py → winnow_api → api → apps → <repo root> is parents[4].
DEFAULT_SEED_DIR = (
    Path(__file__).resolve().parents[4] / "packages" / "seed-data" / "emails"
)


@dataclass
class EvalSplit:
    train: list[SeedEmail]
    test: list[SeedEmail]
    seed: int
    test_fraction: float


def _load_seeds(seed_dir: Path) -> list[SeedEmail]:
    return [
        SeedEmail.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(seed_dir.glob("seed_*.json"))
    ]


def load_split(
    seed_dir: Path | None = None,
    test_fraction: float = 0.30,
    random_state: int = 42,
) -> EvalSplit:
    """Return a stratified train/test split of the seed corpus.

    Stratified on ``ground_truth_lane`` so the test set preserves the
    corpus lane distribution — otherwise a random split could leave a
    minority lane barely represented and make per-lane recall noisy.
    """
    seeds = _load_seeds(seed_dir or DEFAULT_SEED_DIR)
    labels = [s.ground_truth_lane for s in seeds]
    train, test = train_test_split(
        seeds,
        test_size=test_fraction,
        stratify=labels,
        random_state=random_state,
    )
    return EvalSplit(
        train=train,
        test=test,
        seed=random_state,
        test_fraction=test_fraction,
    )
