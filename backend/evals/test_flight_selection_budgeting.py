"""Focused authenticated regressions for explicit flight selection and budgeting."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from accounts.store import AccountStore
from agents.models import FinalReport
from api.auth import get_store
from api.main import app
from api.post_plan import _matches_retained_flight_request
from evals.a4_support import PlanningKit, csrf, finished_plan, second_client, signed_in_client
from gateway.travel.contracts import (
    EvidenceMeta,
    FlightQuote,
    FlightSearchRequest,
    FlightSegment,
    TravelerMix,
)


@pytest.fixture(autouse=True)
def _clear_overrides() -> None:
    yield
    app.dependency_overrides.clear()


def _workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, AccountStore, dict[str, Any], dict[str, Any]]:
    client, store = signed_in_client(tmp_path, email="flight-owner@example.com")
    kit = PlanningKit(monkeypatch, tmp_path)
    session, _job = finished_plan(client, kit)
    initialized = client.post(
        f"/planning/sessions/{session['id']}/workspace",
        headers=csrf(client),
        json={"source": "job"},
    )
    assert initialized.status_code == 200, initialized.text
    return client, store, session, initialized.json()


def _selection(quote_id: str | None, *, source: str) -> dict[str, Any]:
    if source == "inventory_quote":
        assert quote_id is not None
        return {"kind": "flight_selection", "source": source, "quote_id": quote_id}
    return {
        "kind": "flight_selection",
        "source": source,
        "quote_id": quote_id,
        "amount_minor": 51000,
        "currency": "INR",
        "covers": "round-trip party fare as stated by the traveler",
        "amount_scope": "party_total",
        "payment_channel": "direct_airline",
        "assumptions": ["traveler supplied one party total"],
    }


def test_flight_preview_confirm_save_reopen_and_owner_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, session, initialized = _workspace(tmp_path, monkeypatch)
    options = client.get(f"/planning/sessions/{session['id']}/flight-selection")
    assert options.status_code == 200, options.text
    options_body = options.json()
    selected_quote = options_body["selected"]["quote_id"]
    assert all("segments" not in item for item in options_body["observations"])

    first_save = client.post(
        "/account/trips",
        headers=csrf(client),
        json={
            "session_id": session["id"],
            "client_event_id": "flight-initial-save",
            "source_result_id": initialized["current_result_id"],
            "expected_workspace_version": initialized["version"],
        },
    )
    assert first_save.status_code == 201, first_save.text
    trip_id = first_save.json()["trip"]["id"]

    current_session = client.get(f"/planning/sessions/{session['id']}").json()
    current_workspace = client.get(f"/planning/sessions/{session['id']}/workspace").json()
    preview = client.post(
        f"/planning/sessions/{session['id']}/flight-selection/preview",
        headers=csrf(client),
        json={
            "client_event_id": "flight-user-preview",
            "expected_session_version": current_session["version"],
            "expected_workspace_version": current_workspace["version"],
            "selection": _selection(selected_quote, source="user_provided_total"),
        },
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["preview"]["before"] != preview_body["preview"]["after"]
    assert (
        client.get(f"/planning/sessions/{session['id']}/workspace")
        .json()["report"]
        .get("flight_selection")
        is None
    )

    replay = client.post(
        f"/planning/sessions/{session['id']}/flight-selection/preview",
        headers=csrf(client),
        json={
            "client_event_id": "flight-user-preview",
            "expected_session_version": current_session["version"],
            "expected_workspace_version": current_workspace["version"],
            "selection": _selection(selected_quote, source="user_provided_total"),
        },
    )
    assert replay.status_code == 200
    assert replay.json() == preview_body

    workspace = client.get(f"/planning/sessions/{session['id']}/workspace").json()
    session_after_preview = client.get(f"/planning/sessions/{session['id']}").json()
    approved = client.post(
        f"/planning/sessions/{session['id']}/actions/{preview_body['proposal_id']}/approve",
        headers=csrf(client),
        json={
            "client_event_id": "flight-user-approve",
            "expected_session_version": session_after_preview["version"],
            "expected_workspace_version": workspace["version"],
        },
    )
    assert approved.status_code == 200, approved.text
    accepted = client.get(f"/planning/sessions/{session['id']}/workspace").json()
    report = FinalReport.model_validate(accepted["report"])
    assert report.flight_selection is not None
    assert report.flight_selection.amount_scope == "party_total"
    assert report.hotel_selection is None

    appended = client.post(
        f"/account/trips/{trip_id}/revisions",
        headers=csrf(client),
        json={
            "session_id": session["id"],
            "client_event_id": "flight-append",
            "source_result_id": accepted["current_result_id"],
            "expected_workspace_version": accepted["version"],
        },
    )
    assert appended.status_code == 201, appended.text
    reopened = AccountStore.open(tmp_path / "accounts.sqlite")
    app.dependency_overrides[get_store] = lambda: reopened
    saved = client.get(f"/account/trips/{trip_id}/revisions/2")
    assert saved.status_code == 200
    assert saved.json()["report"]["flight_selection"]["amount_scope"] == "party_total"
    hidden = second_client("flight-other@example.com").get(
        f"/planning/sessions/{session['id']}/flight-selection"
    )
    assert hidden.status_code in {404, 409}


def test_flight_requires_explicit_scope_and_only_retained_complete_quote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, session, _initialized = _workspace(tmp_path, monkeypatch)
    current_session = client.get(f"/planning/sessions/{session['id']}").json()
    current_workspace = client.get(f"/planning/sessions/{session['id']}/workspace").json()
    ambiguous = client.post(
        f"/planning/sessions/{session['id']}/flight-selection/preview",
        headers=csrf(client),
        json={
            "client_event_id": "flight-ambiguous",
            "expected_session_version": current_session["version"],
            "expected_workspace_version": current_workspace["version"],
            "selection": {
                "kind": "flight_selection",
                "source": "user_provided_total",
                "amount_minor": 51000,
                "currency": "INR",
                "covers": "flights",
                "payment_channel": "direct_airline",
            },
        },
    )
    assert ambiguous.status_code == 422
    unknown = client.post(
        f"/planning/sessions/{session['id']}/flight-selection/preview",
        headers=csrf(client),
        json={
            "client_event_id": "flight-observation-is-not-quote",
            "expected_session_version": current_session["version"],
            "expected_workspace_version": current_workspace["version"],
            "selection": _selection("not-an-observation-or-quote", source="inventory_quote"),
        },
    )
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "FLIGHT_CANDIDATE_NOT_FOUND"

    options = client.get(f"/planning/sessions/{session['id']}/flight-selection").json()
    incomplete = client.post(
        f"/planning/sessions/{session['id']}/flight-selection/preview",
        headers=csrf(client),
        json={
            "client_event_id": "flight-retained-quote",
            "expected_session_version": current_session["version"],
            "expected_workspace_version": current_workspace["version"],
            "selection": _selection(options["selected"]["quote_id"], source="inventory_quote"),
        },
    )
    # The retained sample row is a one-way synthetic segment for this round trip;
    # it is visible evidence but cannot be promoted into a round-trip selection.
    assert incomplete.status_code == 422
    assert incomplete.json()["detail"]["code"] == "FLIGHT_IDENTITY_MISMATCH"


def test_provider_quote_identity_requires_continuous_outbound_and_return() -> None:
    request = FlightSearchRequest(
        origin="DEL",
        destination="SIN",
        depart_date=date(2027, 2, 10),
        return_date=date(2027, 2, 13),
        travelers=TravelerMix(adults=1),
        cabin="economy",
        currency="INR",
    )
    departed = datetime(2027, 2, 10, 3, tzinfo=UTC)
    returned = datetime(2027, 2, 13, 3, tzinfo=UTC)

    def segment(origin: str, destination: str, when: datetime) -> FlightSegment:
        return FlightSegment(
            origin=origin,
            destination=destination,
            departure_at=when,
            arrival_at=when + timedelta(hours=2),
            marketing_airline="Test",
            flight_number=f"T{origin}{destination}",
            cabin="economy",
            duration_min=120,
        )

    quote = FlightQuote(
        id="discontinuous",
        segments=[segment("DEL", "DXB", departed), segment("HKG", "DEL", returned)],
        trip_type="round_trip",
        travelers=request.travelers,
        total_minor=1,
        currency="INR",
        evidence=EvidenceMeta(
            provider_id="fixture",
            retrieved_at=departed,
            status="cached",
            terms_version="v1",
            completeness="complete",
            needs_verification=True,
        ),
    )
    assert not _matches_retained_flight_request(quote, request)
