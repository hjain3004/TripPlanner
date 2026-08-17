from __future__ import annotations

import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agents.models import PlaceSearchRequest
from agents.search import search_catalog_places
from api.main import app, build_place_provider_resolver, get_kb, get_place_provider_resolver
from core.db import DB_PATH, load_kb, seed_database
from gateway.places.adapters.tripadvisor import (
    FixtureTripadvisorTransport,
    TripadvisorEntityLedger,
    TripadvisorTerraAdapter,
)
from gateway.places.contracts import PartialPlaceResult
from gateway.places.registry import (
    AdapterCapabilities,
    PlaceGatewayError,
    ProviderRegistry,
    ProviderRegistryEntry,
    get_default_place_registry,
)


@pytest.fixture(autouse=True)
def assert_zero_network_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    real_socket = socket.socket

    def guarded_socket(*args: object, **kwargs: object) -> socket.socket:
        family = args[0] if args else kwargs.get("family", socket.AF_INET)
        if family in (socket.AF_INET, socket.AF_INET6):
            raise RuntimeError(
                "Zero-network violation: external socket creation attempted during API tests"
            )
        return real_socket(*args, **kwargs)

    monkeypatch.setattr(socket, "socket", guarded_socket)


def _get_test_kb():
    if not DB_PATH.exists():
        seed_database()
    return load_kb(DB_PATH)


def test_search_places_returns_seeded_results() -> None:
    kb = _get_test_kb()
    req = PlaceSearchRequest(destination="SIN", query="gardens", limit=5)
    resp = search_catalog_places(req, kb)
    assert len(resp.results) > 0
    match = next((r for r in resp.results if "gardens" in r.name.casefold()), None)
    assert match is not None
    assert match.poi_id == "sg-gardens-by-the-bay"
    assert match.evidence is not None
    assert match.evidence.status == "live"


def test_search_places_category_filter() -> None:
    kb = _get_test_kb()
    req = PlaceSearchRequest(destination="SIN", category="food", limit=10)
    resp = search_catalog_places(req, kb)
    for r in resp.results:
        assert r.category == "food"


