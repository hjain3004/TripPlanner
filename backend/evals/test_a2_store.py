from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from accounts.models import FORBIDDEN_FIELD_NAMES, Session, UserCredential

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def _session(**overrides: object) -> Session:
    kwargs: dict[str, object] = {
        "id": "s1",
        "user_id": "u1",
        "token_hash": "a" * 64,
        "created_at": NOW,
        "last_seen_at": NOW,
        "expires_at": NOW + timedelta(days=14),
    }
    kwargs.update(overrides)
    return Session(**kwargs)  # type: ignore[arg-type]


def test_credential_stores_a_hash_not_a_password() -> None:
    cred = UserCredential(
        user_id="u1",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$abc$def",
        updated_at=NOW,
    )

    assert cred.algorithm == "argon2id"
    assert cred.failed_attempts == 0
    assert cred.locked_until is None


def test_credential_rejects_a_plaintext_password_field() -> None:
    with pytest.raises(ValidationError):
        UserCredential(
            user_id="u1",
            password_hash="$argon2id$x",
            updated_at=NOW,
            password="hunter2",
        )


def test_password_hash_is_not_a_forbidden_field_name() -> None:
    """password is forbidden forever; password_hash is the correct thing to store."""
    assert "password" in FORBIDDEN_FIELD_NAMES
    assert "password_hash" not in FORBIDDEN_FIELD_NAMES
    for field_name in UserCredential.model_fields:
        assert field_name.lower() not in FORBIDDEN_FIELD_NAMES


def test_session_rejects_a_token_hash_that_is_not_sha256_hex() -> None:
    with pytest.raises(ValidationError):
        _session(token_hash="tooshort")


def test_session_is_valid_before_expiry() -> None:
    assert _session().is_valid_at(NOW + timedelta(days=1)) is True


def test_session_is_invalid_at_and_after_expiry() -> None:
    session = _session()

    assert session.is_valid_at(session.expires_at) is False
    assert session.is_valid_at(session.expires_at + timedelta(seconds=1)) is False


def test_revoked_session_is_invalid_even_before_expiry() -> None:
    session = _session(revoked_at=NOW)

    assert session.is_valid_at(NOW + timedelta(days=1)) is False
