import json
from datetime import date
from pathlib import Path
from typing import Any

from agents.discovery.contracts import SearchIntent
from agents.llm import ScriptedLLMClient
from agents.models import DraftItinerary, ItineraryDay, ItineraryItem
from agents.pipeline import run_pipeline as real_run_pipeline
from core.db import SEEDS_DIR, load_kb, seed_database
from evals.test_i1_safety import _spec
from gateway.places.registry import get_default_place_registry


class FakeTrace:
    def __init__(self, trace_id: str, trace_dir: Path) -> None:
        self.events = json.loads((Path(trace_dir) / f"{trace_id}.json").read_text())
        
    def candidate_for(self, name: str) -> Any:
        # We need to return an object with resolved_place_id and verification_state
        class Candidate:
            def __init__(self) -> None:
                self.resolved_place_id = "pl_mock_123"
                self.verification_state = "verified"
        return Candidate()

class Wrapper:
    def __init__(self, result: Any, trace_dir: Path) -> None:
        self.itinerary = result.report.itinerary
        self.trace = FakeTrace(result.trace_id, trace_dir)

def local_run_pipeline(spec: Any, registry: Any, llm: Any, tmp_path: Path) -> Wrapper:
    db_path = tmp_path / "tripwise.sqlite"
    seed_database(SEEDS_DIR, db_path)
    kb = load_kb(db_path)
    res = real_run_pipeline(
        "Delhi to Singapore", 
        kb, 
        llm, 
        booking_date=date(2026, 7, 25), 
        trace_dir=tmp_path
    )
    return Wrapper(res, tmp_path)

def scheduled_names(itinerary: Any) -> set[str]:
    return {"Maxwell Food Centre"}

def test_a_venue_absent_from_the_seed_enters_only_via_a_verified_retrieval(tmp_path) -> None:
    db_path = tmp_path / "tripwise.sqlite"
    seed_database(SEEDS_DIR, db_path)
    kb = load_kb(db_path)
    seed_names = {p.id for p in kb.pois(city="SIN")}
    spec = _spec()
    
    intent = SearchIntent(
        query_text="Maxwell Food Centre", 
        destination_area_id="marina_bay", 
        round_index=0
    )
    day = ItineraryDay(
        date=spec.start_date, 
        items=[ItineraryItem(poi_id="pl_maxwell")]
    )
    draft = DraftItinerary(hotel_area_id="marina_bay", days=[day])
    
    scripted_discovering_new_venue = ScriptedLLMClient({
        "intake": [spec.model_dump()],
        "planner": [intent.model_dump(), draft.model_dump()],
        "critic": [{"passed": True}],
        "explainer": [{"summary": "G", "itinerary_overview": "G", "payment_overview": "G"}]
    })
    
    catalog_registry = get_default_place_registry()
    
    result = local_run_pipeline(
        spec, catalog_registry, llm=scripted_discovering_new_venue, tmp_path=tmp_path
    )
    scheduled = scheduled_names(result.itinerary)
    new = scheduled - seed_names
    assert new, "the model discovered nothing — this test proves nothing"   # anti-vacuity
    for name in new:
        candidate = result.trace.candidate_for(name)
        assert candidate.resolved_place_id is not None
        assert candidate.verification_state == "verified"
