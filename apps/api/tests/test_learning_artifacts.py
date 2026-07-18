"""Artifact rotation + rollback tests.

Locks the two behaviors that matter to the guardrail story: the current
artifact is never lost mid-rotation, and rollback is a symmetric
operation that a caller can invoke twice to get back where they started.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import joblib
import pytest

from winnow_api.learning import artifacts


@pytest.fixture(autouse=True)
def _redirect_artifact_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the module's paths at a temp directory per test."""
    monkeypatch.setattr(artifacts, "ARTIFACT_PATH", tmp_path / "base.joblib")
    monkeypatch.setattr(artifacts, "PREVIOUS_ARTIFACT_PATH", tmp_path / "base.previous.joblib")
    yield


class _FakeModel:
    """Minimal object that ``save`` writes as joblib. Passes for TrainedModel.

    ``trained_at_iso`` is required by save_new_active's log line even
    though the artifact-rotation code doesn't otherwise consume it.
    """

    def __init__(self, tag: str):
        self.tag = tag
        self.trained_at_iso = f"iso-{tag}"

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)


def _load_tag(path: Path) -> str:
    return joblib.load(path).tag


def test_first_save_writes_current_without_previous():
    artifacts.save_new_active(_FakeModel("v1"))  # type: ignore[arg-type]
    assert artifacts.ARTIFACT_PATH.exists()
    assert not artifacts.PREVIOUS_ARTIFACT_PATH.exists()
    assert _load_tag(artifacts.ARTIFACT_PATH) == "v1"


def test_second_save_rotates_previous():
    artifacts.save_new_active(_FakeModel("v1"))  # type: ignore[arg-type]
    artifacts.save_new_active(_FakeModel("v2"))  # type: ignore[arg-type]

    assert _load_tag(artifacts.ARTIFACT_PATH) == "v2"
    assert _load_tag(artifacts.PREVIOUS_ARTIFACT_PATH) == "v1"


def test_third_save_drops_oldest():
    """Only one previous is kept — space is not free on hosted platforms."""
    artifacts.save_new_active(_FakeModel("v1"))  # type: ignore[arg-type]
    artifacts.save_new_active(_FakeModel("v2"))  # type: ignore[arg-type]
    artifacts.save_new_active(_FakeModel("v3"))  # type: ignore[arg-type]

    assert _load_tag(artifacts.ARTIFACT_PATH) == "v3"
    assert _load_tag(artifacts.PREVIOUS_ARTIFACT_PATH) == "v2"


def test_rollback_swaps_current_and_previous():
    artifacts.save_new_active(_FakeModel("v1"))  # type: ignore[arg-type]
    artifacts.save_new_active(_FakeModel("v2"))  # type: ignore[arg-type]

    assert artifacts.rollback_to_previous() is True
    assert _load_tag(artifacts.ARTIFACT_PATH) == "v1"
    assert _load_tag(artifacts.PREVIOUS_ARTIFACT_PATH) == "v2"


def test_rollback_twice_returns_to_original_state():
    """Second rollback should undo the first — no data lost either way."""
    artifacts.save_new_active(_FakeModel("v1"))  # type: ignore[arg-type]
    artifacts.save_new_active(_FakeModel("v2"))  # type: ignore[arg-type]

    artifacts.rollback_to_previous()  # v1 active, v2 previous
    artifacts.rollback_to_previous()  # v2 active, v1 previous again

    assert _load_tag(artifacts.ARTIFACT_PATH) == "v2"
    assert _load_tag(artifacts.PREVIOUS_ARTIFACT_PATH) == "v1"


def test_rollback_without_previous_returns_false():
    """No previous, no exception — caller decides how to surface it."""
    assert artifacts.rollback_to_previous() is False
