"""Offline end-to-end tests for opt-in gateway + MCP wiring in run_pipeline()."""

from __future__ import annotations

import ast
import asyncio
import json
import socket
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from agents.gateway_estimator import evaluate_live_awards
from agents.llm import ScriptedLLMClient
from agents.models import (
    CriticIssue,
    CriticVerdict,
    DraftItinerary,
    EstimatorResult,
    ExplainerOutput,
    ItineraryDay,
    ItineraryItem,
    PipelineStatus,
    TripSpec,
)
from agents.pipeline import run_pipeline
from core.db import SEEDS_DIR, KnowledgeBase, load_kb, seed_database
from core.models import (
    CostedTrip,
    FxRate,
    LoyaltyProgram,
    PointValuation,
    Provenance,
    RecommendationKind,
    SpendCategory,
    SpendLineItem,
    TransferEdge,
    UserWallet,
)
from gateway.travel.adapters.kiwi.adapter import KiwiAdapter
from gateway.travel.adapters.kiwi.tool_policy import ALLOWED_TOOLS as KIWI_ALLOWED
from gateway.travel.adapters.openbnb.budget import OpenBnBCallBudget
from gateway.travel.adapters.openbnb.fixture_transport import FixtureOpenBnBTransport
from gateway.travel.adapters.openbnb.registry import build_openbnb_adapter
from gateway.travel.adapters.seats_aero.adapter import SeatsAeroAdapter
from gateway.travel.adapters.seats_aero.tool_policy import ALLOWED_TOOLS as SEATS_ALLOWED
from gateway.travel.adapters.trivago.adapter import TrivagoAdapter
from gateway.travel.adapters.trivago.tool_policy import ALLOWED_TOOLS as TRIVAGO_ALLOWED
from gateway.travel.contracts import AwardQuote, EvidenceMeta, HotelQuote, TravelerMix
from gateway.travel.errors import TravelGatewayError
from gateway.travel.live_orchestrator import GatewayProviderFactories
from gateway.travel.mcp_readonly import (
    FixtureMcpTransport,
    McpCallBudget,
    McpCircuitBreaker,
    RawMcpToolResponse,
)
from gateway.travel.registry import gateway_live_enabled_from_env

ADAPTERS_DIR = Path(__file__).resolve().parent.parent / "gateway/travel/adapters"
CORE_DIR = Path(__file__).resolve().parent.parent / "core"

PROV = Provenance(
    source_type="manual_curation",
    last_verified=date(2026, 11, 27),
    verified_by="UNVERIFIED",
    needs_verification=True,
    confidence=1.0,
)


@pytest.fixture(autouse=True)
def _block_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("No live network sockets permitted in offline wiring tests")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)


def _seeded_kb(
    tmp_path: Path,
    *,
    with_live_award_edges: bool = False,
    voyager_val_micro: int | None = None,
) -> KnowledgeBase:
    tmp_path.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "tripwise.sqlite"
    seed_database(SEEDS_DIR, db_path)
    kb = load_kb(db_path)
    if not with_live_award_edges:
        return kb
    extra_vals = [val for cid in (c.id for c in kb.cards()) for val in kb.valuations_for_card(cid)]
    if voyager_val_micro is not None:
        extra_vals.append(
            PointValuation(
                id="vp-voyager-override",
                card_id="voyager-prime",
                path="transfer_airline",
                value_micro_major_per_point=voyager_val_micro,
                currency="INR",
                min_points=1000,
                conditions="test baseline",
                provenance=PROV,
            )
        )
    return KnowledgeBase.from_models(
        cards=kb.cards(),
        reward_rules=kb.rules_for_cards([c.id for c in kb.cards()]),
        offers=list(kb._offers),
        point_valuations=extra_vals,
        fx_rates=[
            *kb._fx.values(),
            FxRate(
                base="CAD",
                quote="INR",
                rate_micro=61_000_000,
                as_of=date(2026, 11, 27),
                provenance=PROV,
            ),
        ],
        pois=kb.pois("Singapore"),
        areas=kb.areas("Singapore"),
        sample_flights=kb.sample_flights("DEL", "SIN"),
        sample_hotels=kb.sample_hotels("Singapore"),
        loyalty_programs=[
            *kb.programs(),
            LoyaltyProgram(
                id="aeroplan",
                kind="airline",
                name="Air Canada Aeroplan",
                booking_url="https://seats.aero",
                provenance=PROV,
            ),
        ],
        transfer_edges=[
            *kb._transfer_edges,
            TransferEdge(
                id="voyager-to-aeroplan",
                from_id="voyager-prime",
                to_id="aeroplan",
                ratio_from=1,
                ratio_to=1,
                min_transfer=1000,
                increment=1000,
                transfer_time_hours_typical=0,
                transfer_time_hours_max=1,
                provenance=PROV,
            ),
        ],
        transfer_bonuses=list(kb._transfer_bonuses),
        award_chart_entries=kb.award_entries("DEL", "SIN", "business", "round_trip"),
    )


