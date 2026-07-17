"""Pub/Sub envelope decoding.

JWT signature verification would require Google's public keys and a
real Google-signed token; that path is exercised only against staging.
What we can and do test locally: the envelope decode contract.
"""

from __future__ import annotations

import base64
import json
import os

import pytest

if os.environ.get("WINNOW_MODE", "demo") != "real":
    pytest.skip(
        "winnow_api.gmail is real-mode only; set WINNOW_MODE=real to run.",
        allow_module_level=True,
    )

from winnow_api.gmail.pubsub import decode_pubsub_envelope


def _envelope(inner: dict) -> dict:
    data_b64 = base64.b64encode(json.dumps(inner).encode("utf-8")).decode("ascii")
    return {"message": {"data": data_b64, "messageId": "m-1"}, "subscription": "sub"}


def test_decode_extracts_history_id_and_email():
    inner = {"emailAddress": "me@example.com", "historyId": "H-42"}
    decoded = decode_pubsub_envelope(_envelope(inner))
    assert decoded == inner


def test_decode_missing_data_raises():
    with pytest.raises(ValueError, match="envelope missing"):
        decode_pubsub_envelope({"message": {}, "subscription": "sub"})


def test_decode_no_message_raises():
    with pytest.raises(ValueError):
        decode_pubsub_envelope({"subscription": "sub"})
