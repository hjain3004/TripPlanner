from __future__ import annotations

import pytest

from gateway.travel.errors import TravelGatewayError


def test_error_carries_typed_code() -> None:
    err = TravelGatewayError("no_results", "no flights found")
    assert err.code == "no_results"
    assert "no flights found" in str(err)


def test_error_redacts_secrets() -> None:
    err = TravelGatewayError("authentication_failed", "Authorization: Bearer sk_live_abcdef123456")
    assert "sk_live_abcdef123456" not in str(err)
    assert "REDACTED" in str(err)


@pytest.mark.parametrize(
    "code",
    [
        "provider_unavailable", "authentication_failed", "permission_denied",
        "rate_limited", "budget_exhausted", "timeout", "invalid_response",
        "no_results", "unsupported_domain", "region_restricted", "terms_disabled",
    ],
)
def test_all_spec16_codes_are_constructible(code: str) -> None:
    err = TravelGatewayError(code, "x")  # type: ignore[arg-type]
    assert err.code == code


def test_repr_includes_code() -> None:
    err = TravelGatewayError("timeout", "adapter timed out")
    assert "timeout" in repr(err)