def _spec(
    *,
    start_date: date = date(2026, 12, 27),
    end_date: date = date(2026, 12, 30),
    travelers: int = 1,
    style: str = "balanced",
) -> TripSpec:
    return TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=start_date,
        end_date=end_date,
        travelers=travelers,
        budget_minor=50_000_000,
        budget_currency="INR",
        style=style,  # type: ignore[arg-type]
        interests=["nature", "food"],
        wallet=UserWallet(
            card_ids=["hdfc-infinia", "axis-atlas"],
            points_balances={"voyager-prime": 150_000},
        ),
        unresolved=[],
    )


def _itinerary(start_date: date = date(2026, 12, 27)) -> DraftItinerary:
    return DraftItinerary(
        hotel_area_id="marina_bay",
        days=[
            ItineraryDay(
                date=start_date,
                items=[
                    ItineraryItem(poi_id="sg-gardens-by-the-bay"),
                    ItineraryItem(poi_id="sg-hawker-maxwell"),
                ],
            ),
            ItineraryDay(date=date(2026, 12, 28), items=[]),
            ItineraryDay(date=date(2026, 12, 29), items=[]),
        ],
        notes=["recorded-fixture-run"],
    )


def _llm(spec: TripSpec, itinerary: DraftItinerary) -> ScriptedLLMClient:
    return ScriptedLLMClient(
        {
            "intake": [spec],
            "planner": [itinerary],
            "critic": [CriticVerdict(passed=True)],
            "explainer": [
                ExplainerOutput(
                    summary="Grounded summary.",
                    itinerary_overview="Grounded itinerary.",
                    payment_overview="Grounded payments.",
                )
            ],
        }
    )


def _round_trip_kiwi_fixture(tmp_path: Path, src_name: str, return_iso: str) -> Path:
    """Extend a real Stage-1 one-way capture with its return leg for round-trip TripSpec tests."""
    raw = json.loads((ADAPTERS_DIR / "kiwi/fixtures" / src_name).read_text())
    inner = json.loads(raw["content"][0]["text"])
    for it in inner.get("itineraries", []):
        it["tripType"] = "round"
        it["inbound"] = {
            "from": "SIN",
            "to": "DEL",
            "departureTime": f"{return_iso}T10:15:00",
            "arrivalTime": f"{return_iso}T14:05:00",
            "durationSeconds": 19800,
            "stops": 0,
            "route": ["SIN", "DEL"],
            "cabinClass": it["outbound"].get("cabinClass", "Business"),
            "segments": [
                {
                    "from": "SIN",
                    "to": "DEL",
                    "departureTime": f"{return_iso}T10:15:00",
                    "arrivalTime": f"{return_iso}T14:05:00",
                    "durationSeconds": 19800,
                    "carrier": "SQ",
                    "carrierName": "Singapore Airlines",
                    "flightNumber": "SQ402",
                    "cabinClass": it["outbound"].get("cabinClass", "Business"),
                }
            ],
        }
    raw["content"][0]["text"] = json.dumps(inner)
    dest = tmp_path / f"rt_{src_name}"
    dest.write_text(json.dumps(raw))
    return dest


