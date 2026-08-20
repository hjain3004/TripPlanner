"""Freshness state transitions — spec 16 §8.

Status is code-computed, never supplied by a provider or LLM: a source may
declare live/cached/estimated/verify_required, but only this function may
promote that declaration to ``stale`` once its expiry has passed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

Status = Literal["live", "cached", "estimated", "stale", "verify_required"]


def is_expired(expires_at: datetime | None, now: datetime) -> bool:
    """Exact-instant equality counts as expired: evidence is live only while
    now < expires_at."""
    if expires_at is None:
        return False
    return now >= expires_at


def compute_status(
    *,
    source_status: Status,
    retrieved_at: datetime,
    expires_at: datetime | None,
    now: datetime,
) -> Status:
    if source_status in ("live", "cached") and is_expired(expires_at, now):
        return "stale"
    return source_status
