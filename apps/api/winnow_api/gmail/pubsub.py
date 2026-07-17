"""Pub/Sub push webhook verification.

Google-signed JWTs arrive in the ``Authorization: Bearer <jwt>`` header
on every push. We verify the signature against Google's public keys
and check the audience matches ``WINNOW_PUBSUB_AUDIENCE`` — set to the
webhook URL when the Pub/Sub subscription is created.

Skipping this verification would let anyone POST to /gmail/webhook
and trigger sync work (or, worse, spoof a historyId that induces a
back-in-time re-scan).
"""

from __future__ import annotations

import base64
import json

import structlog
from google.auth.transport import requests as ga_requests
from google.oauth2 import id_token

log = structlog.get_logger(__name__)


class InvalidPubSubToken(RuntimeError):
    """JWT invalid, expired, or audience mismatch."""


def verify_pubsub_jwt(bearer_token: str, expected_audience: str) -> dict:
    """Verify a Pub/Sub push JWT and return the decoded claims.

    Raises ``InvalidPubSubToken`` on any verification failure.
    """
    try:
        claims = id_token.verify_oauth2_token(
            bearer_token, ga_requests.Request(), audience=expected_audience
        )
    except ValueError as exc:
        raise InvalidPubSubToken(str(exc)) from exc
    # Google-issued tokens have issuer accounts.google.com or https://accounts.google.com;
    # verify_oauth2_token already checks this, but assert explicitly for defense in depth.
    iss = claims.get("iss", "")
    if iss not in ("accounts.google.com", "https://accounts.google.com"):
        raise InvalidPubSubToken(f"Unexpected issuer {iss!r}")
    return claims


def decode_pubsub_envelope(body: dict) -> dict:
    """Pull the Gmail notification payload out of a Pub/Sub push envelope.

    Pub/Sub sends:
        {"message": {"data": "<base64 of JSON>", "messageId": "...", ...},
         "subscription": "..."}
    The inner JSON has {"emailAddress": ..., "historyId": "..."}.
    """
    msg = body.get("message") or {}
    data_b64 = msg.get("data")
    if not data_b64:
        raise ValueError("Pub/Sub envelope missing message.data")
    decoded = base64.b64decode(data_b64.encode("ascii")).decode("utf-8")
    return json.loads(decoded)
