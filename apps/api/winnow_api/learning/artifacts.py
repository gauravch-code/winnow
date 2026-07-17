"""Classifier artifact management: save-new, rotate-previous, rollback.

One current artifact (``base.joblib``) and one rollback slot
(``base.previous.joblib``). No versioned history: disk space is not
free on Fly.io/Railway, and if I ever want more than one rollback
point I can add a versioned directory later.

Rotation is atomic-ish: previous is deleted, current is renamed to
previous, then new is written. A crash mid-rotation loses the previous
model but never the current — because the rename happens before the
new file lands. That's the right failure mode: "we lost a rollback
option" beats "we lost the currently-active model."
"""

from __future__ import annotations

import shutil
from pathlib import Path

import structlog

from winnow_api.classifier.model import TrainedModel

log = structlog.get_logger(__name__)

_ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "classifier" / "artifacts"
ARTIFACT_PATH = _ARTIFACT_DIR / "base.joblib"
PREVIOUS_ARTIFACT_PATH = _ARTIFACT_DIR / "base.previous.joblib"


def save_new_active(model: TrainedModel) -> None:
    """Rotate current → previous, then write ``model`` as the new current.

    If no current model exists yet (first ever retrain), no rotation
    happens — ``base.previous.joblib`` remains absent.
    """
    _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    if ARTIFACT_PATH.exists():
        # Overwrite whatever was in the previous slot — we only keep one.
        if PREVIOUS_ARTIFACT_PATH.exists():
            PREVIOUS_ARTIFACT_PATH.unlink()
        shutil.move(str(ARTIFACT_PATH), str(PREVIOUS_ARTIFACT_PATH))
        log.info("classifier_previous_rotated", path=str(PREVIOUS_ARTIFACT_PATH))

    model.save(ARTIFACT_PATH)
    log.info(
        "classifier_new_active_saved",
        path=str(ARTIFACT_PATH),
        version=model.trained_at_iso,
    )


def rollback_to_previous() -> bool:
    """Swap current with previous. Returns False if there's nothing to roll back to.

    Symmetric with ``save_new_active``: the model that was current
    becomes the new previous, so a caller can rollback twice to end up
    where they started.
    """
    if not PREVIOUS_ARTIFACT_PATH.exists():
        log.warning("classifier_no_previous_to_rollback")
        return False

    # Same atomic-ish dance: rename current out of the way first.
    tmp = ARTIFACT_PATH.with_suffix(".rollback-tmp")
    if ARTIFACT_PATH.exists():
        shutil.move(str(ARTIFACT_PATH), str(tmp))
    shutil.move(str(PREVIOUS_ARTIFACT_PATH), str(ARTIFACT_PATH))
    if tmp.exists():
        shutil.move(str(tmp), str(PREVIOUS_ARTIFACT_PATH))
    log.info("classifier_rolled_back", current=str(ARTIFACT_PATH))
    return True