def _fixture_factories(
    tmp_path: Path,
    *,
    kiwi_cabin: str = "economy",
    round_trip_return_iso: str | None = "2026-12-30",
) -> GatewayProviderFactories:
    budget_db = tmp_path / "gateway_budget.sqlite"
    kiwi_file = (
        "search_flights_del_sin_biz_live.json"
        if kiwi_cabin == "business"
        else "search_flights_del_sin_eco_live.json"
    )
    kiwi_path = (
        _round_trip_kiwi_fixture(tmp_path, kiwi_file, round_trip_return_iso)
        if round_trip_return_iso is not None
        else ADAPTERS_DIR / f"kiwi/fixtures/{kiwi_file}"
    )
    return GatewayProviderFactories(
        kiwi=lambda pid, now, enabled, db: KiwiAdapter(
            transport=FixtureMcpTransport(
                provider_id="kiwi",
                allowed_tools=KIWI_ALLOWED,
                fixture_paths={"search-flight": kiwi_path},
            ),
            budget=McpCallBudget(budget_db, provider_id="kiwi"),
            plan_id=pid,
            now=now,
            live_enabled=enabled,
            circuit_breaker=McpCircuitBreaker(),
        ),
        trivago=lambda pid, now, enabled, db: TrivagoAdapter(
            transport=FixtureMcpTransport(
                provider_id="trivago",
                allowed_tools=TRIVAGO_ALLOWED,
                fixture_paths={
                    "trivago-accommodation-search": (
                        ADAPTERS_DIR / "trivago/fixtures/search_hotels_singapore_live.json"
                    )
                },
            ),
            budget=McpCallBudget(budget_db, provider_id="trivago"),
            plan_id=pid,
            now=now,
            live_enabled=enabled,
            circuit_breaker=McpCircuitBreaker(),
        ),
        seats_aero=lambda pid, now, enabled, db: SeatsAeroAdapter(
            transport=FixtureMcpTransport(
                provider_id="seats_aero",
                allowed_tools=SEATS_ALLOWED,
                fixture_paths={
                    "get_flights": ADAPTERS_DIR
                    / "seats_aero/fixtures/get_flights_del_sin_live.json"
                },
            ),
            budget=McpCallBudget(budget_db, provider_id="seats_aero"),
            plan_id=pid,
            now=now,
            live_enabled=enabled,
            circuit_breaker=McpCircuitBreaker(),
        ),
    )


def test_default_pipeline_parity_when_gateway_flag_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for var in (
        "TRIPWISE_GATEWAY_LIVE_ENABLED",
        "TRIPWISE_GATEWAY_KILL_SWITCH",
        "TRIPWISE_KIWI_LIVE_ENABLED",
        "TRIPWISE_TRIVAGO_LIVE_ENABLED",
        "TRIPWISE_SEATS_AERO_LIVE_ENABLED",
    ):
        monkeypatch.delenv(var, raising=False)
    assert gateway_live_enabled_from_env() is False

    kb = _seeded_kb(tmp_path)
    spec = _spec(start_date=date(2026, 8, 1), end_date=date(2026, 8, 4), travelers=2)
    itin = DraftItinerary(
        hotel_area_id="marina_bay",
        days=[
            ItineraryDay(
                date=date(2026, 8, 1), items=[ItineraryItem(poi_id="sg-gardens-by-the-bay")]
            ),
            ItineraryDay(date=date(2026, 8, 2), items=[]),
            ItineraryDay(date=date(2026, 8, 3), items=[]),
        ],
    )
    r1 = run_pipeline("DEL to SIN", kb, _llm(spec, itin), booking_date=date(2026, 7, 25))
    r2 = run_pipeline("DEL to SIN", kb, _llm(spec, itin), booking_date=date(2026, 7, 25))
    assert r1.status == PipelineStatus.OK and r2.status == PipelineStatus.OK
    assert r1.report is not None and r2.report is not None
    assert r1.report.travel_inventory is None
    assert r1.report.costed_trip == r2.report.costed_trip
    assert r1.report.optimizer_result == r2.report.optimizer_result
    assert r1.report.transfer_advice == r2.report.transfer_advice
    assert r1.report.assumptions == r2.report.assumptions

    # Gateway kill switch overrides TRIPWISE_GATEWAY_LIVE_ENABLED=1 unconditionally.
    monkeypatch.setenv("TRIPWISE_GATEWAY_LIVE_ENABLED", "1")
    monkeypatch.setenv("TRIPWISE_GATEWAY_KILL_SWITCH", "1")
    assert gateway_live_enabled_from_env() is False


