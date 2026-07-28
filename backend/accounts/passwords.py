"""Argon2id password hashing (spec 17 §4).

Never MD5, SHA-1, plain SHA-256, or bcrypt without tuned cost. The returned
string encodes salt and parameters, so no separate salt column is needed.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

ALGORITHM = "argon2id"

_hasher = PasswordHasher()

# A hash of a value no user can have. Verifying against it costs the same as a
# real verification, which is what keeps login timing uniform when the account
# does not exist — see dummy_verify.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing-uniformity")


def hash_password(plaintext: str) -> str:
    if not plaintext:
        raise ValueError("password must not be empty")
    return _hasher.hash(plaintext)


def verify_password(plaintext: str, stored_hash: str) -> bool:
    """False on mismatch AND on a malformed stored hash. Never raises."""
    try:
        return _hasher.verify(stored_hash, plaintext)
    except (VerifyMismatchError, VerificationError, ValueError):
        return False


def dummy_verify(plaintext: str) -> None:
    """Burn a verification against a fixed hash. Call when the user is absent."""
    try:
        _hasher.verify(_DUMMY_HASH, plaintext)
    except (VerifyMismatchError, VerificationError, ValueError):
        pass
