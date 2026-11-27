"""Offline replay (and gated manual live smoke) for TripPlanner's keyless MCP travel adapters."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from core.db import SEEDS_DIR, KnowledgeBase, load_kb, seed_database
from core.explain.audit import build_audit_certificate
from core.models import (
    AwardChartEntry,
    AwardTarget,
    CostedTrip,
    FxRate,
    LoyaltyProgram,
    OptimizationPrefs,
    Provenance,
    SpendCategory,
    SpendLineItem,
    TransferEdge,
    UserWallet,
)
from core.optimizer import optimize
from core.transfer.pathfinder import find_transfer_plans
from core.transfer.pooling import PoolingConfig
from gateway.travel.adapters.kiwi.adapter import KiwiAdapter, build_live_kiwi_transport
from gateway.travel.adapters.kiwi.tool_policy import ALLOWED_TOOLS as KIWI_ALLOWED
from gateway.travel.adapters.seats_aero.adapter import (
    SeatsAeroAdapter,
    build_live_seats_aero_transport,
)
from gateway.travel.adapters.seats_aero.tool_policy import ALLOWED_TOOLS as SEATS_ALLOWED
from gateway.travel.adapters.trivago.adapter import TrivagoAdapter, build_live_trivago_transport
from gateway.travel.adapters.trivago.tool_policy import ALLOWED_TOOLS as TRIVAGO_ALLOWED
from gateway.travel.contracts import (
    AwardQuote,
    AwardSearchRequest,
    FlightQuote,
    FlightSearchRequest,
    HotelQuote,
    HotelSearchRequest,
    TravelerMix,
)
from gateway.travel.mcp_readonly import FixtureMcpTransport, McpCallBudget
from gateway.travel.registry import get_default_travel_registry

ADAPTERS_DIR = Path(__file__).resolve().parent.parent / "adapters"
SMOKE_NOW = datetime(2026, 11, 27, 9, 45, tzinfo=UTC)


def build_fixture_adapters(
    *,
    plan_id: str = "smoke-del-sin-2026-12-27",
    kiwi_cabin: str = "economy",
    now: datetime = SMOKE_NOW,
) -> tuple[SeatsAeroAdapter, TrivagoAdapter, KiwiAdapter]:
    kiwi_fixture = (
        "search_flights_del_sin_biz_live.json"
        if kiwi_cabin == "business"
        else "search_flights_del_sin_eco_live.json"
    )
    seats_transport = FixtureMcpTransport(
        provider_id="seats_aero",
        allowed_tools=SEATS_ALLOWED,
        fixture_paths={
            "get_flights": ADAPTERS_DIR / "seats_aero/fixtures/get_flights_del_sin_live.json",
            "get_capabilities": ADAPTERS_DIR / "seats_aero/fixtures/get_capabilities_live.json",
            "get_flight_details": ADAPTERS_DIR / "seats_aero/fixtures/get_flight_details_live.json",
        },
    )
    trivago_transport = FixtureMcpTransport(
        provider_id="trivago",
        allowed_tools=TRIVAGO_ALLOWED,
        fixture_paths={
            "trivago-accommodation-search": (
                ADAPTERS_DIR / "trivago/fixtures/search_hotels_singapore_live.json"
            ),
        },
    )
    kiwi_transport = FixtureMcpTransport(
        provider_id="kiwi",
        allowed_tools=KIWI_ALLOWED,
        fixture_paths={
            "search-flight": ADAPTERS_DIR / f"kiwi/fixtures/{kiwi_fixture}",
        },
    )
    return (
        SeatsAeroAdapter(
            transport=seats_transport,
            budget=McpCallBudget(provider_id="seats_aero"),
            plan_id=plan_id,
            now=lambda: now,
            live_enabled=True,
        ),
        TrivagoAdapter(
            transport=trivago_transport,
            budget=McpCallBudget(provider_id="trivago"),
            plan_id=plan_id,
            now=lambda: now,
            live_enabled=True,
        ),
        KiwiAdapter(
            transport=kiwi_transport,
            budget=McpCallBudget(provider_id="kiwi"),
            plan_id=plan_id,
            now=lambda: now,
            live_enabled=True,
        ),
    )


def evaluate_real_quotes_in_kernel(
    *,
    flight_quotes: Sequence[FlightQuote],
    hotel_quotes: Sequence[HotelQuote],
    award_quotes: Sequence[AwardQuote],
    db_dir: Path,
    booking_date: date = date(2026, 11, 27),
) -> dict[str, object]:
    """Carry normalized gateway quotes into TripPlanner's deterministic optimizer & pathfinder."""
    if not flight_quotes or not hotel_quotes or not award_quotes:
        raise ValueError("Non-empty flight, hotel, and award quotes required for kernel flow")

    best_flight = min(flight_quotes, key=lambda q: (q.total_minor, len(q.segments), q.id))
    best_hotel = min(hotel_quotes, key=lambda q: (q.total_minor, q.id))
    best_award = min(award_quotes, key=lambda q: (q.miles_total, q.fees_minor, q.id))

    db_path = db_dir / "smoke_tripwise.sqlite"
    seed_database(SEEDS_DIR, db_path)
    base_kb = load_kb(db_path)

    trip = CostedTrip(
        id="smoke-del-sin",
        origin="DEL",
        destination="SIN",
        home_currency="INR",
        booking_date=booking_date,
        trip_start_date=best_flight.segments[0].departure_at.date(),
        lines=[
            SpendLineItem(
                id="flight-cash",
                label=f"Kiwi Flight {best_flight.segments[0].flight_number}",
                category=SpendCategory.FLIGHTS,
                amount_minor=best_flight.total_minor,
                currency=best_flight.currency,
                available_channels=best_flight.purchasable_channels or ["ota_generic"],
            ),
            SpendLineItem(
                id="hotel-cash",
                label=f"Trivago Stay {best_hotel.name}",
                category=SpendCategory.HOTELS,
                amount_minor=best_hotel.total_minor,
                currency=best_hotel.currency,
                available_channels=best_hotel.purchasable_channels or ["ota_generic"],
            ),
        ],
    )
    wallet = UserWallet(
        card_ids=["hdfc-infinia", "axis-atlas"],
        points_balances={"hdfc-infinia": 50_000, "axis-atlas": 40_000},
    )
    opt_result = optimize(trip, wallet, base_kb)
    audit_cert = build_audit_certificate(
        trip, wallet, base_kb, opt_result, prefs=OptimizationPrefs()
    )

    prov = Provenance(
        source_type="manual_curation",
        last_verified=booking_date,
        verified_by="UNVERIFIED",
        needs_verification=best_award.evidence.needs_verification,
        confidence=1.0,
    )
    prog_id = best_award.program_id
    award_kb = KnowledgeBase.from_models(
        cards=[],
        reward_rules=[],
        offers=[],
        point_valuations=[],
        fx_rates=[
            FxRate(
                base="CAD", quote="INR", rate_micro=61_000_000, as_of=booking_date, provenance=prov
            ),
            FxRate(
                base="USD", quote="INR", rate_micro=84_000_000, as_of=booking_date, provenance=prov
            ),
            FxRate(
                base="SGD", quote="INR", rate_micro=63_200_000, as_of=booking_date, provenance=prov
            ),
        ],
        loyalty_programs=[
            LoyaltyProgram(
                id=prog_id,
                kind="airline",
                name=prog_id.title(),
                booking_url=best_award.evidence.deep_link_url,
                provenance=prov,
            ),
            LoyaltyProgram(
                id="hdfc-infinia",
                kind="card_currency",
                name="HDFC Infinia",
                provenance=prov,
            ),
            LoyaltyProgram(
                id="axis-atlas",
                kind="card_currency",
                name="Axis Atlas",
                provenance=prov,
            ),
        ],
        transfer_edges=[
            TransferEdge(
                id=f"hdfc-to-{prog_id}",
                from_id="hdfc-infinia",
                to_id=prog_id,
                ratio_from=1,
                ratio_to=1,
                min_transfer=1000,
                increment=1000,
                transfer_time_hours_typical=2,
                transfer_time_hours_max=24,
                provenance=prov,
            ),
            TransferEdge(
                id=f"atlas-to-{prog_id}",
                from_id="axis-atlas",
                to_id=prog_id,
                ratio_from=1,
                ratio_to=1,
                min_transfer=1000,
                increment=1000,
                transfer_time_hours_typical=4,
                transfer_time_hours_max=24,
                provenance=prov,
            ),
        ],
        transfer_bonuses=[],
        award_chart_entries=[
            AwardChartEntry(
                id=best_award.id,
                program_id=prog_id,
                origin=best_award.origin,
                destination=best_award.destination,
                cabin=best_award.cabin,
                trip_type="one_way",
                miles_cost=best_award.miles_total,
                fees_minor=best_award.fees_minor,
                fees_currency=best_award.fees_currency,
                provenance=prov,
            )
        ],
    )
    advice = find_transfer_plans(
        target=AwardTarget(
            origin="DEL",
            destination="SIN",
            cabin=best_award.cabin,
            trip_type="one_way",
            travelers=1,
            home_currency="INR",
        ),
        wallet=wallet,
        kb=award_kb,
        baseline_valuations={"hdfc-infinia": 1_000_000, "axis-atlas": 950_000},
        cash_price_minor=best_flight.total_minor,
        on_date=booking_date,
        allow_pooling=True,
        pooling_config=PoolingConfig(deadline_hours=48, max_transfers=3),
    )

    winning_plan = advice.plans[0] if advice.plans else None
    return {
        "mode": "recorded_replay",
        "kiwi_quotes": len(flight_quotes),
        "trivago_quotes": len(hotel_quotes),
        "seats_aero_quotes": len(award_quotes),
        "selected_flight_id": best_flight.id,
        "selected_flight_total_minor": best_flight.total_minor,
        "selected_hotel_id": best_hotel.id,
        "selected_hotel_total_minor": best_hotel.total_minor,
        "selected_award_id": best_award.id,
        "selected_award_miles": best_award.miles_total,
        "optimizer_effective_cost_minor": opt_result.effective_cost_minor,
        "audit_trip_snapshot_hash": audit_cert.trip_snapshot_hash,
        "audit_result_hash": audit_cert.result_hash,
        "transfer_recommendation": advice.recommendation.kind.value,
        "transfer_checklist_first_step": (
            winning_plan.checklist_steps[0]
            if winning_plan and winning_plan.checklist_steps
            else None
        ),
    }


