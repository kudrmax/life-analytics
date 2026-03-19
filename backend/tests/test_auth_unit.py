"""
Unit tests for pure functions in app.auth.

No database fixtures — only in-memory bcrypt / JWT logic.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from jose import jwt

from app.auth import (
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)


class TestHashPassword:
    """Tests for hash_password()."""

    def test_returns_different_string_than_input(self) -> None:
        password = "my_secret"
        hashed = hash_password(password)
        assert hashed != password

    def test_produces_different_hashes_for_same_password(self) -> None:
        password = "my_secret"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2


class TestVerifyPassword:
    """Tests for verify_password()."""

    def test_correct_password_returns_true(self) -> None:
        password = "my_secret"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_wrong_password_returns_false(self) -> None:
        hashed = hash_password("correct_password")
        assert verify_password("wrong_password", hashed) is False


class TestCreateAccessToken:
    """Tests for create_access_token()."""

    def test_returns_string(self) -> None:
        token = create_access_token(user_id=1, username="alice")
        assert isinstance(token, str)
        assert len(token) > 0


class TestDecodeToken:
    """Tests for decode_token()."""

    def test_round_trip_returns_correct_payload(self) -> None:
        token = create_access_token(user_id=42, username="bob")
        result = decode_token(token)
        assert result == {"id": 42, "username": "bob"}

    def test_garbage_token_raises_401(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            decode_token("not.a.valid.jwt.token")
        assert exc_info.value.status_code == 401

    def test_expired_token_raises_401(self) -> None:
        expired_payload = {
            "sub": "1",
            "username": "alice",
            "exp": datetime.utcnow() - timedelta(days=1),
        }
        expired_token = jwt.encode(expired_payload, SECRET_KEY, algorithm=ALGORITHM)
        with pytest.raises(HTTPException) as exc_info:
            decode_token(expired_token)
        assert exc_info.value.status_code == 401

    def test_token_missing_sub_raises_401(self) -> None:
        payload_no_sub = {
            "username": "alice",
            "exp": datetime.utcnow() + timedelta(days=1),
        }
        token = jwt.encode(payload_no_sub, SECRET_KEY, algorithm=ALGORITHM)
        with pytest.raises(HTTPException) as exc_info:
            decode_token(token)
        assert exc_info.value.status_code == 401


class TestGetCurrentUser:
    """Tests for get_current_user() — async."""

    async def test_none_header_raises_401(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(authorization=None)
        assert exc_info.value.status_code == 401

    async def test_basic_scheme_raises_401(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(authorization="Basic xyz")
        assert exc_info.value.status_code == 401

    async def test_valid_bearer_returns_user_dict(self) -> None:
        token = create_access_token(user_id=7, username="carol")
        result = await get_current_user(authorization=f"Bearer {token}")
        assert result == {"id": 7, "username": "carol"}

    async def test_bearer_garbage_raises_401(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(authorization="Bearer garbage.token.here")
        assert exc_info.value.status_code == 401