def test_recorded_live_end_to_end_pipeline_flow_with_real_captures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRIPWISE_GATEWAY_LIVE_ENABLED", "1")
    monkeypatch.setenv("TRIPWISE_KIWI_LIVE_ENABLED", "1")
    monkeypatch.setenv("TRIPWISE_TRIVAGO_LIVE_ENABLED", "1")
    monkeypatch.setenv("TRIPWISE_SEATS_AERO_LIVE_ENABLED", "1")
    monkeypatch.delenv("TRIPWISE_GATEWAY_KILL_SWITCH", raising=False)

    # Luxury run on 2026-12-27 exercises Kiwi business + Trivago hotels + Seats.aero Aeroplan award.
    # At 0.40 INR/pt voyager baseline, 75k miles + CAD 74.10 taxes beats 50% of INR 93,741 RT cash.
    spec = _spec(style="luxury", travelers=1)
    itin = _itinerary()
    kb = _seeded_kb(tmp_path, with_live_award_edges=True, voyager_val_micro=400_000)

    resp = run_pipeline(
        "DEL to SIN Dec 27-30 luxury",
        kb,
        _llm(spec, itin),
        booking_date=date(2026, 11, 27),
        gateway_factories=_fixture_factories(tmp_path, kiwi_cabin="business"),
        gateway_budget_db_path=tmp_path / "gateway_budget.sqlite",
    )
    assert resp.status == PipelineStatus.OK
    assert resp.report is not None
    report = resp.report

    # Real Kiwi (INR 93,741 = 9_374_100 paise) and Trivago cheapest INR deal flowed into CostedTrip.
    by_cat = {line.category.value: line for line in report.costed_trip.lines}
    assert by_cat["flights"].amount_minor == 9_374_100
    assert by_cat["flights"].id.startswith("flight:kiwi:")
    assert by_cat["hotels"].amount_minor == 1_993_400
    assert by_cat["hotels"].id.startswith("hotel:trivago:")

    assert any("gateway:flight:kiwi:ok (15 quotes)" in a for a in report.assumptions)
    assert any("gateway:hotel:trivago:ok (73 quotes)" in a for a in report.assumptions)
    assert any("gateway:award:seats_aero:ok (1 quotes)" in a for a in report.assumptions)

    assert report.travel_inventory is not None
    assert report.travel_inventory.flight is not None
    assert report.travel_inventory.flight.provider_id == "kiwi"
    assert report.travel_inventory.hotel is not None
    assert report.travel_inventory.hotel.provider_id == "trivago"
    assert report.travel_inventory.reference_only_awards is False

    # Seats.aero real award propagated into TransferAdvice with VERIFY (blocking) step 1.
    assert report.transfer_advice is not None
    assert report.transfer_advice.recommendation.kind == RecommendationKind.REDEEM
    winning_plan = report.transfer_advice.plans[0]
    assert winning_plan.award.program_id == "aeroplan"
    assert winning_plan.checklist_steps[0].startswith("VERIFY (blocking):")
    assert "https://seats.aero/i/" in winning_plan.checklist_steps[0]
    assert any("needs_verification" in w for w in report.provenance_warnings)

    # At 1.00 INR/pt baseline, 75k one-way miles + fees vs half RT cash (INR 46,870.50) yields
    # PAY_CASH, so better seed round-trip REDEEM advice is preserved rather than clobbered.
    kb_high = _seeded_kb(tmp_path / "high", with_live_award_edges=True)
    resp_high = run_pipeline(
        "DEL to SIN Dec 27-30 luxury high pt baseline",
        kb_high,
        _llm(spec, itin),
        booking_date=date(2026, 11, 27),
        gateway_factories=_fixture_factories(tmp_path, kiwi_cabin="business"),
        gateway_budget_db_path=tmp_path / "gateway_budget_high.sqlite",
    )
    assert resp_high.status == PipelineStatus.OK and resp_high.report is not None
    assert resp_high.report.transfer_advice is not None
    assert resp_high.report.transfer_advice.recommendation.kind == RecommendationKind.REDEEM
    assert resp_high.report.transfer_advice.plans[0].award.program_id != "aeroplan"


