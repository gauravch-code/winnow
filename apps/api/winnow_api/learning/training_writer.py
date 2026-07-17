"""Write a TrainingExample from an Email + resolved (label, label_source).

Called on the request path when a user's action turns into a labeled
example (see winnow_api.demo.routes and, in real mode, the ingestion
handlers in Step 11 polish). Kept as a plain function rather than a
service class because there's exactly one call site per action type
and the arguments are simple.

Cached feature vector + embedding are stored so the retrainer doesn't
have to re-embed every historical example (embedding a bunch of old
messages nightly would push MiniLM to be the bottleneck).
"""

from __future__ import annotations

import uuid

import numpy as np
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from winnow_api.classifier.embeddings import embed_one
from winnow_api.classifier.features import extract_features
from winnow_api.db.models import Email, TrainingExample

log = structlog.get_logger(__name__)


def write_training_example(
    db: Session,
    email: Email,
    *,
    label: str,
    label_source: str,
    user_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
) -> TrainingExample | None:
    """Insert (or update if a stronger signal supersedes) a training example.

    Idempotency policy: one training row per (email, scope). If an
    example already exists for this email in this user/session, the
    later action's label wins — that matches how a user's mental model
    works ("my most recent action is what I meant"). ``label_source``
    is updated too, so the retrainer can weight by source later.
    """
    if (user_id is None) == (session_id is None):
        raise ValueError("Exactly one of user_id / session_id must be set.")

    features = extract_features(email)
    embedding = embed_one(email.subject, email.body_text)
    emb_bytes = np.asarray(embedding, dtype=np.float32).tobytes()

    existing = db.execute(
        select(TrainingExample).where(
            TrainingExample.email_id == email.id,
            TrainingExample.user_id == user_id,
            TrainingExample.session_id == session_id,
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.label = label
        existing.label_source = label_source
        existing.features = features
        existing.embedding = emb_bytes
        existing.embedding_dim = int(embedding.shape[0])
        existing.embedding_dtype = "float32"
        log.debug(
            "training_example_updated",
            email_id=str(email.id),
            label=label,
            source=label_source,
        )
        return existing

    row = TrainingExample(
        email_id=email.id,
        user_id=user_id,
        session_id=session_id,
        label=label,
        label_source=label_source,
        features=features,
        embedding=emb_bytes,
        embedding_dim=int(embedding.shape[0]),
        embedding_dtype="float32",
    )
    db.add(row)
    log.debug(
        "training_example_written",
        email_id=str(email.id),
        label=label,
        source=label_source,
    )
    return row
