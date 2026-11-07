"""Focused authenticated regressions for explicit hotel selection and budgeting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from accounts.store import AccountStore
from agents.models import FinalReport
from api.auth import get_store
from api.main import app
from evals.a4_support import PlanningKit, csrf, finished_plan, second_client, signed_in_client


@pytest.fixture(autouse=True)
def _clear_overrides() -> None:
    yield
    app.dependency_overrides.clear()


def _workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, AccountStore, dict[str, Any], dict[str, Any]]:
    client, store = signed_in_client(tmp_path, email="hotel-owner@example.com")
    kit = PlanningKit(monkeypatch, tmp_path)
    session, job = finished_plan(client, kit)
    initialized = client.post(
        f"/planning/sessions/{session['id']}/workspace",
        headers=csrf(client),
        json={"source": "job"},
    )
    assert initialized.status_code == 200, initialized.text
    return client, store, session, initialized.json()


def _selection_action(quote_id: str, *, source: str = "inventory_quote") -> dict[str, Any]:
    if source == "inventory_quote":
        return {"kind": "hotel_selection", "source": source, "quote_id": quote_id}
    return {
        "kind": "hotel_selection",
        "source": source,
        "quote_id": quote_id,
        "amount_minor": 197094,
        "currency": "SGD",
        "covers": "room, taxes and fees as stated by the traveler",
        "payment_channel": "ota_generic",
        "assumptions": ["traveler supplied the complete stay total"],
    }


def test_sample_hotel_selection_preview_confirm_save_reopen_and_stale_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, session, initialized = _workspace(tmp_path, monkeypatch)
    options = client.get(f"/planning/sessions/{session['id']}/hotel-selection")
    assert options.status_code == 200, options.text
    selected_quote = options.json()["selected"]["quote_id"]

    first_save = client.post(
        "/account/trips",
        headers=csrf(client),
        json={
            "session_id": session["id"],
            "client_event_id": "hotel-selection-initial-save",
            "source_result_id": initialized["current_result_id"],
            "expected_workspace_version": initialized["version"],
        },
    )
    assert first_save.status_code == 201, first_save.text
    trip_id = first_save.json()["trip"]["id"]

    current_session = client.get(f"/planning/sessions/{session['id']}").json()
    current_workspace = client.get(f"/planning/sessions/{session['id']}/workspace").json()
    preview = client.post(
        f"/planning/sessions/{session['id']}/hotel-selection/preview",
        headers=csrf(client),
        json={
            "client_event_id": "hotel-selection-preview",
            "expected_session_version": current_session["version"],
            "expected_workspace_version": current_workspace["version"],
            "selection": _selection_action(selected_quote, source="user_provided_total"),
        },
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["preview"]["before"] != preview_body["preview"]["after"]
    assert client.get(f"/planning/sessions/{session['id']}/workspace").json()["report"].get(
        "hotel_selection"
    ) is None

    replay = client.post(
        f"/planning/sessions/{session['id']}/hotel-selection/preview",
        headers=csrf(client),
        json={
            "client_event_id": "hotel-selection-preview",
            "expected_session_version": current_session["version"],
            "expected_workspace_version": current_workspace["version"],
            "selection": _selection_action(selected_quote, source="user_provided_total"),
        },
    )
    assert replay.status_code == 200
    assert replay.json() == preview_body

    conflicting = client.post(
        f"/planning/sessions/{session['id']}/hotel-selection/preview",
        headers=csrf(client),
        json={
            "client_event_id": "hotel-selection-preview",
            "expected_session_version": current_session["version"],
            "expected_workspace_version": current_workspace["version"],
            "selection": _selection_action("different-quote"),
        },
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"

    after_preview = client.get(f"/planning/sessions/{session['id']}/workspace").json()
    after_preview_session = client.get(f"/planning/sessions/{session['id']}").json()
    approved = client.post(
        f"/planning/sessions/{session['id']}/actions/{preview_body['proposal_id']}/approve",
        headers=csrf(client),
        json={
            "client_event_id": "hotel-selection-approve",
            "expected_session_version": after_preview_session["version"],
            "expected_workspace_version": after_preview["version"],
        },
    )
    assert approved.status_code == 200, approved.text
    accepted = client.get(f"/planning/sessions/{session['id']}/workspace").json()
    accepted_report = FinalReport.model_validate(accepted["report"])
    assert accepted_report.hotel_selection is not None
    assert accepted_report.hotel_selection.source == "user_provided_total"
    assert accepted_report.hotel_selection.quote_id == selected_quote
    assert accepted_report.travel_inventory is not None
    assert accepted_report.travel_inventory.flight_observations == FinalReport.model_validate(
        initialized["report"]
    ).travel_inventory.flight_observations

    stale = client.post(
        f"/planning/sessions/{session['id']}/actions/{preview_body['proposal_id']}/approve",
        headers=csrf(client),
        json={
            "client_event_id": "hotel-selection-approve-stale",
            "expected_session_version": after_preview_session["version"],
            "expected_workspace_version": after_preview["version"],
        },
    )
    assert stale.status_code == 409

    latest = client.get(f"/planning/sessions/{session['id']}/workspace").json()
    appended = client.post(
        f"/account/trips/{trip_id}/revisions",
        headers=csrf(client),
        json={
            "session_id": session["id"],
            "client_event_id": "hotel-selection-append",
            "source_result_id": latest["current_result_id"],
            "expected_workspace_version": latest["version"],
        },
    )
    assert appended.status_code == 201, appended.text
    assert appended.json()["revision"] == 2
    revision_one = client.get(f"/account/trips/{trip_id}/revisions/1").json()
    revision_two = client.get(f"/account/trips/{trip_id}/revisions/2").json()
    assert revision_one["report"].get("hotel_selection") is None
    assert revision_two["report"]["hotel_selection"]["quote_id"] == selected_quote

    reopened = AccountStore.open(tmp_path / "accounts.sqlite")
    app.dependency_overrides[get_store] = lambda: reopened
    reopened_revision = client.get(f"/account/trips/{trip_id}/revisions/2")
    assert reopened_revision.status_code == 200
    assert reopened_revision.json()["report"]["hotel_selection"]["quote_id"] == selected_quote

    other = second_client("hotel-other@example.com")
    hidden = other.get(f"/planning/sessions/{session['id']}/hotel-selection")
    assert hidden.status_code in {404, 409}


def test_user_total_is_separate_from_provider_evidence_and_requires_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, session, initialized = _workspace(tmp_path, monkeypatch)
    current_session = client.get(f"/planning/sessions/{session['id']}").json()
    current_workspace = client.get(f"/planning/sessions/{session['id']}/workspace").json()
    missing_channel = client.post(
        f"/planning/sessions/{session['id']}/hotel-selection/preview",
        headers=csrf(client),
        json={
            "client_event_id": "hotel-user-total-no-channel",
            "expected_session_version": current_session["version"],
            "expected_workspace_version": current_workspace["version"],
            "selection": {
                "kind": "hotel_selection",
                "source": "user_provided_total",
                "amount_minor": 197094,
                "currency": "SGD",
                "covers": "room and taxes as stated",
            },
        },
    )
    assert missing_channel.status_code == 422
    assert missing_channel.json()["detail"]["code"] == "HOTEL_PAYMENT_CHANNEL_REQUIRED"

    options = client.get(f"/planning/sessions/{session['id']}/hotel-selection").json()
    quote_id = options["selected"]["quote_id"]
    user_total = _selection_action(quote_id, source="user_provided_total")
    selected = client.post(
        f"/planning/sessions/{session['id']}/hotel-selection/preview",
        headers=csrf(client),
        json={
            "client_event_id": "hotel-user-total",
            "expected_session_version": current_session["version"],
            "expected_workspace_version": current_workspace["version"],
            "selection": user_total,
        },
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["preview"]["after"]["limitations"]
    current_session = client.get(f"/planning/sessions/{session['id']}").json()
    current_workspace = client.get(f"/planning/sessions/{session['id']}/workspace").json()

    inventory = client.post(
        f"/planning/sessions/{session['id']}/hotel-selection/preview",
        headers=csrf(client),
        json={
            "client_event_id": "hotel-inventory-quote",
            "expected_session_version": current_session["version"],
            "expected_workspace_version": current_workspace["version"],
            "selection": _selection_action(quote_id),
        },
    )
    assert inventory.status_code == 200, inventory.text
    assert inventory.json()["preview"]["selection"]["source"] == "inventory_quote"
    initial_hotel_amount = next(
        line["amount_minor"]
        for line in initialized["report"]["costed_trip"]["lines"]
        if line["category"] == "hotels"
    )
    assert inventory.json()["preview"]["after"]["hotel_amount_minor"] == initial_hotel_amount
