from __future__ import annotations

import pytest

from accounts.passwords import (
    ALGORITHM,
    dummy_verify,
    hash_password,
    verify_password,
)


def test_hash_is_argon2id_and_not_the_plaintext() -> None:
    stored = hash_password("correct horse battery staple")

    assert ALGORITHM == "argon2id"
    assert stored.startswith("$argon2id$")
    assert "correct horse battery staple" not in stored


def test_same_password_hashes_differently_each_time() -> None:
    assert hash_password("hunter2hunter2") != hash_password("hunter2hunter2")


def test_verify_accepts_the_right_password() -> None:
    assert verify_password("hunter2hunter2", hash_password("hunter2hunter2")) is True


def test_verify_rejects_the_wrong_password() -> None:
    assert verify_password("hunter3hunter3", hash_password("hunter2hunter2")) is False


def test_verify_rejects_a_malformed_hash_without_raising() -> None:
    assert verify_password("hunter2hunter2", "not-a-hash") is False


def test_dummy_verify_returns_none_and_does_not_raise() -> None:
    assert dummy_verify("anything") is None


def test_empty_password_is_rejected() -> None:
    with pytest.raises(ValueError):
        hash_password("")
