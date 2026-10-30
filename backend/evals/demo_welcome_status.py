"""Demonstration of welcome-window status for a held card (spec 18 Case A, backend slice).

    cd backend && .venv/bin/python -m evals.demo_welcome_status

Drives the REAL application in-process: sign in (cookie + CSRF), hold cards, run the real
planning job, save the trip, then request status through
``POST /account/wallet/{entry_id}/welcome-status``. Storage is a real SQLite file in a
temp directory. Nothing leaves the machine: no network, no credentials, no LLM (the
planning job uses a scripted client against the seeded sample knowledge base).

Offer terms in the "synthetic offer" scenes are SYNTHETIC test data (``verified_by`` starts
with SYNTHETIC, source is ``example.invalid``). They are not issuer terms. The first scene
uses the shipped catalog, which is empty, to show the honest default.
"""

from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from api.main import app
from api.welcome import get_as_of
from evals.a4_support import second_client
from evals.welcome_support import plan_and_save, request_status, synthetic_offer, use_catalog

TODAY = date(2026, 10, 24)  # pinned so the demo's dates are reproducible


def _scene(title: str) -> None:
    print(f"\n=== {title} ===")


def _summary(body: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "status",
        "as_of",
        "opened_on",
        "window_closes_on",
        "days_remaining",
        "min_spend_minor",
        "currency",
        "qualifying_spend_to_date_minor",
        "shortfall_minor",
        "trip_assigned_spend_minor",
        "trip_counted_spend_minor",
        "conditional_trip_spend_minor",
        "shortfall_after_conditional_trip_minor",
        "trip_alone_clears_minimum_if_conditions_hold",
    )
    return {key: body[key] for key in keys}


def main() -> None:
    monkeypatch = pytest.MonkeyPatch()
    tmp = Path(tempfile.mkdtemp(prefix="welcome-demo-"))
    try:
        _scene("1. Sign in, hold two cards, plan and save a trip (real planning job)")
        client, _store, created, entries = plan_and_save(
            tmp,
            monkeypatch,
            cards=[("hdfc-infinia", date(2026, 10, 1)), ("sbi-cashback", None)],
        )
        trip_id = created["trip"]["id"]
        infinia, cashback = entries
        me = client.get("/auth/me").json()
        print(f"signed in as {me['email']}; trip {trip_id} revision 1 saved")

        _scene("2. Normal path: shipped catalog (no approved offer data)")
        app.dependency_overrides[get_as_of] = lambda: TODAY
        body = request_status(client, infinia, trip_id, prior=1_200_000).json()
        print(json.dumps(_summary(body), indent=2))
        print("limitations:", [item["code"] for item in body["limitations"]])

        _scene("3. SYNTHETIC offer: dates, remaining spend, bonus, assumptions, provenance")
        use_catalog([synthetic_offer()], as_of=TODAY)
        body = request_status(client, infinia, trip_id, prior=1_200_000).json()
        print(json.dumps(_summary(body), indent=2))
        print("bonus:", json.dumps(body["bonus"], indent=2))
        print("offer provenance:", json.dumps(body["offer"]["provenance"], indent=2))
        print("per-line timing (this card only):")
        for line in body["lines"]:
            print(
                f"  {line['label']:<45} {line['channel']:<12} {line['timing_basis']:<16}"
                f" amount={line['amount_minor']:>9} counted={line['counted_minor']:>9}"
                f" -> {line['assessment']}"
            )
        print(f"zero-amount lines omitted: {body['omitted_zero_amount_lines']}")
        print("assumptions:")
        for note in body["assumptions"]:
            print(f"  - {note}")

        _scene("4. Unknown inputs stay unknown")
        omitted = request_status(client, infinia, trip_id).json()
        print(
            "prior spend omitted ->",
            {
                "qualifying_spend_to_date_minor": omitted["qualifying_spend_to_date_minor"],
                "shortfall_minor": omitted["shortfall_minor"],
                "limitations": [item["code"] for item in omitted["limitations"]],
            },
        )
        use_catalog([synthetic_offer("sbi-cashback")], as_of=TODAY)
        no_open_date = request_status(client, cashback, trip_id, prior=0).json()
        print(
            "entry with no opened_on ->",
            {
                "status": no_open_date["status"],
                "opened_on": no_open_date["opened_on"],
                "window_closes_on": no_open_date["window_closes_on"],
                "limitations": [item["code"] for item in no_open_date["limitations"]],
            },
        )

        _scene("5. Wrong owner is refused exactly like a missing id")
        mallory = second_client("mallory@example.com")
        use_catalog([synthetic_offer()], as_of=TODAY)
        stolen = request_status(mallory, infinia, trip_id)
        missing = request_status(mallory, "no-such-entry", trip_id)
        print(f"someone else's wallet entry -> {stolen.status_code} {stolen.json()['detail']}")
        print(f"a nonexistent wallet entry  -> {missing.status_code} {missing.json()['detail']}")
        print("identical responses:", stolen.json() == missing.json())
    finally:
        app.dependency_overrides.clear()
        monkeypatch.undo()


if __name__ == "__main__":
    main()
