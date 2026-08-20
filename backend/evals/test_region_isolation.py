"""I7 Task 7: a second real, activated region (Mumbai) must not leak into or
borrow from Singapore's catalog, and vice versa. Requires both real catalogs
built (backend/catalogs/active_sg-core.json, active_bom-core.json) - skipped
otherwise, since this is a real-data integration check, not a unit test.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from agents.models import TripSpec
from agents.retrieval import retrieve_candidates


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
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        travelers=2,
        style="balanced",
        interests=["food"],
        wallet={"card_ids": []},
    )


CATALOGS_ROOT = Path(__file__).parent.parent / "catalogs"
_SG_CATALOG = CATALOGS_ROOT / "active_sg-core.json"
_BOM_CATALOG = CATALOGS_ROOT / "active_bom-core.json"

pytestmark = pytest.mark.allow_real_catalog


@pytest.mark.skipif(
    not (_SG_CATALOG.exists() and _BOM_CATALOG.exists()),
    reason="requires both real catalogs built (backend/catalogs/active_{sg,bom}-core.json)",
)
def test_singapore_and_mumbai_catalogs_are_disjoint() -> None:
    sg = retrieve_candidates(_spec("SIN"), StubKB())
    bom = retrieve_candidates(_spec("BOM"), StubKB())

    # Anti-vacuity: both catalogs must actually have returned real candidates.
    assert len(sg.pois) > 0
    assert len(bom.pois) > 0

    sg_ids = {p.id for p in sg.pois}
    bom_ids = {p.id for p in bom.pois}
    assert sg_ids.isdisjoint(bom_ids)

    # And the cities on the returned POIs are correctly attributed, not
    # silently inherited from whichever catalog happened to load first.
    assert all(p.city == "Singapore" for p in sg.pois)
    assert all(p.city == "Mumbai" for p in bom.pois)
