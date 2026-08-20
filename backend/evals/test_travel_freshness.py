from __future__ import annotations

from datetime import UTC, datetime

from gateway.travel.freshness import compute_status, is_expired


def test_live_inside_ttl_stays_live() -> None:
    now = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    expires = datetime(2026, 8, 1, 11, 0, tzinfo=UTC)
    assert (
        compute_status(source_status="live", retrieved_at=now, expires_at=expires, now=now)
        == "live"
    )


def test_expired_live_becomes_stale() -> None:
    retrieved = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    expires = datetime(2026, 8, 1, 11, 0, tzinfo=UTC)
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    assert (
        compute_status(source_status="live", retrieved_at=retrieved, expires_at=expires, now=now)
        == "stale"
    )


def test_exact_instant_equality_counts_as_expired() -> None:
    t = datetime(2026, 8, 1, 11, 0, tzinfo=UTC)
    assert is_expired(t, t) is True


def test_no_expiry_is_never_expired() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    assert is_expired(None, now) is False


def test_estimated_never_becomes_live_regardless_of_clock() -> None:
    retrieved = datetime(2026, 8, 1, tzinfo=UTC)
    now = datetime(2030, 1, 1, tzinfo=UTC)
    assert (
        compute_status(source_status="estimated", retrieved_at=retrieved, expires_at=None, now=now)
        == "estimated"
    )


def test_cached_without_expiry_stays_cached() -> None:
    retrieved = datetime(2026, 8, 1, tzinfo=UTC)
    now = datetime(2026, 8, 2, tzinfo=UTC)
    assert (
        compute_status(source_status="cached", retrieved_at=retrieved, expires_at=None, now=now)
        == "cached"
    )


def test_cached_with_expiry_past_becomes_stale() -> None:
    retrieved = datetime(2026, 8, 1, tzinfo=UTC)
    expires = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    now = datetime(2026, 8, 2, tzinfo=UTC)
    assert (
        compute_status(source_status="cached", retrieved_at=retrieved, expires_at=expires, now=now)
        == "stale"
    )


def test_verify_required_passes_through_unchanged() -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    assert (
        compute_status(source_status="verify_required", retrieved_at=now, expires_at=None, now=now)
        == "verify_required"
    )
