from __future__ import annotations

import pytest
from pydantic import ValidationError

from gateway.travel.protocol import AdapterCapabilities


def test_capabilities_rejects_unknown_domain() -> None:
    with pytest.raises(ValidationError):
        AdapterCapabilities(
            provider_id="x", domains={"flight", "bookings"}, countries="configured",
            live_data=False, supports_cache=False, supports_commercial_use=False,
            allowed_profiles={"student_noncommercial"}, source_method="sample",
            stability="stable", requires_user_initiated_search=False, max_concurrency=1,
        )


def test_capabilities_rejects_unknown_source_method() -> None:
    with pytest.raises(ValidationError):
        AdapterCapabilities(
            provider_id="x", domains={"flight"}, countries="configured",
            live_data=False, supports_cache=False, supports_commercial_use=False,
            allowed_profiles={"student_noncommercial"}, source_method="webhook",
            stability="stable", requires_user_initiated_search=False, max_concurrency=1,
        )


def test_capabilities_rejects_zero_concurrency() -> None:
    with pytest.raises(ValidationError):
        AdapterCapabilities(
            provider_id="x", domains={"flight"}, countries="configured",
            live_data=False, supports_cache=False, supports_commercial_use=False,
            allowed_profiles={"student_noncommercial"}, source_method="sample",
            stability="stable", requires_user_initiated_search=False, max_concurrency=0,
        )


def test_capabilities_accepts_valid_shape() -> None:
    caps = AdapterCapabilities(
        provider_id="sample_travel_adapter", domains={"flight", "hotel", "award"},
        countries="configured", live_data=False, supports_cache=False,
        supports_commercial_use=False, allowed_profiles={"student_noncommercial"},
        source_method="sample", stability="stable",
        requires_user_initiated_search=False, max_concurrency=1,
    )
    assert caps.provider_id == "sample_travel_adapter"


def test_capabilities_accepts_explicit_country_set() -> None:
    caps = AdapterCapabilities(
        provider_id="x", domains={"hotel"}, countries={"SG", "IN"},
        live_data=True, supports_cache=True, supports_commercial_use=False,
        allowed_profiles={"student_noncommercial"}, source_method="official_api",
        stability="experimental", requires_user_initiated_search=True, max_concurrency=2,
    )
    assert caps.countries == {"SG", "IN"}
