"""Action → training-label mapping tests.

Every one of the 7 action_types listed in the schema is exercised so
that a future weak-signal reclassification is caught by a red test
rather than shipping to production quietly. If we ever decide
``draft_discarded`` or ``marked_read`` DOES carry lane signal, these
tests are where the change is anchored.
"""

from __future__ import annotations

import pytest

from winnow_api.learning.action_labels import (
    ACTION_TO_LABEL_SOURCE,
    label_from_action,
)


def test_lane_moved_uses_to_lane():
    assert label_from_action("lane_moved", "hidden") == ("hidden", "user_move")
    assert label_from_action("lane_moved", "needs_you") == ("needs_you", "user_move")
    assert label_from_action("lane_moved", "informational") == ("informational", "user_move")


def test_lane_moved_without_to_lane_is_skipped():
    """A lane_moved row with no to_lane is malformed — don't crash, just skip."""
    assert label_from_action("lane_moved", None) is None


def test_archived_implies_hidden():
    assert label_from_action("archived", None) == ("hidden", "user_archive")


def test_starred_implies_needs_you():
    assert label_from_action("starred", None) == ("needs_you", "user_star")


def test_draft_edited_implies_needs_you():
    assert label_from_action("draft_edited", None) == ("needs_you", "user_draft_edit")


def test_snoozed_implies_needs_you():
    """User deferred — they still wanted to see it, just later."""
    assert label_from_action("snoozed", None) == ("needs_you", "user_snooze")


@pytest.mark.parametrize("weak_action", ["marked_read", "draft_discarded"])
def test_weak_signal_actions_return_none(weak_action: str):
    """Deliberately dropped — see action_labels.py docstring for rationale.

    If someone ever decides these carry signal, they'll edit
    ACTION_TO_LABEL_SOURCE, and this test will fail loudly enough to
    force a rationale in the commit message.
    """
    assert label_from_action(weak_action, None) is None
    assert label_from_action(weak_action, "needs_you") is None  # to_lane ignored


def test_unknown_action_returns_none():
    assert label_from_action("nonsense", None) is None


def test_action_source_map_is_complete_for_labeled_actions():
    """Every action that COULD produce a training row must have a label_source."""
    for action, source in ACTION_TO_LABEL_SOURCE.items():
        # Contract: the resolver returns (label, source) with matching source.
        resolved = label_from_action(
            action, "needs_you" if action == "lane_moved" else None
        )
        assert resolved is not None, f"{action} declared but resolver skipped it"
        assert resolved[1] == source, f"{action} source mismatch: {resolved[1]} vs {source}"
