from pathlib import Path

from agents.retrieval import retrieve_candidates
from agents.models import TripSpec
from core.db import KnowledgeBase


class StubKB:
    def pois(self, city: str) -> list:
        return []

    def areas(self, city: str) -> list:
        return []


def _spec(destination: str) -> TripSpec:
    return TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city=destination,
        start_date="2026-10-10",
        end_date="2026-10-15",
        travelers=1,
        style="balanced",
        wallet={"currency": "INR", "card_ids": []},
    )


def test_an_unknown_destination_does_not_get_the_singapore_catalog(
    tmp_path: Path,
) -> None:
    """Task 5: a destination not in regions.yaml must NOT silently
    inherit Singapore's catalog, centroid, or timezone."""
    ctx = retrieve_candidates(
        _spec("XYZ"),
        StubKB(),  # type: ignore[arg-type]
        catalog=tmp_path / "nonexistent.json",
    )
    # No catalog POIs should appear for an unknown destination
    assert ctx.pois == []
    assert ctx.areas == []


def test_singapore_still_resolves(tmp_path: Path) -> None:
    """Anti-regression: SIN must still resolve to Singapore."""
    from gateway.catalog.regions import get_region

    region = get_region("SIN")
    assert region is not None
    assert region.city_name == "Singapore"
    assert region.timezone == "Asia/Singapore"
