"""Regression tests for _prep_text — the real-Gmail crash of 2026-07-19.

A truthy-but-whitespace body (HTML-only mail, empty text/plain parts)
strips to "" and .splitlines() returns [], so [0] raised IndexError and
took down the whole sync. These lock the guard. Pure — no model load.
"""

from __future__ import annotations

import pytest

from winnow_api.classifier.embeddings import _prep_text


@pytest.mark.parametrize(
    "subject, body",
    [
        ("hi", ""),            # empty body
        ("hi", "   "),         # spaces only
        ("hi", "\n\n\t "),     # newlines/whitespace only
        ("hi", None),          # missing body
        ("", ""),              # both empty
        (None, None),          # both missing
    ],
)
def test_prep_text_survives_empty_bodies(subject, body):
    out = _prep_text(subject, body)  # must not raise
    assert isinstance(out, str)


def test_prep_text_uses_first_nonempty_line():
    out = _prep_text("Subject", "first line\nsecond line")
    assert "first line" in out
    assert "second line" not in out


def test_prep_text_truncates_long_first_line():
    out = _prep_text("s", "x" * 500)
    # subject + newline + 280 chars max
    assert len(out) <= len("s") + 1 + 280
