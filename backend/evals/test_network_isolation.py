import socket
from datetime import date
from pathlib import Path

import pytest

from agents.llm import ScriptedLLMClient
from agents.models import (
    CriticVerdict,
    DraftItinerary,
    ExplainerOutput,
    ItineraryDay,
    ItineraryItem,
    PipelineStatus,
    TripSpec,
)
from agents.pipeline import run_pipeline
from core.db import load_kb
from core.models import UserWallet


def _guard_network(*args, **kwargs):
    raise RuntimeError(
        "Non-negotiable #2 violation: deterministic request path touched the network!"
    )


def test_the_request_path_makes_no_network_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1. Patch socket layer to fail closed on any network attempt
    monkeypatch.setattr(socket.socket, "connect", _guard_network)
    monkeypatch.setattr(socket, "create_connection", _guard_network)

    # 2. Setup offline KB and scripted LLM
    kb = load_kb()

    # Trip to an unprovisioned destination (e.g. PAR / Paris with empty catalogs dir)
    empty_catalogs = tmp_path / "empty_catalogs"
    empty_catalogs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "agents.retrieval.Path",
        lambda p: empty_catalogs if p == "catalogs" else Path(p),
    )
    monkeypatch.setattr(
        "agents.pipeline.Path",
        lambda p: empty_catalogs if p == "catalogs" else Path(p),
    )

    spec = TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="PAR",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 5),
        travelers=2,
        budget_minor=25000000,
        budget_currency="INR",
        style="balanced",
        interests=["culture"],
        wallet=UserWallet(
            card_ids=["hdfc-infinia"],
            points_balances={},
        ),
    )
    itinerary = DraftItinerary(
        hotel_area_id="le_marais",
        days=[
            ItineraryDay(
                date=date(2026, 9, 1),
                items=[
                    ItineraryItem(poi_id="par-eiffel-tower"),
                ],
            ),
            ItineraryDay(date=date(2026, 9, 2), items=[]),
        ],
    )

    llm = ScriptedLLMClient(
        {
            "intake": [spec],
            "planner": [itinerary],
            "critic": [CriticVerdict(passed=True)],
            "explainer": [
                ExplainerOutput(
                    summary="Grounded Paris summary.",
                    itinerary_overview="Paris itinerary.",
                    payment_overview="Payment overview.",
                )
            ],
        }
    )

    # 3. Run pipeline against unprovisioned destination
    resp = run_pipeline(
        raw_request="Delhi to Paris Sep 1-5",
        kb=kb,
        llm=llm,
        booking_date=date(2026, 8, 1),
        trace_dir=tmp_path / "traces",
    )

    # 4. Assert clean completion with honest capability reporting
    assert resp.status == PipelineStatus.OK
    assert resp.report is not None
    assert resp.report.region_capability is not None
    assert resp.report.region_capability.catalog_status == "absent"
    assert resp.report.region_capability.place_count == 0


def test_network_guard_fails_on_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "connect", _guard_network)
    with pytest.raises(RuntimeError, match="Non-negotiable #2 violation"):
        s = socket.socket()
        s.connect(("1.1.1.1", 80))
