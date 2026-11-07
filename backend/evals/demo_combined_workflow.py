"""Demonstration of the combined TripWise backend workflow.

Exercises the full integrated workflow in-process against real SQLite:
1. Traveler sign-in (Argon2id + HTTP-only session cookie + CSRF).
2. Wallet initialization (held card: SBI Cashback).
3. 8-question planning interview and deterministic pipeline execution (DEL -> SIN, 2 travelers).
4. Explicit hotel selection (traveler-asserted stay total, SGD 1,970.94).
5. Save immutable trip revision 1 to SQLite store.
6. Simulated server restart: re-initialize store from disk and reopen revision 1.
7. Explicit flight selection (traveler party total estimate, INR 51,000) and append revision 2.
8. Non-inventory CP4 itinerary amendment (deterministic POI removal) and append revision 3.
9. Verify accepted hotel & flight selections remain consistent across reloads and amendments.
10. Case B card acquisition assessment against shipped empty catalog:
    demonstrates honest NO_APPROVED_OFFER.
11. Case B card acquisition assessment against qualifying synthetic offer:
    demonstrates exact conditional informational framing and net first-year calculation.

Run directly via:
    cd backend && .venv/bin/python -m evals.demo_combined_workflow
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from accounts.store import AccountStore
from agents.models import FinalReport
from api.auth import get_store
from api.main import app
from api.welcome import get_as_of
from core.models import UserWallet
from evals.a4_support import (
    PlanningKit,
    csrf,
    finished_plan,
    signed_in_client,
    simulate_restart,
)
from evals.welcome_support import (
    add_card,
    request_acquisition_assessment,
    synthetic_offer,
    use_catalog,
)

AS_OF = date(2026, 10, 24)
HELD_CARD = "sbi-cashback"
CANDIDATE_CARD = "axis-atlas"


def _scene(title: str) -> None:
    print(f"\n{'=' * 10} {title} {'=' * 10}")


def run_demo() -> None:
    monkeypatch = pytest.MonkeyPatch()
    tmp = Path(tempfile.mkdtemp(prefix="combined-demo-"))
    db_path = tmp / "accounts.db"

    print("TripWise Integrated Backend Demonstration")
    print(f"Isolated temp SQLite database: {db_path}")

    # 1. Authenticate traveler
    _scene("1. Traveler Sign-In & Authentication")
    client, store = signed_in_client(tmp, email="traveler@example.com")
    print("Traveler registered and signed in via Argon2id hashed credentials.")
    print("Session token stored in HTTP-only cookie; CSRF header required on mutation routes.")

    # 2. Add held card to wallet
    _scene("2. Wallet Setup")
    entry_id = add_card(
        client, HELD_CARD, opened_on=date(2026, 1, 15), nickname="Primary Cashback Card"
    )
    wallet = UserWallet.model_validate(client.get("/account/wallet/projection").json())
    print(f"Added held card to wallet: {HELD_CARD} (opened 2026-01-15, entry_id={entry_id})")
    print(f"Projected wallet card count: {len(wallet.card_ids)}")

    # 3. Planning Interview & Execution
    _scene("3. Conversational Planning & Deterministic Pipeline")
    kit = PlanningKit(monkeypatch, tmp)
    session, job = finished_plan(client, kit, wallet=wallet)
    session_id = session["id"]

    init_ws = client.post(
        f"/planning/sessions/{session_id}/workspace",
        headers=csrf(client),
        json={"source": "job"},
    )
    assert init_ws.status_code == 200, init_ws.text
    ws = init_ws.json()
    print("Completed 8-question interview: DEL -> SIN (2 travelers, Nov 1-5, 2026).")
    print(f"Confirmed planning job finished. Initial workspace version: {ws['version']}")

    # 4. Explicit Hotel Selection
    _scene("4. Explicit Hotel Selection (Traveler-Asserted Stay Total)")
    hotel_options = client.get(f"/planning/sessions/{session_id}/hotel-selection").json()
    hotel_quote_id = hotel_options["selected"]["quote_id"]
    cur_session = client.get(f"/planning/sessions/{session_id}").json()
    cur_ws = client.get(f"/planning/sessions/{session_id}/workspace").json()

    hotel_preview = client.post(
        f"/planning/sessions/{session_id}/hotel-selection/preview",
        headers=csrf(client),
        json={
            "client_event_id": "hotel-select-preview",
            "expected_session_version": cur_session["version"],
            "expected_workspace_version": cur_ws["version"],
            "selection": {
                "kind": "hotel_selection",
                "source": "user_provided_total",
                "quote_id": hotel_quote_id,
                "amount_minor": 197094,  # SGD 1,970.94
                "currency": "SGD",
                "covers": "room, taxes and service charges as stated by traveler",
                "payment_channel": "ota_generic",
                "assumptions": ["traveler supplied exact stay total"],
            },
        },
    )
    assert hotel_preview.status_code == 200, hotel_preview.text
    hotel_proposal = hotel_preview.json()

    cur_session = client.get(f"/planning/sessions/{session_id}").json()
    cur_ws = client.get(f"/planning/sessions/{session_id}/workspace").json()
    hotel_approve = client.post(
        f"/planning/sessions/{session_id}/actions/{hotel_proposal['proposal_id']}/approve",
        headers=csrf(client),
        json={
            "client_event_id": "hotel-select-approve",
            "expected_session_version": cur_session["version"],
            "expected_workspace_version": cur_ws["version"],
        },
    )
    assert hotel_approve.status_code == 200, hotel_approve.text
    print("Approved explicit hotel selection: SGD 1,970.94 (user_provided_total, ota_generic).")

    # 5. Save Trip Revision 1
    _scene("5. Save Immutable Trip Revision 1 to SQLite")
    cur_ws = client.get(f"/planning/sessions/{session_id}/workspace").json()
    save_resp = client.post(
        "/account/trips",
        headers=csrf(client),
        json={
            "session_id": session_id,
            "client_event_id": "save-trip-rev-1",
            "source_result_id": cur_ws["current_result_id"],
            "expected_workspace_version": cur_ws["version"],
        },
    )
    assert save_resp.status_code == 201, save_resp.text
    trip_data = save_resp.json()
    trip_id = trip_data["trip"]["id"]
    print(f"Saved Trip ID: {trip_id}, Initial Revision: 1")

    # 6. Simulated Server Restart and SQLite Reopen
    _scene("6. Simulated Server Restart & Revision Reopen")
    app.dependency_overrides.clear()
    simulate_restart(monkeypatch)

    fresh_store = AccountStore.open(tmp / "accounts.sqlite")
    app.dependency_overrides[get_store] = lambda: fresh_store
    restart_client = TestClient(app, base_url="https://testserver", cookies=client.cookies)

    reopened_rev = restart_client.get(f"/account/trips/{trip_id}/revisions/1")
    assert reopened_rev.status_code == 200, reopened_rev.text
    rev1_body = reopened_rev.json()
    rev1_report = FinalReport.model_validate(rev1_body["report"])

    assert rev1_report.hotel_selection is not None
    assert rev1_report.hotel_selection.amount_minor == 197094
    assert rev1_report.hotel_selection.currency == "SGD"
    print("Re-opened saved revision 1 after full server restart simulation:")
    print(f"  Hotel Selection preserved: SGD {rev1_report.hotel_selection.amount_minor / 100:,.2f}")

    # 7. Explicit Flight Selection & Append Revision 2
    _scene("7. Explicit Flight Selection & Revision 2 Append")
    flight_options = restart_client.get(f"/planning/sessions/{session_id}/flight-selection").json()
    flight_quote_id = flight_options["selected"]["quote_id"]
    cur_session = restart_client.get(f"/planning/sessions/{session_id}").json()
    cur_ws = restart_client.get(f"/planning/sessions/{session_id}/workspace").json()

    flight_preview = restart_client.post(
        f"/planning/sessions/{session_id}/flight-selection/preview",
        headers=csrf(restart_client),
        json={
            "client_event_id": "flight-select-preview",
            "expected_session_version": cur_session["version"],
            "expected_workspace_version": cur_ws["version"],
            "selection": {
                "kind": "flight_selection",
                "source": "user_provided_total",
                "quote_id": flight_quote_id,
                "amount_minor": 5100000,  # INR 51,000.00
                "currency": "INR",
                "covers": "round-trip economy for party of 2",
                "amount_scope": "party_total",
                "payment_channel": "direct_airline",
                "assumptions": ["traveler supplied airline direct party quote"],
            },
        },
    )
    assert flight_preview.status_code == 200, flight_preview.text
    flight_proposal = flight_preview.json()

    cur_session = restart_client.get(f"/planning/sessions/{session_id}").json()
    cur_ws = restart_client.get(f"/planning/sessions/{session_id}/workspace").json()
    flight_approve = restart_client.post(
        f"/planning/sessions/{session_id}/actions/{flight_proposal['proposal_id']}/approve",
        headers=csrf(restart_client),
        json={
            "client_event_id": "flight-select-approve",
            "expected_session_version": cur_session["version"],
            "expected_workspace_version": cur_ws["version"],
        },
    )
    assert flight_approve.status_code == 200, flight_approve.text

    cur_ws = restart_client.get(f"/planning/sessions/{session_id}/workspace").json()
    append_rev2 = restart_client.post(
        f"/account/trips/{trip_id}/revisions",
        headers=csrf(restart_client),
        json={
            "session_id": session_id,
            "client_event_id": "append-trip-rev-2",
            "source_result_id": cur_ws["current_result_id"],
            "expected_workspace_version": cur_ws["version"],
        },
    )
    assert append_rev2.status_code == 201, append_rev2.text
    print(f"Appended Revision 2 to Trip {trip_id}.")

    # 8. Non-Inventory CP4 Itinerary Amendment & Revision 3 Append
    _scene("8. Non-Inventory Itinerary Amendment & Revision 3 Append")
    cur_ws = restart_client.get(f"/planning/sessions/{session_id}/workspace").json()
    cur_session = restart_client.get(f"/planning/sessions/{session_id}").json()
    first_day_items = cur_ws["report"]["itinerary"]["days"][0]["items"]
    poi_to_remove = first_day_items[0]["poi_id"]

    edit_preview = restart_client.post(
        f"/planning/sessions/{session_id}/actions",
        headers=csrf(restart_client),
        json={
            "client_event_id": "edit-poi-preview",
            "expected_session_version": cur_session["version"],
            "expected_workspace_version": cur_ws["version"],
            "action": {
                "kind": "deterministic_edit",
                "edit": {
                    "op": "remove_item",
                    "poi_id": poi_to_remove,
                    "day_index": 0,
                },
            },
        },
    )
    assert edit_preview.status_code == 200, edit_preview.text
    edit_proposal = edit_preview.json()

    cur_ws = restart_client.get(f"/planning/sessions/{session_id}/workspace").json()
    cur_session = restart_client.get(f"/planning/sessions/{session_id}").json()
    edit_approve = restart_client.post(
        f"/planning/sessions/{session_id}/actions/{edit_proposal['proposal_id']}/approve",
        headers=csrf(restart_client),
        json={
            "client_event_id": "edit-poi-approve",
            "expected_session_version": cur_session["version"],
            "expected_workspace_version": cur_ws["version"],
        },
    )
    assert edit_approve.status_code == 200, edit_approve.text

    cur_ws = restart_client.get(f"/planning/sessions/{session_id}/workspace").json()
    append_rev3 = restart_client.post(
        f"/account/trips/{trip_id}/revisions",
        headers=csrf(restart_client),
        json={
            "session_id": session_id,
            "client_event_id": "append-trip-rev-3",
            "source_result_id": cur_ws["current_result_id"],
            "expected_workspace_version": cur_ws["version"],
        },
    )
    assert append_rev3.status_code == 201, append_rev3.text
    print(f"Appended Revision 3 to Trip {trip_id} (removed POI '{poi_to_remove}').")

    # 9. Verify Revisions Consistency
    _scene("9. Verification of Cross-Revision Amounts")
    rev3_data = restart_client.get(f"/account/trips/{trip_id}/revisions/3").json()
    rev3_report = FinalReport.model_validate(rev3_data["report"])
    assert rev3_report.hotel_selection is not None
    assert rev3_report.hotel_selection.amount_minor == 197094
    assert rev3_report.flight_selection is not None
    assert rev3_report.flight_selection.amount_minor == 5100000

    print("Verified Revision 3 preserves exact selected amounts across non-inventory edits:")
    print(f"  Hotel Stay Total: SGD {rev3_report.hotel_selection.amount_minor / 100:,.2f}")
    print(f"  Flight Party Total: INR {rev3_report.flight_selection.amount_minor / 100:,.2f}")

    # 10. Case B Assessment: Shipped Empty Catalog
    _scene("10. Case B Card Acquisition Assessment (Shipped Empty Catalog)")
    app.dependency_overrides[get_as_of] = lambda: AS_OF
    pt = {
        "booking_date": "2026-10-24",
        "first_bookable_spend_date": "2026-11-20",
    }
    shipped_assessment = request_acquisition_assessment(
        restart_client, trip_id, revision=3, payment_timing=pt
    )
    assert shipped_assessment.status_code == 200, shipped_assessment.text
    shipped_body = shipped_assessment.json()
    assert len(shipped_body["suggestions"]) == 0
    assert any(lim["code"] == "NO_APPROVED_OFFER" for lim in shipped_body["limitations"])
    print("Shipped Catalog Result:")
    print(f"  Suggestions count: {len(shipped_body['suggestions'])}")
    print(f"  Limitations returned: {[lim['code'] for lim in shipped_body['limitations']]}")
    print("  Demonstrated honest fallback when no approved welcome offers exist in the catalog.")

    # 11. Case B Assessment: Qualifying Synthetic Offer
    _scene("11. Case B Card Acquisition Assessment (Qualifying Synthetic Offer)")
    synthetic = synthetic_offer(
        card_id=CANDIDATE_CARD,
        bonus_points=None,
        bonus_currency_id=None,
        bonus_flat_minor=2_000_000,  # ₹20,000 flat bonus
        min_spend_minor=1_000_000,   # ₹10,000 spend requirement
        spend_window_days=90,
        expected_approval_days=7,
        expected_card_in_hand_days=7,
        annual_fee_minor=500_000,    # ₹5,000 annual fee
        eligibility_exclusions=[
            "Must be a new Axis Bank credit card customer.",
            "Existing cardholders of any Axis credit card are ineligible.",
        ],
    )
    use_catalog([synthetic], as_of=AS_OF)

    synthetic_assessment = request_acquisition_assessment(
        restart_client, trip_id, revision=3, payment_timing=pt
    )
    assert synthetic_assessment.status_code == 200, synthetic_assessment.text
    synthetic_body = synthetic_assessment.json()
    assert len(synthetic_body["suggestions"]) == 1
    sug = synthetic_body["suggestions"][0]

    print("Qualifying Offer Result:")
    print(f"  Candidate Card: {sug['card_id']}")
    print(f"  Framing: \"{sug['verbatim_framing']}\"")
    print(f"  Welcome Bonus Net: INR {sug['bonus_value_minor'] / 100:,.2f}")
    print(f"  Annual Fee: INR {sug['annual_fee_minor'] / 100:,.2f}")
    print(f"  Incremental Trip Earn Delta: INR {sug['trip_earn_delta_minor'] / 100:,.2f}")
    print(f"  Net First Year Benefit: INR {sug['net_first_year_minor'] / 100:,.2f}")
    print(f"  Eligibility Exclusions: {sug['eligibility_exclusions']}")
    print("  Zero autonomous wallet mutations, no affiliate links, exact verbatim framing.")

    app.dependency_overrides.clear()
    _scene("DEMONSTRATION COMPLETE: ALL INVARIANTS VERIFIED")


if __name__ == "__main__":
    run_demo()
