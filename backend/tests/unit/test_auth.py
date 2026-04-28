"""Unit tests for JWT token utilities."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.utils.jwt_utils import (
    ACCESS_TOKEN_EXPIRE,
    REFRESH_TOKEN_EXPIRE,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.config import settings

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"


def test_create_access_token():
    token = create_access_token(TEST_USER_ID)
    payload = decode_token(token)
    assert payload["sub"] == TEST_USER_ID
    assert payload["type"] == "access"
    exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    assert exp > datetime.now(timezone.utc)
    assert exp <= datetime.now(timezone.utc) + ACCESS_TOKEN_EXPIRE + timedelta(seconds=5)


def test_create_refresh_token():
    token = create_refresh_token(TEST_USER_ID)
    payload = decode_token(token)
    assert payload["sub"] == TEST_USER_ID
    assert payload["type"] == "refresh"
    exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    assert exp > datetime.now(timezone.utc)
    assert exp <= datetime.now(timezone.utc) + REFRESH_TOKEN_EXPIRE + timedelta(seconds=5)


def test_decode_expired_token():
    payload = {
        "sub": TEST_USER_ID,
        "type": "access",
        "iat": datetime.now(timezone.utc) - timedelta(hours=2),
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(token)


def test_token_type_check():
    refresh = create_refresh_token(TEST_USER_ID)
    payload = decode_token(refresh)
    # Simulates the check in get_current_user / refresh endpoint
    assert payload["type"] != "access"
