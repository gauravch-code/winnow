"""MiniLM embedding wrapper.

Singleton so the ~90MB model is loaded once per process. Encoding is
CPU-bound but fast — on a modest laptop, ~1000 subjects/sec at batch
size 32. That's well inside the tier-1 latency budget.

The embedded text is subject + first-line snippet, not the full body.
Rationale: subjects and openers carry most of the semantic signal for
lane routing (a newsletter looks like a newsletter in its subject; a
direct ask looks like an ask in its opener), and long bodies would
smear the embedding toward generic English. Truncation at model max
tokens would also drop critical late-body signal for long threads,
which nobody wants to reason about.
"""

from __future__ import annotations

import threading
from typing import Iterable

import numpy as np

_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_EMBEDDING_DIM = 384

_model = None
_model_lock = threading.Lock()


def get_model():
    """Lazy singleton. Loads MiniLM on first call, ~1-2s cold."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(_MODEL_NAME)
    return _model


def embedding_dim() -> int:
    return _EMBEDDING_DIM


def _prep_text(subject: str, body: str) -> str:
    subject = (subject or "").strip()
    first_line = (body or "").strip().splitlines()[0] if body else ""
    return f"{subject}\n{first_line[:280]}"


def embed_batch(texts: Iterable[tuple[str, str]]) -> np.ndarray:
    """Encode a batch of (subject, body) pairs. Returns (N, 384) float32."""
    prepared = [_prep_text(s, b) for s, b in texts]
    if not prepared:
        return np.zeros((0, _EMBEDDING_DIM), dtype=np.float32)
    model = get_model()
    vectors = model.encode(prepared, batch_size=32, show_progress_bar=False)
    return np.asarray(vectors, dtype=np.float32)


def embed_one(subject: str, body: str) -> np.ndarray:
    """Encode a single email. Returns (384,) float32."""
    return embed_batch([(subject, body)])[0]
