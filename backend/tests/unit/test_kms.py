"""Unit tests for local AES-256-GCM KMS utility."""
import os
import base64

import pytest

# Use a fixed test key so tests are deterministic
_TEST_KEY = base64.b64encode(os.urandom(32)).decode()


@pytest.fixture(autouse=True)
def patch_kms_settings(monkeypatch):
    monkeypatch.setenv("KMS_MODE", "local")
    monkeypatch.setenv("LOCAL_ENCRYPT_KEY", _TEST_KEY)
    # Re-import settings so env vars take effect
    import importlib
    import app.config as cfg_mod
    importlib.reload(cfg_mod)
    import app.utils.kms as kms_mod
    importlib.reload(kms_mod)
    return kms_mod


def test_encrypt_decrypt_roundtrip(patch_kms_settings):
    kms = patch_kms_settings
    plaintext = b"super secret refresh token"
    ciphertext = kms.encrypt(plaintext)
    recovered = kms.decrypt(ciphertext)
    assert recovered == plaintext


def test_different_ciphertext(patch_kms_settings):
    kms = patch_kms_settings
    plaintext = b"same plaintext"
    ct1 = kms.encrypt(plaintext)
    ct2 = kms.encrypt(plaintext)
    # AES-GCM uses random 12-byte nonce, so ciphertexts must differ
    assert ct1 != ct2
    # But both decrypt to the same value
    assert kms.decrypt(ct1) == plaintext
    assert kms.decrypt(ct2) == plaintext
