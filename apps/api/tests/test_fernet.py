"""Fernet encryption helper tests.

Fernet itself is well-tested by the ``cryptography`` library; these
tests lock our wrapper's error contract so callers can rely on typed
exceptions instead of catching library internals.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from winnow_api.config import get_settings
from winnow_api.security import EncryptionKeyMissing, InvalidCiphertext, decrypt, encrypt


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch):
    """Generate a fresh key per test and force it into the cached settings."""
    key = Fernet.generate_key().decode("ascii")
    settings = get_settings()
    monkeypatch.setattr(settings, "encryption_key", key)
    yield
    # lru_cache holds the Settings instance across tests; setattr on it is
    # reverted by monkeypatch on teardown so the next test starts clean.


def test_roundtrip_ascii():
    plaintext = "1//06oauth-refresh-token-example"
    assert decrypt(encrypt(plaintext)) == plaintext


def test_roundtrip_unicode():
    """Refresh tokens are ASCII in practice; we still don't want to lose bytes."""
    plaintext = "hello — world 世界 🚀"
    assert decrypt(encrypt(plaintext)) == plaintext


def test_ciphertext_is_url_safe_ascii():
    """Fernet tokens are URL-safe base64. We need this to be TEXT-column safe."""
    ct = encrypt("x")
    assert ct.isascii()
    assert all(c.isalnum() or c in "-_=." for c in ct)


def test_tampered_ciphertext_raises_our_exception():
    ct = encrypt("secret")
    # Flip one byte in the payload region.
    mutated = ct[:-5] + ("A" if ct[-5] != "A" else "B") + ct[-4:]
    with pytest.raises(InvalidCiphertext, match="different key"):
        decrypt(mutated)


def test_wrong_key_raises_our_exception(monkeypatch: pytest.MonkeyPatch):
    ct = encrypt("secret")
    # Rotate the key without re-encrypting.
    new_key = Fernet.generate_key().decode("ascii")
    settings = get_settings()
    monkeypatch.setattr(settings, "encryption_key", new_key)
    with pytest.raises(InvalidCiphertext):
        decrypt(ct)


def test_missing_key_raises_typed_error(monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "encryption_key", None)
    with pytest.raises(EncryptionKeyMissing, match="WINNOW_ENCRYPTION_KEY"):
        encrypt("x")
