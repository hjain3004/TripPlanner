from __future__ import annotations

import pytest
from pydantic import ValidationError

from gateway.travel.registry import (
    TravelProviderRegistry,
    TravelProviderRegistryEntry,
    get_default_travel_registry,
)


def test_sample_adapter_is_enabled_by_default() -> None:
    registry = get_default_travel_registry()
    entry = registry.get_entry("sample_travel_adapter")
    assert entry.enabled is True
    assert entry.source_method == "sample"
    assert entry.live_data is False
    assert entry.monthly_cost_minor == 0


def test_disabled_provider_is_never_selected() -> None:
    registry = TravelProviderRegistry(
        entries=[
            TravelProviderRegistryEntry(
                provider_id="future_live",
                enabled=False,
                allowed_profiles={"student_noncommercial"},
                domains={"flight"},
                countries={"SG"},
                source_method="official_api",
                monthly_cost_minor=0,
                priority=10,
            ),
        ]
    )
    selected = registry.select_providers(
        active_profile="student_noncommercial", domain="flight", country="SG"
    )
    assert selected == []


def test_capability_mismatch_excludes_provider() -> None:
    registry = TravelProviderRegistry(
        entries=[
            TravelProviderRegistryEntry(
                provider_id="hotel_only",
                enabled=True,
                allowed_profiles={"student_noncommercial"},
                domains={"hotel"},
                countries={"SG"},
                source_method="sample",
                monthly_cost_minor=0,
                priority=10,
            ),
        ]
    )
    assert (
        registry.select_providers(
            active_profile="student_noncommercial", domain="flight", country="SG"
        )
        == []
    )


def test_profile_mismatch_excludes_provider() -> None:
    registry = TravelProviderRegistry(
        entries=[
            TravelProviderRegistryEntry(
                provider_id="commercial_only",
                enabled=True,
                allowed_profiles={"commercial_production"},
                domains={"flight"},
                countries={"SG"},
                source_method="official_api",
                monthly_cost_minor=0,
                priority=10,
            ),
        ]
    )
    assert (
        registry.select_providers(
            active_profile="student_noncommercial", domain="flight", country="SG"
        )
        == []
    )


def test_unsupported_country_excludes_provider() -> None:
    registry = get_default_travel_registry()
    registry.entries.append(
        TravelProviderRegistryEntry(
            provider_id="sg_only",
            enabled=True,
            allowed_profiles={"student_noncommercial"},
            domains={"flight"},
            countries={"SG"},
            source_method="official_api",
            monthly_cost_minor=0,
            priority=1,
        )
    )
    selected = registry.select_providers(
        active_profile="student_noncommercial", domain="flight", country="IN"
    )
    assert all(e.provider_id != "sg_only" for e in selected)


def test_unknown_cost_means_disabled() -> None:
    with pytest.raises(ValidationError):
        TravelProviderRegistryEntry(
            provider_id="mystery",
            enabled=True,
            allowed_profiles={"student_noncommercial"},
            domains={"flight"},
            countries={"SG"},
            source_method="official_api",
            monthly_cost_minor=None,  # type: ignore[arg-type]
            priority=10,
        )


def test_negative_cost_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TravelProviderRegistryEntry(
            provider_id="negative_cost",
            enabled=True,
            allowed_profiles={"student_noncommercial"},
            domains={"flight"},
            countries={"SG"},
            source_method="official_api",
            monthly_cost_minor=-1,
            priority=10,
        )


def test_selection_is_deterministic_ordering() -> None:
    registry = TravelProviderRegistry(
        entries=[
            TravelProviderRegistryEntry(
                provider_id="b",
                enabled=True,
                allowed_profiles={"student_noncommercial"},
                domains={"flight"},
                countries={"SG"},
                source_method="sample",
                monthly_cost_minor=0,
                priority=10,
            ),
            TravelProviderRegistryEntry(
                provider_id="a",
                enabled=True,
                allowed_profiles={"student_noncommercial"},
                domains={"flight"},
                countries={"SG"},
                source_method="sample",
                monthly_cost_minor=0,
                priority=10,
            ),
        ]
    )
    selected = registry.select_providers(
        active_profile="student_noncommercial", domain="flight", country="SG"
    )
    assert [e.provider_id for e in selected] == ["a", "b"]


def test_selection_orders_by_priority_before_id() -> None:
    registry = TravelProviderRegistry(
        entries=[
            TravelProviderRegistryEntry(
                provider_id="z_high_priority",
                enabled=True,
                allowed_profiles={"student_noncommercial"},
                domains={"flight"},
                countries={"SG"},
                source_method="sample",
                monthly_cost_minor=0,
                priority=1,
            ),
            TravelProviderRegistryEntry(
                provider_id="a_low_priority",
                enabled=True,
                allowed_profiles={"student_noncommercial"},
                domains={"flight"},
                countries={"SG"},
                source_method="sample",
                monthly_cost_minor=0,
                priority=50,
            ),
        ]
    )
    selected = registry.select_providers(
        active_profile="student_noncommercial", domain="flight", country="SG"
    )
    assert [e.provider_id for e in selected] == ["z_high_priority", "a_low_priority"]


def test_sample_adapter_always_available_even_with_zero_other_providers() -> None:
    registry = get_default_travel_registry()
    selected = registry.select_providers(
        active_profile="student_noncommercial", domain="flight", country="IN"
    )
    assert any(e.provider_id == "sample_travel_adapter" for e in selected)


def test_unknown_provider_id_raises_typed_error() -> None:
    from gateway.travel.errors import TravelGatewayError

    registry = get_default_travel_registry()
    with pytest.raises(TravelGatewayError) as exc_info:
        registry.get_entry("does_not_exist")
    assert exc_info.value.code == "provider_unavailable"


def test_llm_is_never_involved_in_selection() -> None:
    import inspect

    from gateway.travel import registry as registry_module

    source = inspect.getsource(registry_module)
    assert "llm" not in source.casefold()
