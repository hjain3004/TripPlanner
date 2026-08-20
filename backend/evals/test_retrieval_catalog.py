from datetime import date
from pathlib import Path

import pytest

from agents.retrieval import retrieve_candidates
from core.db import KnowledgeBase, load_kb
from core.models import OptimizationPrefs, UserWallet
from core.trip_models import TripSpec


@pytest.fixture
def spec() -> TripSpec:
    return TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        travelers=2,
        budget_minor=25000000,
        budget_currency="INR",
        style="balanced",
        interests=[],
        pace="moderate",
        wallet=UserWallet(card_ids=["hdfc-infinia"]),
        optimization=OptimizationPrefs(),
    )


@pytest.fixture
def kb() -> KnowledgeBase:
    return load_kb()


def test_catalog_places_reach_the_retrieval_context(
    active_catalog: Path, spec: TripSpec, kb: KnowledgeBase
) -> None:
    ctx = retrieve_candidates(spec, kb, catalog=active_catalog)
    assert len(ctx.poi_rows) > 4, "still serving only the seeded POIs"


def test_seeded_pois_and_catalog_places_coexist_without_duplicates(
    active_catalog: Path, spec: TripSpec, kb: KnowledgeBase
) -> None:
    ctx = retrieve_candidates(spec, kb, catalog=active_catalog)
    ids = [r.split("|")[0].strip() for r in ctx.poi_rows]
    assert len(ids) == len(set(ids))


def test_a_catalog_place_without_hours_is_marked_verify_required(
    active_catalog: Path, spec: TripSpec, kb: KnowledgeBase
) -> None:
    """Spec 5.4 survives the mapping — unknown hours never become open."""
    ctx = retrieve_candidates(spec, kb, catalog=active_catalog)
    print("POI ROWS:", ctx.poi_rows)
    rows = [r for r in ctx.poi_rows if "verify" in r.lower()]
    assert rows


def test_provenance_survives_the_mapping(
    active_catalog: Path, spec: TripSpec, kb: KnowledgeBase
) -> None:
    ctx = retrieve_candidates(spec, kb, catalog=active_catalog)
    assert all(r.licence_id for r in ctx.poi_provenance)


def test_retrieval_falls_back_to_seeds_when_no_catalog_is_active(
    tmp_path: Path, spec: TripSpec, kb: KnowledgeBase
) -> None:
    """Spec 12: a missing catalog degrades, it does not crash."""
    ctx = retrieve_candidates(spec, kb, catalog=tmp_path / "absent.json")
    assert len(ctx.poi_rows) == 4


def test_core_still_does_not_import_gateway() -> None:
    """The mapping belongs in agents/. Existing boundary tests must stay green."""
    from pathlib import Path

    from evals.test_catalog_boundary import _imports

    assert _imports(Path(__file__).parent.parent / "core", {"gateway", "agents", "api"}) == []