def test_search_places_api_endpoint() -> None:
    client = TestClient(app)
    app.dependency_overrides[get_kb] = _get_test_kb

    try:
        response = client.post(
            "/places/search", json={"destination": "SIN", "query": "maxwell", "limit": 5}
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert len(data["results"]) >= 1
        assert data["results"][0]["poi_id"] == "sg-hawker-maxwell"
        assert data["results"][0]["name"] == "Maxwell Food Centre"
    finally:
        app.dependency_overrides.clear()


def test_search_places_api_default_resolver_does_not_invoke_disabled_tripadvisor() -> None:
    client = TestClient(app)
    app.dependency_overrides[get_kb] = _get_test_kb

    try:
        response = client.post(
            "/places/search", json={"destination": "SIN", "query": "maxwell", "limit": 5}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["diagnostics"] == []
        assert data["results"][0]["poi_id"] == "sg-hawker-maxwell"
    finally:
        app.dependency_overrides.clear()


def test_search_places_api_test_resolver_invokes_fixture_adapter_through_registry(
    tmp_path: Path,
) -> None:
    client = TestClient(app)
    app.dependency_overrides[get_kb] = _get_test_kb

    ledger = TripadvisorEntityLedger(db_path=tmp_path / "billable.db", is_billable=True)
    registry = get_default_place_registry(ledger=ledger)
    ta_entry = registry.get_entry("tripadvisor_terra")
    ta_entry.enabled = True
    adapter = TripadvisorTerraAdapter(
        transport=FixtureTripadvisorTransport(default_search_fixture="search_locations_success.json")
    )

    def _resolver_override():
        return build_place_provider_resolver(
            registry,
            {"tripadvisor_terra": adapter},
            active_profile="student_noncommercial",
        )

    app.dependency_overrides[get_place_provider_resolver] = _resolver_override

    try:
        response = client.post(
            "/places/search", json={"destination": "SIN", "query": "Lau Pa Sat", "limit": 5}
        )
        assert response.status_code == 200
        data = response.json()
        result_ids = [item["poi_id"] for item in data["results"]]
        assert "poi:ta_310892" in result_ids
    finally:
        app.dependency_overrides.clear()


def test_search_places_api_test_resolver_reports_fixture_failure_through_diagnostics(
    tmp_path: Path,
) -> None:
    client = TestClient(app)
    app.dependency_overrides[get_kb] = _get_test_kb

    ledger = TripadvisorEntityLedger(db_path=tmp_path / "billable.db", is_billable=True)
    registry = get_default_place_registry(ledger=ledger)
    ta_entry = registry.get_entry("tripadvisor_terra")
    ta_entry.enabled = True
    adapter = TripadvisorTerraAdapter(
        transport=FixtureTripadvisorTransport(default_search_fixture="error_500_server_error.json")
    )

    def _resolver_override():
        return build_place_provider_resolver(
            registry,
            {"tripadvisor_terra": adapter},
            active_profile="student_noncommercial",
        )

    app.dependency_overrides[get_place_provider_resolver] = _resolver_override

    try:
        response = client.post(
            "/places/search", json={"destination": "SIN", "query": "maxwell", "limit": 5}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"][0]["poi_id"] == "sg-hawker-maxwell"
        assert data["diagnostics"]
        assert data["diagnostics"][0]["provider_id"] == "tripadvisor_terra"
        assert data["diagnostics"][0]["fallback_used"] is True
        assert data["diagnostics"][0]["code"] == "provider_unavailable"
    finally:
        app.dependency_overrides.clear()


def test_search_places_api_preserves_rate_limit_timeout_and_budget_diagnostics(
    tmp_path: Path,
) -> None:
    class _DiagnosticAdapter:
        provider_id = "diagnostic_fixture"

        def __init__(self, mode: str) -> None:
            self.mode = mode

        def search_places(self, request):  # noqa: ANN001
            if self.mode == "rate_limited":
                return [], PartialPlaceResult(
                    unresolved_needs=["tripadvisor_candidate_search"],
                    stop_reason="rate_limited",
                )
            if self.mode == "timeout":
                raise PlaceGatewayError("timeout", "provider timeout")
            return [], PartialPlaceResult(
                unresolved_needs=["tripadvisor_candidate_search"],
                stop_reason="budget_exhausted",
            )

    for mode, expected_code in [
        ("rate_limited", "rate_limited"),
        ("timeout", "timeout"),
        ("budget_exhausted", "budget_exhausted"),
    ]:
        client = TestClient(app)
        app.dependency_overrides[get_kb] = _get_test_kb
        registry = ProviderRegistry(
            entries=[
                ProviderRegistryEntry(
                    provider_id="diagnostic_fixture",
                    enabled=True,
                    allowed_profiles=["student_noncommercial"],
                    capabilities=AdapterCapabilities(domains=["poi"], supported_countries=["SG"]),
                    remaining_quota=1,
                )
            ]
        )
        adapter = _DiagnosticAdapter(mode)

        def _make_resolver_override(
            selected_registry: ProviderRegistry,
            selected_adapter: _DiagnosticAdapter,
        ):
            def _resolver_override():
                return build_place_provider_resolver(
                    selected_registry,
                    {"diagnostic_fixture": selected_adapter},
                    active_profile="student_noncommercial",
                )

            return _resolver_override

        app.dependency_overrides[get_place_provider_resolver] = _make_resolver_override(
            registry,
            adapter,
        )

        try:
            response = client.post(
                "/places/search", json={"destination": "SIN", "query": "maxwell", "limit": 5}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["results"][0]["poi_id"] == "sg-hawker-maxwell"
            assert data["diagnostics"][0]["provider_id"] == "diagnostic_fixture"
            assert data["diagnostics"][0]["code"] == expected_code
        finally:
            app.dependency_overrides.clear()


def test_search_places_api_missing_coordinates_remain_none(tmp_path: Path) -> None:
    client = TestClient(app)
    app.dependency_overrides[get_kb] = _get_test_kb

    ledger = TripadvisorEntityLedger(db_path=tmp_path / "billable.db", is_billable=True)
    registry = get_default_place_registry(ledger=ledger)
    registry.get_entry("tripadvisor_terra").enabled = True
    adapter = TripadvisorTerraAdapter(
        transport=FixtureTripadvisorTransport(default_search_fixture="missing_optional_fields.json")
    )

    def _resolver_override():
        return build_place_provider_resolver(
            registry,
            {"tripadvisor_terra": adapter},
            active_profile="student_noncommercial",
        )

    app.dependency_overrides[get_place_provider_resolver] = _resolver_override

    try:
        response = client.post(
            "/places/search", json={"destination": "SIN", "query": "Unrated", "limit": 5}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"][0]["lat"] is None
        assert data["results"][0]["lon"] is None
    finally:
        app.dependency_overrides.clear()


def test_search_places_api_env_var_does_not_activate_tripadvisor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRIPWISE_TRIPADVISOR_API_KEY", "fake_key_that_must_not_activate")
    client = TestClient(app)
    app.dependency_overrides[get_kb] = _get_test_kb

    try:
        response = client.post(
            "/places/search", json={"destination": "SIN", "query": "maxwell", "limit": 5}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"][0]["poi_id"] == "sg-hawker-maxwell"
        assert data["diagnostics"] == []
    finally:
        app.dependency_overrides.clear()


def test_build_place_provider_resolver_requires_registry_eligibility(tmp_path: Path) -> None:
    ledger = TripadvisorEntityLedger(db_path=tmp_path / "billable.db", is_billable=True)
    registry = ProviderRegistry(
        entries=[
            ProviderRegistryEntry(
                provider_id="tripadvisor_terra",
                enabled=False,
                allowed_profiles=["student_noncommercial"],
                capabilities=AdapterCapabilities(domains=["poi"], supported_countries=["SG"]),
                remaining_quota=ledger.get_status()["remaining"],
            )
        ]
    )
    adapter = TripadvisorTerraAdapter(
        transport=FixtureTripadvisorTransport(default_search_fixture="search_locations_success.json")
    )
    resolver = build_place_provider_resolver(
        registry,
        {"tripadvisor_terra": adapter},
        active_profile="student_noncommercial",
    )

    request = PlaceSearchRequest(destination="SIN", query="Lau Pa Sat", limit=5)
    assert resolver(request) is None
