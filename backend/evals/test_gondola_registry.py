from __future__ import annotations

import pytest

from gateway.travel.registry import get_default_travel_registry


def test_default_registry_includes_a_gondola_entry() -> None:
    registry = get_default_travel_registry()
    assert any(e.provider_id == "gondola" for e in registry.entries)


def test_gondola_entry_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRIPWISE_GONDOLA_LIVE_ENABLED", raising=False)
    monkeypatch.delenv("TRIPWISE_GONDOLA_KILL_SWITCH", raising=False)
    registry = get_default_travel_registry()
    entry = registry.get_entry("gondola")
    assert entry.enabled is False


def test_select_providers_returns_only_sample_when_gondola_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRIPWISE_GONDOLA_LIVE_ENABLED", raising=False)
    registry = get_default_travel_registry()
    eligible = registry.select_providers(
        active_profile="student_noncommercial", domain="hotel", country="SG"
    )
    provider_ids = [e.provider_id for e in eligible]
    assert provider_ids == ["sample_travel_adapter"]


def test_env_flag_enables_gondola_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIPWISE_GONDOLA_LIVE_ENABLED", "true")
    monkeypatch.delenv("TRIPWISE_GONDOLA_KILL_SWITCH", raising=False)
    registry = get_default_travel_registry()
    entry = registry.get_entry("gondola")
    assert entry.enabled is True


def test_kill_switch_overrides_the_live_enabled_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIPWISE_GONDOLA_LIVE_ENABLED", "true")
    monkeypatch.setenv("TRIPWISE_GONDOLA_KILL_SWITCH", "true")
    registry = get_default_travel_registry()
    entry = registry.get_entry("gondola")
    assert entry.enabled is False


def test_gondola_is_preferred_over_sample_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIPWISE_GONDOLA_LIVE_ENABLED", "true")
    monkeypatch.delenv("TRIPWISE_GONDOLA_KILL_SWITCH", raising=False)
    registry = get_default_travel_registry()
    eligible = registry.select_providers(
        active_profile="student_noncommercial", domain="hotel", country="SG"
    )
    assert eligible[0].provider_id == "gondola"
    assert eligible[-1].provider_id == "sample_travel_adapter"


def test_gondola_is_only_eligible_for_student_noncommercial_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRIPWISE_GONDOLA_LIVE_ENABLED", "true")
    registry = get_default_travel_registry()
    eligible = registry.select_providers(
        active_profile="commercial_production", domain="hotel", country="SG"
    )
    assert all(e.provider_id != "gondola" for e in eligible)
