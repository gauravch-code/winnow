from pathlib import Path

from winnow_api.classifier.features import ENGINEERED_FEATURE_NAMES, extract_features
from winnow_api.classifier.inference import Classifier, ClassifierResult, TopFeature


def default_artifact_path() -> Path:
    """Path to the shipped baseline model. Single source of truth so the
    API, the CLI sync, and training all agree on where the model lives."""
    return Path(__file__).resolve().parent / "artifacts" / "base.joblib"


def load_baseline(version_label: str = "base-0.1") -> Classifier | None:
    """Load the baseline classifier, or None if it hasn't been trained yet."""
    path = default_artifact_path()
    return Classifier.load(path, version_label=version_label) if path.exists() else None


__all__ = [
    "Classifier",
    "ClassifierResult",
    "ENGINEERED_FEATURE_NAMES",
    "TopFeature",
    "default_artifact_path",
    "extract_features",
    "load_baseline",
]
