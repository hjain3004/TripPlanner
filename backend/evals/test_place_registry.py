from __future__ import annotations

import random

import pytest

from gateway.places.registry import (
    AdapterCapabilities,
    PlaceGatewayError,
    ProviderRegistry,
    ProviderRegistryEntry,
    get_default_place_registry,
)


def test_disabled_entry_is_never_selected() -> None:
    reg = ProviderRegistry(
        entries=[
            ProviderRegistryEntry(
                provider_id="test1",
                enabled=False,
                allowed_profiles=["student_noncommercial"],
                capabilities=AdapterCapabilities(domains=["poi"], supported_countries=["SG"]),
                remaining_quota=10,
            )
        ]
    )
    selected = reg.select_providers("student_noncommercial", "poi", "SG")
    assert len(selected) == 0


def test_wrong_profile_entry_is_rejected() -> None:
    reg = ProviderRegistry(
        entries=[
            ProviderRegistryEntry(
                provider_id="commercial_only",
                enabled=True,
                allowed_profiles=["commercial_production"],
                capabilities=AdapterCapabilities(domains=["poi"], supported_countries=["SG"]),
                remaining_quota=10,
            )
        ]
    )
    selected = reg.select_providers("student_noncommercial", "poi", "SG")
    assert len(selected) == 0


def test_selection_order_is_deterministic_across_shuffled_input() -> None:
    entries = [
        ProviderRegistryEntry(
            provider_id="p1",
            enabled=True,
            allowed_profiles=["student_noncommercial"],
            capabilities=AdapterCapabilities(domains=["poi"], supported_countries=["SG"]),
            remaining_quota=10,
            priority=1,
        ),
        ProviderRegistryEntry(
            provider_id="p2",
            enabled=True,
            allowed_profiles=["student_noncommercial"],
            capabilities=AdapterCapabilities(domains=["poi"], supported_countries=["SG"]),
            remaining_quota=10,
            priority=2,
        ),
        ProviderRegistryEntry(
            provider_id="p3",
            enabled=True,
            allowed_profiles=["student_noncommercial"],
            capabilities=AdapterCapabilities(domains=["poi"], supported_countries=["SG"]),
            remaining_quota=5,
            priority=1,
        ),
    ]

    # Expected order: p1, p2, p3?
    # quota descending, priority ascending, provider_id ascending
    # p1: quota 10, pri 1
    # p2: quota 10, pri 2
    # p3: quota 5, pri 1
    # Sorting key is: -quota, priority, provider_id
    # p1: -10, 1, p1 -> 1st
    # p2: -10, 2, p2 -> 2nd
    # p3: -5, 1, p3 -> 3rd

    shuffled1 = entries[:]
    random.shuffle(shuffled1)
    reg1 = ProviderRegistry(entries=shuffled1)
    sel1 = reg1.select_providers("student_noncommercial", "poi", "SG")

    shuffled2 = entries[:]
    random.shuffle(shuffled2)
    reg2 = ProviderRegistry(entries=shuffled2)
    sel2 = reg2.select_providers("student_noncommercial", "poi", "SG")

    assert [x.provider_id for x in sel1] == ["p1", "p2", "p3"]
    assert [x.provider_id for x in sel2] == ["p1", "p2", "p3"]


def test_unknown_provider_id_raises() -> None:
    reg = ProviderRegistry(entries=[])
    with pytest.raises(PlaceGatewayError, match="Unknown provider_id: fake"):
        reg.get_entry("fake")


def test_sample_place_adapter_is_the_only_entry_enabled_by_default() -> None:
    reg = get_default_place_registry()
    enabled_entries = [e for e in reg.entries if e.enabled]
    assert len(enabled_entries) == 1
    assert enabled_entries[0].provider_id == "sample_adapter"
