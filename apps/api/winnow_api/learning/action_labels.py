"""Action → training-label mapping.

All 7 action types listed in the schema are handled here. Not every
action becomes a training example — ``marked_read`` and
``draft_discarded`` produce ambiguous signal, so we deliberately drop
them rather than pollute the training set with weak labels that will
confuse the classifier over time.

Signal strength decisions (justified so a future reader can revisit):

- ``lane_moved`` — the user's explicit correction. Strongest possible
  signal. Label = to_lane.
- ``archived`` — the user wants this out of the inbox. Strong hidden
  signal.
- ``starred`` — deliberate "this matters." Strong needs_you signal.
- ``snoozed`` — the user thought "I'll deal with this later." That's
  a needs_you signal (they didn't archive it).
- ``draft_edited`` — the user engaged enough to compose a reply. Strong
  needs_you signal.
- ``draft_discarded`` — ambiguous. Could mean the email tricked them
  into engaging, or they'll reply later, or they abandoned mid-thought.
  Skip.
- ``marked_read`` — everyone reads everything. Not a lane signal. Skip.

If we ever decide draft_discarded is worth a hidden label, add it here
and evals will show whether it helps or hurts.
"""

from __future__ import annotations

from typing import Any

# action_type → (label_source, label_getter). label_getter is a callable
# so ``lane_moved`` can read to_lane off the action row; other actions
# are static.

_MOVE_LABEL: Any = "USE_TO_LANE"


ACTION_TO_LABEL_SOURCE: dict[str, str] = {
    "lane_moved": "user_move",
    "archived": "user_archive",
    "starred": "user_star",
    "draft_edited": "user_draft_edit",
    "snoozed": "user_snooze",
}

# Static labels for the actions where the label is implied by the
# action itself, not the row's fields.
_STATIC_LABELS: dict[str, str] = {
    "archived": "hidden",
    "starred": "needs_you",
    "draft_edited": "needs_you",
    "snoozed": "needs_you",
}


def label_from_action(action_type: str, to_lane: str | None) -> tuple[str, str] | None:
    """Return (label, label_source) or None if the action carries no signal.

    ``to_lane`` is only consulted for ``lane_moved`` (where it's the
    label). Passing it for other actions is harmless.
    """
    if action_type not in ACTION_TO_LABEL_SOURCE:
        # marked_read, draft_discarded, or an unknown action → skip.
        return None
    source = ACTION_TO_LABEL_SOURCE[action_type]
    if action_type == "lane_moved":
        if not to_lane:
            # Malformed lane_moved with no target — skip rather than crash.
            return None
        return to_lane, source
    return _STATIC_LABELS[action_type], source