async def run_smoke(*, live: bool, work_dir: Path) -> dict[str, object]:
    registry = get_default_travel_registry()
    if live:
        live_now = datetime.now(UTC)
        depart_date = live_now.date() + timedelta(days=30)
        checkout_date = depart_date + timedelta(days=3)
        award_date = depart_date + timedelta(days=1)
        seats = SeatsAeroAdapter(
            transport=build_live_seats_aero_transport(),
            budget=McpCallBudget(provider_id="seats_aero"),
            plan_id="live-smoke-free-mcp",
            now=lambda: live_now,
            live_enabled=True,
        )
        trivago = TrivagoAdapter(
            transport=build_live_trivago_transport(),
            budget=McpCallBudget(provider_id="trivago"),
            plan_id="live-smoke-free-mcp",
            now=lambda: live_now,
            live_enabled=True,
        )
        kiwi = KiwiAdapter(
            transport=build_live_kiwi_transport(),
            budget=McpCallBudget(provider_id="kiwi"),
            plan_id="live-smoke-free-mcp",
            now=lambda: live_now,
            live_enabled=True,
        )
        booking_date = live_now.date()
    else:
        depart_date = date(2026, 12, 27)
        checkout_date = date(2026, 12, 30)
        award_date = date(2026, 12, 28)
        booking_date = date(2026, 11, 27)
        seats, trivago, kiwi = build_fixture_adapters()

    flight_quotes = await kiwi.search_flights(
        FlightSearchRequest(
            origin="DEL",
            destination="SIN",
            depart_date=depart_date,
            travelers=TravelerMix(adults=1),
            cabin="economy",
            currency="INR",
        )
    )
    hotel_quotes = await trivago.search_hotels(
        HotelSearchRequest(
            city="Singapore",
            check_in=depart_date,
            check_out=checkout_date,
            travelers=TravelerMix(adults=2),
            rooms=1,
            style="balanced",
            currency="INR",
        )
    )
    award_quotes = await seats.search_awards(
        AwardSearchRequest(
            origin="DEL",
            destination="SIN",
            depart_date=award_date,
            travelers=TravelerMix(adults=1),
            cabin="business",
        )
    )
    summary = evaluate_real_quotes_in_kernel(
        flight_quotes=flight_quotes,
        hotel_quotes=hotel_quotes,
        award_quotes=award_quotes,
        db_dir=work_dir,
        booking_date=booking_date,
    )
    summary["registry_providers"] = [e.provider_id for e in registry.entries]
    if live:
        summary["mode"] = "live_bounded"
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke TripPlanner keyless MCP travel adapters.")
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="Replay recorded live fixtures offline (default mode).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Execute 1 bounded live call per provider instead of offline fixture replay.",
    )
    parser.add_argument(
        "--acknowledge-live",
        action="store_true",
        help="Required confirmation flag when --live is passed.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.live and not args.acknowledge_live:
        raise SystemExit("--live requires --acknowledge-live confirmation.")
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        summary = asyncio.run(run_smoke(live=args.live, work_dir=Path(tmp)))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
