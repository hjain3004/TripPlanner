"""Replay local hotel/flight evidence through sign-in, planning and amendment.

Usage: python -m evals.demo_gondola_hotel_plan /path/to/normalized-quote.json \
    [--flight-observations /path/to/observations.json]

No provider/model call is made. SQLite is task-local, the model is scripted,
and the retained quote's original provenance/timestamps are preserved. The
demonstration also replays authored weather context and a scoped CP4 amendment.
Do not pass raw provider responses or credentials. No input document is copied
into the repo.
"""

from __future__ import annotations

import argparse
import copy
import json
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

import api.confirmed_planning as planning_api
import api.main as api_main
import evals.a4_support as support
from accounts.store import AccountStore
from agents.models import DraftItinerary, ItineraryDay
from api.auth import get_store
from core.models import UserWallet
from evals.test_travel_gateway_parity import _kb
from gateway.travel.adapters.gondola.budget import GondolaCallBudget
from gateway.travel.adapters.gondola.dated_hotel_adapter import GondolaDatedHotelAdapter
from gateway.travel.contracts import (
    FlexibleFlightSearchRequest,
    FlightPriceObservation,
    HotelQuote,
    HotelSearchRequest,
)
from gateway.weather.adapter import OpenMeteoWeatherAdapter
from gateway.weather.budget import WeatherCallBudget
from gateway.weather.contracts import WeatherLocation
from gateway.weather.planning import WeatherContextService
from gateway.weather.transport import FIXTURES_DIR, FixtureWeatherTransport


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("normalized_quote", type=Path)
    parser.add_argument("--flight-observations", type=Path)
    args = parser.parse_args()
    quote = HotelQuote.model_validate_json(args.normalized_quote.read_text())
    flights = (
        [
            FlightPriceObservation.model_validate(item)
            for item in json.loads(args.flight_observations.read_text())
        ]
        if args.flight_observations
        else []
    )
    if quote.city.casefold() != "singapore" or quote.evidence.provider_id != "gondola":
        parser.error("This demonstration requires a normalized Singapore Gondola quote")
    if not quote.evidence.needs_verification:
        parser.error("The observed Gondola contract remains verify-required")
    root = Path(tempfile.mkdtemp(prefix="gondola-plan-demo-"))
    kb = _kb(root)
    # The retained hotel/flight capture is for 2027-02-10..13, while the shipped
    # authored climate fixture covers 2027-02-01..07. Shift that authored fixture
    # into a task-local replay file so the demo exercises the exact trip window;
    # its provenance remains synthetic and is never presented as provider output.
    weather_fixture_dir = root / "weather-fixtures"
    weather_fixture_dir.mkdir()
    climate = json.loads((FIXTURES_DIR / "singapore_ok.climate.json").read_text())
    payload = climate["payload"]
    original_start = date.fromisoformat(payload["date_range"]["start"])
    shift = quote.check_in - original_start
    payload["date_range"]["start"] = (original_start + shift).isoformat()
    payload["date_range"]["end"] = (
        date.fromisoformat(payload["date_range"]["end"]) + shift
    ).isoformat()
    for day in payload["daily"]:
        day["time"] = (date.fromisoformat(day["time"]) + shift).isoformat()
    payload["daily"] = payload["daily"][: (quote.check_out - quote.check_in).days + 1]
    (weather_fixture_dir / "combined.climate.json").write_text(json.dumps(climate) + "\n")
    weather_service = WeatherContextService(
        OpenMeteoWeatherAdapter(
            transport=FixtureWeatherTransport("combined", fixture_dir=weather_fixture_dir),
            budget=WeatherCallBudget(root / "weather-calls.sqlite"),
            plan_id="gondola-combined-demo",
            now=lambda: quote.evidence.retrieved_at,
            enabled=True,
        ),
        location_provider=lambda _iata: WeatherLocation(
            latitude=1.29, longitude=103.85, label="Singapore"
        ),
        now=lambda: quote.evidence.retrieved_at,
    )
    mp = pytest.MonkeyPatch()

    class ReplayAdapter(GondolaDatedHotelAdapter):
        capabilities = GondolaDatedHotelAdapter.capabilities.model_copy(
            update={"domains": {"hotel", "flight_trend"} if flights else {"hotel"}}
        )

        async def search_hotels(self, request: HotelSearchRequest) -> list[HotelQuote]:
            return [quote]

        async def search_flight_price_trends(
            self, request: FlexibleFlightSearchRequest
        ) -> list[FlightPriceObservation]:
            return flights

    class NoTransport:
        async def call_tool(
            self, tool_name: str, arguments: dict[str, object]
        ) -> dict[str, object]:
            raise AssertionError("Offline replay must not dispatch provider calls")

    factory = planning_api.build_travel_service

    def replay_factory(kb: object, *, plan_id: str, now: object, country: str = "IN") -> object:
        replay = ReplayAdapter(
            transport=NoTransport(),
            budget=GondolaCallBudget(),
            plan_id=plan_id,
            now=lambda: quote.evidence.retrieved_at,
            live_enabled=True,
            origin="live_capture_replay",
        )
        return factory(kb, plan_id=plan_id, now=now, country=country, gondola_hotel_adapter=replay)

    original_spec = support._spec
    try:
        payloads = copy.deepcopy(support.INTERVIEW_PAYLOADS)
        payloads[0].update(
            start_date=quote.check_in.isoformat(),
            end_date=quote.check_out.isoformat(),
            travelers=quote.travelers.adults,
        )
        payloads[1]["adults"] = quote.travelers.adults
        mp.setattr(support, "INTERVIEW_PAYLOADS", payloads)
        mp.setattr(
            support,
            "_spec",
            lambda wallet: original_spec(wallet).model_copy(
                update={
                    "start_date": quote.check_in,
                    "end_date": quote.check_out,
                    "travelers": quote.travelers.adults,
                }
            ),
        )
        mp.setattr(
            support,
            "_itinerary",
            lambda: DraftItinerary(
                hotel_area_id="marina_bay",
                days=[
                    ItineraryDay(date=quote.check_in + timedelta(days=i), items=[])
                    for i in range((quote.check_out - quote.check_in).days)
                ],
            ),
        )
        mp.setattr(api_main, "get_kb", lambda: kb)
        mp.setattr(api_main, "get_weather_context_service", lambda: weather_service)
        mp.setattr(planning_api, "build_travel_service", replay_factory)
        kit = support.PlanningKit(mp, root)
        mp.setattr(api_main, "get_booking_date", lambda: datetime.now(UTC).date())
        client, _ = support.signed_in_client(root, email="gondola-demo@example.invalid")
        session, job = support.finished_plan(client, kit, wallet=UserWallet(card_ids=[]))
        inventory = job["report"]["travel_inventory"]
        alternate = next(q for q in inventory["alternatives"] if q["provider_id"] == "gondola")
        saved = client.post(
            "/account/trips",
            headers=support.csrf(client),
            json={"session_id": session["id"], "client_event_id": "save-gondola-demo"},
        )
        assert saved.status_code == 201, saved.text
        reopened = AccountStore.open(root / "accounts.sqlite")
        api_main.app.dependency_overrides[get_store] = lambda: reopened
        revision = client.get(f"/account/trips/{saved.json()['trip']['id']}/revisions/1")
        assert revision.status_code == 200, revision.text
        restored = revision.json()["report"]["travel_inventory"]["alternatives"]
        assert alternate in restored
        flight_rows = inventory.get("flight_observations", [])
        assert revision.json()["report"]["travel_inventory"]["flight_observations"] == flight_rows
        assert job["report"]["weather_context"]["status"] == "available"
        assert revision.json()["report"]["weather_context"] == job["report"]["weather_context"]

        # Exercise one deterministic CP4 amendment through the authenticated API.  The
        # scoped replan must retain the provider evidence and make no replay transport call.
        initialized = client.post(
            f"/planning/sessions/{session['id']}/workspace",
            headers=support.csrf(client),
            json={"source": "job"},
        )
        assert initialized.status_code == 200, initialized.text
        workspace = client.get(f"/planning/sessions/{session['id']}/workspace").json()
        current_session = client.get(f"/planning/sessions/{session['id']}").json()
        proposed = client.post(
            f"/planning/sessions/{session['id']}/actions",
            headers=support.csrf(client),
            json={
                "client_event_id": "combined-scoped-replan-propose",
                "expected_session_version": current_session["version"],
                "expected_workspace_version": workspace["version"],
                "action": {
                    "kind": "scoped_itinerary_replan",
                    "scope": "dates",
                    "affected_dates": [quote.check_in.isoformat()],
                    "day_theme": "nature escape",
                },
            },
        )
        assert proposed.status_code == 200, proposed.text
        after_proposal = client.get(f"/planning/sessions/{session['id']}/workspace").json()
        after_session = client.get(f"/planning/sessions/{session['id']}").json()
        approved = client.post(
            f"/planning/sessions/{session['id']}/actions/{proposed.json()['proposal_id']}/approve",
            headers=support.csrf(client),
            json={
                "client_event_id": "combined-scoped-replan-approve",
                "expected_session_version": after_session["version"],
                "expected_workspace_version": after_proposal["version"],
            },
        )
        assert approved.status_code == 200, approved.text
        amended = client.get(f"/planning/sessions/{session['id']}/workspace").json()["report"]
        assert amended["travel_inventory"]["flight_observations"] == flight_rows
        assert amended["weather_context"] == job["report"]["weather_context"]
        print(
            json.dumps(
                {
                    "execution": (
                        "authenticated API and SQLite; recorded quote replay; scripted model"
                    ),
                    "plan_status": job["status"],
                    "property_name": alternate["property_name"],
                    "room_name": alternate["room_name"],
                    "source_amount_minor": alternate["source_amount_minor"],
                    "source_currency": alternate["source_currency"],
                    "cost_eligible": False,
                    "budget_provider": inventory["hotel"]["provider_id"],
                    "saved_and_reopened": True,
                    "timestamps_preserved": True,
                    "weather_replayed": True,
                    "cp4_scoped_amendment": "approved",
                    "provider_calls_after_replay": 0,
                    "provider_calls": 0,
                    "flight_observations": [
                        {
                            key: row[key]
                            for key in (
                                "carrier_name",
                                "observed_total_minor",
                                "currency",
                                "price_scope",
                                "outbound_departure_local",
                                "return_itinerary_confirmed",
                                "is_bookable",
                            )
                        }
                        for row in flight_rows
                    ],
                },
                indent=2,
            )
        )
    finally:
        api_main.app.dependency_overrides.clear()
        mp.undo()


if __name__ == "__main__":
    main()
