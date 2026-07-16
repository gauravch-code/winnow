"""Synthetic seed email schema.

Seed emails live at ``packages/seed-data/emails/{id}.json`` and are the
sole content source for the public demo. Generated once (deterministically)
by ``packages/seed-data/generate.py`` and committed to the repo.

``ground_truth_lane`` is the "correct" triage answer for that email —
consumed by the eval harness (Step 10) and used as the initial lane
assignment in the demo before the classifier is trained.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal[
    "newsletter",
    "work",
    "personal",
    "receipt",
    "calendar",
    "notification",
    "spam",
]

Lane = Literal["needs_you", "informational", "hidden"]


class SeedEmail(BaseModel):
    """One synthetic email. Deterministically produced from a fixed seed."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^seed_\d{3}$")
    sender_email: str
    sender_name: str | None = None
    sender_domain: str
    recipients: dict[str, list[str]]  # {"to": [...], "cc": [...], "bcc": [...]}
    subject: str
    body_text: str
    snippet: str
    received_at: datetime
    thread_depth: int = Field(ge=1)
    has_unsubscribe: bool
    is_reply: bool
    category: Category
    ground_truth_lane: Lane
