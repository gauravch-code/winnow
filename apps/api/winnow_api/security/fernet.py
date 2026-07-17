"""Fernet symmetric encryption for at-rest secrets.

Used for ``users.gmail_refresh_token_encrypted``. Kept deliberately
thin: a plaintext-bytes API around ``cryptography.fernet.Fernet`` with
one call site each for encrypt and decrypt, plus typed exceptions so
callers can distinguish "encryption not configured" from "ciphertext
is garbage".

Key comes from ``WINNOW_ENCRYPTION_KEY`` — read lazily via ``get_settings``
so tests can monkeypatch. Never log the key or the plaintext, and never
accept an empty key silently.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from winnow_api.config import get_settings


class EncryptionKeyMissing(RuntimeError):
    """WINNOW_ENCRYPTION_KEY is not set. Callers should give a helpful message."""


class InvalidCiphertext(RuntimeError):
    """Ciphertext is malformed or was encrypted with a different key."""


def _fernet() -> Fernet:
    key = get_settings().encryption_key
    if not key:
        raise EncryptionKeyMissing(
            "WINNOW_ENCRYPTION_KEY is not set. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode("utf-8") if isinstance(key, str) else key)


def encrypt(plaintext: str) -> str:
    """Encrypt a UTF-8 string. Returns the Fernet token as an ASCII string
    (URL-safe base64), ready to store in a TEXT column."""
    token_bytes = _fernet().encrypt(plaintext.encode("utf-8"))
    return token_bytes.decode("ascii")


def decrypt(token: str) -> str:
    """Reverse of ``encrypt``. Raises ``InvalidCiphertext`` if the token was
    tampered with or encrypted under a different key.

    We deliberately re-raise as our own exception type so callers don't
    have to catch a ``cryptography`` internal exception — otherwise a
    library-internal name change would break the app.
    """
    try:
        plaintext_bytes = _fernet().decrypt(token.encode("ascii"))
    except InvalidToken as exc:
        raise InvalidCiphertext(
            "Refused to decrypt: ciphertext is invalid or was encrypted with a different key. "
            "If you rotated WINNOW_ENCRYPTION_KEY, re-run `winnow gmail authorize`."
        ) from exc
    return plaintext_bytes.decode("utf-8")
