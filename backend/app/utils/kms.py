"""Encryption utility — local AES-256-GCM (dev) or GCP KMS (prod)."""
import base64
import os
from app.config import settings


def _get_local_key() -> bytes:
    key_b64 = settings.LOCAL_ENCRYPT_KEY
    if not key_b64:
        # Generate an ephemeral key when not configured — only suitable for tests
        return os.urandom(32)
    return base64.b64decode(key_b64)


def encrypt(plaintext: bytes) -> bytes:
    if settings.KMS_MODE == "gcp":
        return _gcp_encrypt(plaintext)
    return _local_encrypt(plaintext)


def decrypt(ciphertext: bytes) -> bytes:
    if settings.KMS_MODE == "gcp":
        return _gcp_decrypt(ciphertext)
    return _local_decrypt(ciphertext)


def _local_encrypt(plaintext: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _get_local_key()
    nonce = os.urandom(12)  # 96-bit nonce, random per encrypt call
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ct  # prepend nonce so decrypt can recover it


def _local_decrypt(ciphertext: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _get_local_key()
    nonce = ciphertext[:12]
    ct = ciphertext[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None)


def _gcp_encrypt(plaintext: bytes) -> bytes:
    from google.cloud import kms
    client = kms.KeyManagementServiceClient()
    response = client.encrypt(
        request={"name": settings.KMS_KEY_NAME, "plaintext": plaintext}
    )
    return response.ciphertext


def _gcp_decrypt(ciphertext: bytes) -> bytes:
    from google.cloud import kms
    client = kms.KeyManagementServiceClient()
    response = client.decrypt(
        request={"name": settings.KMS_KEY_NAME, "ciphertext": ciphertext}
    )
    return response.plaintext