def test_raw_one_way_kiwi_capture_for_round_trip_spec_falls_back_to_sample(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRIPWISE_GATEWAY_LIVE_ENABLED", "1")
    monkeypatch.setenv("TRIPWISE_KIWI_LIVE_ENABLED", "1")
    monkeypatch.delenv("TRIPWISE_TRIVAGO_LIVE_ENABLED", raising=False)
    monkeypatch.delenv("TRIPWISE_SEATS_AERO_LIVE_ENABLED", raising=False)
    monkeypatch.delenv("TRIPWISE_GATEWAY_KILL_SWITCH", raising=False)

    spec = _spec(style="luxury", travelers=1)
    itin = _itinerary()
    kb = _seeded_kb(tmp_path)
    resp = run_pipeline(
        "DEL to SIN round-trip",
        kb,
        _llm(spec, itin),
        booking_date=date(2026, 11, 27),
        gateway_factories=_fixture_factories(
            tmp_path, kiwi_cabin="business", round_trip_return_iso=None
        ),
        gateway_budget_db_path=tmp_path / "gateway_budget.sqlite",
    )
    assert resp.status == PipelineStatus.OK
    assert resp.report is not None
    by_cat = {line.category.value: line for line in resp.report.costed_trip.lines}
    assert by_cat["flights"].id == "flight:del-sin-6e-eco"
    assert "gateway:flight:kiwi:fallback:invalid_response" in resp.report.assumptions


def test_async_event_loop_bridge_and_partial_failure_fallbacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRIPWISE_GATEWAY_LIVE_ENABLED", "1")
    monkeypatch.setenv("TRIPWISE_KIWI_LIVE_ENABLED", "1")
    monkeypatch.setenv("TRIPWISE_TRIVAGO_LIVE_ENABLED", "1")
    monkeypatch.setenv("TRIPWISE_SEATS_AERO_LIVE_ENABLED", "1")
    monkeypatch.setenv("TRIPWISE_OPENBNB_ENABLED", "1")
    monkeypatch.delenv("TRIPWISE_GATEWAY_KILL_SWITCH", raising=False)

    class _ErrorTransport:
        def __init__(self, code: str) -> None:
            self.code = code

        async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> RawMcpToolResponse:
            raise TravelGatewayError(self.code, f"simulated {self.code}")  # type: ignore[arg-type]

    budget_db = tmp_path / "b.sqlite"
    factories = GatewayProviderFactories(
        kiwi=lambda pid, now, enabled, db: KiwiAdapter(
            transport=_ErrorTransport("rate_limited"),
            budget=McpCallBudget(budget_db, provider_id="kiwi"),
            plan_id=pid,
            now=now,
            live_enabled=enabled,
            circuit_breaker=McpCircuitBreaker(),
        ),
        trivago=lambda pid, now, enabled, db: TrivagoAdapter(
            transport=FixtureMcpTransport(
                provider_id="trivago",
                allowed_tools=TRIVAGO_ALLOWED,
                fixture_paths={
                    "trivago-accommodation-search": (
                        ADAPTERS_DIR / "trivago/fixtures/search_hotels_singapore_live.json"
                    )
                },
            ),
            budget=McpCallBudget(budget_db, provider_id="trivago"),
            plan_id=pid,
            now=now,
            live_enabled=enabled,
            circuit_breaker=McpCircuitBreaker(),
        ),
        openbnb=lambda pid, now, enabled, db: build_openbnb_adapter(
            transport=FixtureOpenBnBTransport(
                {"airbnb_search": "error_rate_limited"},
                now=now,
            ),
            budget=OpenBnBCallBudget(tmp_path / "openbnb.sqlite"),
            plan_id=pid,
            now=now,
            env={"TRIPWISE_OPENBNB_ENABLED": "1"},
        ),
        seats_aero=lambda pid, now, enabled, db: SeatsAeroAdapter(
            transport=_ErrorTransport("timeout"),
            budget=McpCallBudget(budget_db, provider_id="seats_aero"),
            plan_id=pid,
            now=now,
            live_enabled=enabled,
            circuit_breaker=McpCircuitBreaker(),
        ),
    )

    spec = _spec()
    itin = _itinerary()
    kb = _seeded_kb(tmp_path)

    # Runs cleanly even inside an already-running asyncio event loop (FastAPI request handler case).
    async def _run_inside_loop() -> Any:
        return run_pipeline(
            "DEL to SIN fallback test",
            kb,
            _llm(spec, itin),
            booking_date=date(2026, 11, 27),
            gateway_factories=factories,
        )

    resp = asyncio.run(_run_inside_loop())
    assert resp.status == PipelineStatus.OK
    assert resp.report is not None
    by_cat = {line.category.value: line for line in resp.report.costed_trip.lines}
    # Kiwi 429 fell back to SampleAdapter while Trivago succeeded with real INR deal!
    assert by_cat["flights"].id == "flight:del-sin-6e-eco"
    assert by_cat["hotels"].id.startswith("hotel:trivago:")
    assert "gateway:flight:kiwi:fallback:rate_limited" in resp.report.assumptions
    assert any("gateway:hotel:trivago:ok" in a for a in resp.report.assumptions)
    assert "gateway:hotel:openbnb:fallback:unsupported_domain" in resp.report.assumptions
    assert "gateway:award:seats_aero:fallback:timeout" in resp.report.assumptions


def test_kill_switch_and_complete_hotel_beats_incomplete_on_missing_taxes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRIPWISE_GATEWAY_LIVE_ENABLED", "1")
    monkeypatch.setenv("TRIPWISE_KIWI_LIVE_ENABLED", "1")
    monkeypatch.setenv("TRIPWISE_KIWI_KILL_SWITCH", "1")  # kill switch disables kiwi
    monkeypatch.setenv("TRIPWISE_TRIVAGO_LIVE_ENABLED", "1")
    monkeypatch.setenv("TRIPWISE_SEATS_AERO_LIVE_ENABLED", "1")

    kb = _seeded_kb(tmp_path)
    # Depart > 60 days out triggers clean 60-day anonymous horizon fallback on seats_aero.
    spec = _spec(start_date=date(2027, 4, 1), end_date=date(2027, 4, 4), travelers=1)
    itin = DraftItinerary(
        hotel_area_id="marina_bay",
        days=[
            ItineraryDay(
                date=date(2027, 4, 1), items=[ItineraryItem(poi_id="sg-gardens-by-the-bay")]
            ),
            ItineraryDay(date=date(2027, 4, 2), items=[]),
            ItineraryDay(date=date(2027, 4, 3), items=[]),
        ],
    )

    # Stub hotel adapter returning an incomplete/taxes_uncertain cheaper quote and a complete quote.
    class _StubHotels:
        async def search_hotels(self, request: Any) -> list[HotelQuote]:
            return [
                HotelQuote(
                    id="trivago:cheaper-uncertain",
                    property_id="h1",
                    name="Cheaper Taxes Uncertain",
                    property_kind="hotel",
                    city="Singapore",
                    check_in=request.check_in,
                    check_out=request.check_out,
                    travelers=TravelerMix(adults=1),
                    rooms=1,
                    placement="unknown",
                    total_minor=1_500_000,
                    currency="INR",
                    pay_timing="unknown",
                    evidence=EvidenceMeta(
                        provider_id="trivago",
                        retrieved_at=datetime(2026, 11, 27, tzinfo=UTC),
                        status="live",
                        terms_version="test",
                        completeness="taxes_uncertain",
                        needs_verification=True,
                    ),
                ),
                HotelQuote(
                    id="trivago:complete-taxed",
                    property_id="h2",
                    name="Complete Taxed Hotel",
                    property_kind="hotel",
                    city="Singapore",
                    check_in=request.check_in,
                    check_out=request.check_out,
                    travelers=TravelerMix(adults=1),
                    rooms=1,
                    placement="unknown",
                    total_minor=1_900_000,
                    currency="INR",
                    pay_timing="now",
                    evidence=EvidenceMeta(
                        provider_id="trivago",
                        retrieved_at=datetime(2026, 11, 27, tzinfo=UTC),
                        status="live",
                        terms_version="test",
                        completeness="complete",
                        needs_verification=False,
                    ),
                ),
            ]

    factories = GatewayProviderFactories(
        trivago=lambda pid, now, enabled, db: _StubHotels()  # type: ignore[return-value]
    )
    resp = run_pipeline(
        "DEL to SIN Apr 2027",
        kb,
        _llm(spec, itin),
        booking_date=date(2026, 11, 27),
        gateway_factories=factories,
    )
    assert resp.status == PipelineStatus.OK
    assert resp.report is not None
    assert "gateway:flight:kiwi:disabled" in resp.report.assumptions
    assert (
        "gateway:award:seats_aero:fallback:outside_60d_anonymous_horizon" in resp.report.assumptions
    )
    by_cat = {line.category.value: line for line in resp.report.costed_trip.lines}
    assert by_cat["hotels"].id == "hotel:trivago:complete-taxed"


def test_critic_replan_reuses_live_quotes_and_award_edge_cases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRIPWISE_GATEWAY_LIVE_ENABLED", "1")
    monkeypatch.setenv("TRIPWISE_KIWI_LIVE_ENABLED", "1")
    monkeypatch.setenv("TRIPWISE_TRIVAGO_LIVE_ENABLED", "1")
    monkeypatch.delenv("TRIPWISE_SEATS_AERO_LIVE_ENABLED", raising=False)
    monkeypatch.delenv("TRIPWISE_GATEWAY_KILL_SWITCH", raising=False)

    calls = {"kiwi": 0, "trivago": 0}
    base_factories = _fixture_factories(tmp_path, kiwi_cabin="business")

    def _counting_kiwi(pid: Any, now: Any, enabled: Any, db: Any) -> Any:
        calls["kiwi"] += 1
        assert base_factories.kiwi is not None
        return base_factories.kiwi(pid, now, enabled, db)

    def _counting_trivago(pid: Any, now: Any, enabled: Any, db: Any) -> Any:
        calls["trivago"] += 1
        assert base_factories.trivago is not None
        return base_factories.trivago(pid, now, enabled, db)

    spec = _spec(style="luxury", travelers=1)
    itin1 = _itinerary()
    itin2 = DraftItinerary(
        hotel_area_id="marina_bay",
        days=itin1.days,
        notes=["critic-revised-itinerary"],
    )
    llm = ScriptedLLMClient(
        {
            "intake": [spec],
            "planner": [itin1, itin2],
            "critic": [
                CriticVerdict(
                    passed=False,
                    issues=[
                        CriticIssue(
                            severity="blocking",
                            kind="pace",
                            message="Add an extra landmark.",
                        )
                    ],
                ),
                CriticVerdict(passed=True),
            ],
            "explainer": [
                ExplainerOutput(
                    summary="Grounded summary.",
                    itinerary_overview="Grounded itinerary.",
                    payment_overview="Grounded payments.",
                )
            ],
        }
    )
    kb = _seeded_kb(tmp_path)
    resp = run_pipeline(
        "DEL to SIN critic replan",
        kb,
        llm,
        booking_date=date(2026, 11, 27),
        gateway_factories=GatewayProviderFactories(
            kiwi=_counting_kiwi,
            trivago=_counting_trivago,
        ),
        gateway_budget_db_path=tmp_path / "replan_budget.sqlite",
    )
    assert resp.status == PipelineStatus.OK
    assert resp.report is not None
    assert calls == {"kiwi": 1, "trivago": 1}

    # Zero-mile quotes are safely skipped and first-class quotes keep "first" cabin + KB awards.
    dummy_estimate = EstimatorResult(
        costed_trip=CostedTrip(
            id="t1",
            origin="DEL",
            destination="SIN",
            home_currency="INR",
            booking_date=date(2026, 11, 27),
            trip_start_date=date(2026, 12, 27),
            lines=[
                SpendLineItem(
                    id="flight:rt",
                    label="RT",
                    category=SpendCategory.FLIGHTS,
                    amount_minor=10_000_000,
                    currency="INR",
                    available_channels=["direct_airline"],
                )
            ],
        ),
        assumptions=[],
    )
    zero_quote = AwardQuote(
        id="seats_aero:zero",
        origin="DEL",
        destination="SIN",
        depart_date=date(2026, 12, 27),
        travelers=TravelerMix(adults=1),
        cabin="business",
        program_id="aeroplan",
        miles_total=0,
        fees_minor=0,
        fees_currency="USD",
        evidence=EvidenceMeta(
            provider_id="seats_aero",
            retrieved_at=datetime(2026, 11, 27, tzinfo=UTC),
            status="cached",
            terms_version="test",
            completeness="fees_uncertain",
            needs_verification=True,
        ),
    )
    first_quote = zero_quote.model_copy(
        update={
            "id": "seats_aero:first",
            "cabin": "first",
            "miles_total": 40_000,
            "fees_minor": 5_000,
        }
    )
    assert (
        evaluate_live_awards(
            spec, dummy_estimate, kb, None, [zero_quote], booking_date=date(2026, 11, 27)
        )
        is None
    )
    kb_first = _seeded_kb(tmp_path / "first", with_live_award_edges=True, voyager_val_micro=400_000)
    advice_first = evaluate_live_awards(
        spec, dummy_estimate, kb_first, None, [first_quote], booking_date=date(2026, 11, 27)
    )
    assert advice_first is not None
    assert advice_first.recommendation.kind == RecommendationKind.REDEEM
    assert advice_first.plans[0].award.cabin == "first"

    # With 1.00 INR/pt baseline against 5M one-way cash baseline, 75k miles yields PAY_CASH.
    bad_value_quote = first_quote.model_copy(
        update={"id": "seats_aero:high_miles", "miles_total": 75_000}
    )
    kb_high_eval = _seeded_kb(tmp_path / "high_eval", with_live_award_edges=True)
    advice_cash = evaluate_live_awards(
        spec, dummy_estimate, kb_high_eval, None, [bad_value_quote], booking_date=date(2026, 11, 27)
    )
    assert advice_cash is not None
    assert advice_cash.recommendation.kind == RecommendationKind.PAY_CASH


def test_core_still_imports_zero_gateway_modules() -> None:
    offenders = []
    for py_file in CORE_DIR.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                alias.name == "gateway" or alias.name.startswith("gateway.") for alias in node.names
            ):
                offenders.append(str(py_file))
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and (node.module == "gateway" or node.module.startswith("gateway."))
            ):
                offenders.append(str(py_file))
    assert offenders == []
