"""RegionCapability: honest, request-time reporting of what a destination
actually supports, without silently borrowing Singapore's catalog or budget
data. See docs/superpowers/plans/2026-08-15-itinerary-i7-catalog-relevance-and-regional-rollout.md
Task 6.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.pipeline import build_region_capability
from gateway.catalog.activate import CatalogSummary
from gateway.catalog.regions import Region


def _region(**overrides: object) -> Region:
    base: dict[str, object] = dict(
        iata="BOM",
        city_name="Mumbai",
        country_code="IN",
        timezone="Asia/Kolkata",
        catalog_id="bom-core",
        centroid_lat=19.0760,
        centroid_lon=72.8777,
        currency="INR",
        budget_supported=False,
    )
    base.update(overrides)
    return Region(**base)  # type: ignore[arg-type]


def test_unregistered_destination_returns_no_capability(tmp_path: Path) -> None:
    assert build_region_capability("ZZZ_NOWHERE", tmp_path / "catalogs") is None


def test_registered_region_without_a_built_catalog_reports_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _region()
    monkeypatch.setattr(
        "agents.pipeline.get_region", lambda iata: fake if iata == "BOM" else None
    )

    cap = build_region_capability("BOM", tmp_path / "catalogs")

    assert cap is not None
    assert cap.region == "BOM"
    assert cap.catalog_status == "absent"
    assert cap.place_count == 0


def test_a_region_without_budget_support_reports_the_gap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The mechanism this test guards: no currency/FX rate exists for a new
    region (I7 constraint 2), so budget_supported stays False and the gap is
    named explicitly rather than silently defaulting to zero or SGD."""
    fake = _region(budget_supported=False, currency="INR")
    monkeypatch.setattr(
        "agents.pipeline.get_region", lambda iata: fake if iata == "BOM" else None
    )

    cap = build_region_capability("BOM", tmp_path / "catalogs")

    assert cap is not None
    assert cap.budget_supported is False
    assert cap.known_gaps != []
    assert "INR" in cap.known_gaps[0]


def test_a_budget_supported_region_reports_no_gaps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _region(iata="SIN", city_name="Singapore", currency="SGD", budget_supported=True)
    monkeypatch.setattr(
        "agents.pipeline.get_region", lambda iata: fake if iata == "SIN" else None
    )

    cap = build_region_capability("SIN", tmp_path / "catalogs")

    assert cap is not None
    assert cap.budget_supported is True
    assert cap.known_gaps == []


def test_a_region_with_a_built_catalog_reports_active_and_the_real_place_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    catalog_root = tmp_path / "catalogs"
    catalog_root.mkdir()
    (catalog_root / "active_test-region.summary.json").write_text(
        CatalogSummary(
            catalog_id="test-region", catalog_release="1", place_count=42, quality_passed=True
        ).model_dump_json()
    )
    fake = _region(iata="XYZ", catalog_id="test-region")
    monkeypatch.setattr(
        "agents.pipeline.get_region", lambda iata: fake if iata == "XYZ" else None
    )

    cap = build_region_capability("XYZ", catalog_root)

    assert cap is not None
    assert cap.catalog_status == "active"
    assert cap.place_count == 42
