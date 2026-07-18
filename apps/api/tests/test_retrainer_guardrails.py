"""Retrainer guardrail tests.

Locks the guardrails that are supposed to keep bad models out of
production, using tiny training sets that don't need MiniLM embeddings.
The retrainer's ``_seed_matrix`` normally re-embeds the whole seed
corpus (200 emails × MiniLM), so we monkeypatch it to a fake instead.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy.orm import Session

from winnow_api.db.models import ClassifierMetric, Email, TrainingExample, User
from winnow_api.learning import artifacts as artifacts_module
from winnow_api.learning import retrainer as retrainer_module
from winnow_api.learning.retrainer import RetrainOutcome, Retrainer


# --- fixtures -------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Per-test artifact dir so previous runs don't affect regression checks."""
    monkeypatch.setattr(artifacts_module, "ARTIFACT_PATH", tmp_path / "base.joblib")
    monkeypatch.setattr(
        artifacts_module, "PREVIOUS_ARTIFACT_PATH", tmp_path / "base.previous.joblib"
    )
    # retrainer imports ARTIFACT_PATH by name — patch there too.
    monkeypatch.setattr(retrainer_module, "ARTIFACT_PATH", tmp_path / "base.joblib")


@pytest.fixture(autouse=True)
def _fake_seed_matrix(monkeypatch: pytest.MonkeyPatch):
    """Skip loading 200 seed emails + MiniLM embedding pass.

    Each test that needs seed data provides its own via ``_seeds_arg``.
    """
    # 18 engineered + 384 embedding = 402. Column count must match the
    # user matrix or np.vstack refuses to concat, even at 0 rows.
    empty = (np.zeros((0, 402), dtype=np.float32), np.asarray([], dtype=object))
    monkeypatch.setattr(retrainer_module, "_load_seed_rows", lambda _dir: [])
    monkeypatch.setattr(retrainer_module, "_seed_matrix", lambda _seeds: empty)


@pytest.fixture
def owner(db: Session):
    db.query(TrainingExample).delete()
    db.query(Email).delete()
    db.query(ClassifierMetric).delete()
    db.query(User).delete()
    db.commit()
    u = User(email=f"me-{uuid.uuid4()}@example.com")
    db.add(u)
    db.commit()
    yield u
    db.query(ClassifierMetric).delete()
    db.query(TrainingExample).delete()
    db.query(Email).delete()
    db.query(User).delete()
    db.commit()


def _mint_examples(db: Session, user: User, labels: list[str]) -> list[TrainingExample]:
    """Insert Email + TrainingExample rows for the given labels."""
    rows = []
    for i, label in enumerate(labels):
        email = Email(
            user_id=user.id,
            sender_email=f"s{i}@example.com",
            sender_domain="example.com",
            recipients={"to": ["me@example.com"], "cc": [], "bcc": []},
            subject=f"subj {i}",
            body_text=f"body {i}",
            received_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
            thread_depth=1,
            has_unsubscribe=False,
            is_reply=False,
        )
        db.add(email)
        db.flush()
        emb = np.random.default_rng(seed=i).random(384, dtype=np.float32)
        example = TrainingExample(
            email_id=email.id,
            user_id=user.id,
            label=label,
            label_source="user_move",
            features={
                name: float(np.random.default_rng(seed=i + 100).random())
                for name in [
                    "has_unsubscribe", "is_reply", "thread_depth_capped",
                    "log_subject_length", "log_body_length",
                    "subject_question_marks", "body_question_marks",
                    "urgency_word_count", "sender_is_notification_domain",
                    "sender_is_receipt_domain", "sender_is_personal_domain",
                    "sender_is_suspicious_tld", "recipient_count", "cc_count",
                    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
                ]
            },
            embedding=emb.tobytes(),
            embedding_dim=384,
            embedding_dtype="float32",
        )
        db.add(example)
        rows.append(example)
    db.commit()
    return rows


# --- guardrail tests ------------------------------------------------------


def test_skips_when_below_min_examples(db: Session, owner: User, tmp_path: Path):
    _mint_examples(db, owner, ["needs_you"] * 10)  # < 20

    report = Retrainer(
        db=db, user=owner, seed_dir=tmp_path, min_examples=20
    ).run()

    assert report.outcome is RetrainOutcome.REJECTED_INSUFFICIENT_EXAMPLES
    assert "at least 20" in report.rejection_reason

    # A metrics row is still written for auditability.
    saved = db.query(ClassifierMetric).filter(ClassifierMetric.user_id == owner.id).one()
    assert saved.deployed is False
    assert not (tmp_path / "base.joblib").exists()  # never wrote an artifact


def test_skips_when_only_one_class_present(db: Session, owner: User, tmp_path: Path):
    _mint_examples(db, owner, ["needs_you"] * 25)

    report = Retrainer(
        db=db, user=owner, seed_dir=tmp_path, min_examples=20
    ).run()

    assert report.outcome is RetrainOutcome.REJECTED_INSUFFICIENT_CLASSES
    assert "at least 2" in report.rejection_reason


def test_first_ever_retrain_deploys_without_regression_check(
    db: Session, owner: User, tmp_path: Path
):
    """No active model → previous_active_accuracy is None → no gate to pass."""
    labels = ["needs_you"] * 15 + ["informational"] * 10 + ["hidden"] * 10
    _mint_examples(db, owner, labels)

    report = Retrainer(
        db=db, user=owner, seed_dir=tmp_path, min_examples=20
    ).run()

    assert report.outcome is RetrainOutcome.DEPLOYED
    assert report.previous_active_accuracy is None
    assert (tmp_path / "base.joblib").exists()

    saved = db.query(ClassifierMetric).filter(ClassifierMetric.user_id == owner.id).one()
    assert saved.deployed is True
    assert saved.holdout_accuracy == pytest.approx(report.holdout_accuracy)


def test_metrics_row_written_even_on_rejection(db: Session, owner: User, tmp_path: Path):
    """Auditability: every retrain attempt is a durable row, deployed or not."""
    _mint_examples(db, owner, ["needs_you"] * 5)

    Retrainer(db=db, user=owner, seed_dir=tmp_path, min_examples=20).run()

    row = db.query(ClassifierMetric).filter(ClassifierMetric.user_id == owner.id).one()
    assert row.deployed is False
    assert row.rejection_reason is not None
    assert row.n_training_examples == 5
