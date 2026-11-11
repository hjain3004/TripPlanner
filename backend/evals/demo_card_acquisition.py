"""Demonstration of conditional card acquisition assessment (spec 18 Case B).

    cd backend && .venv/bin/python -m evals.demo_card_acquisition

Drives the REAL application in-process: sign in (cookie + CSRF), hold a card (SBI Cashback),
run the real planning job, save the trip, then request acquisition assessment through
``POST /account/acquisition/trips/{trip_id}/revisions/{revision}``. Storage is
a real SQLite database in a temp directory. Nothing leaves the machine: no network, no
credentials, no LLM (the planning job uses a scripted client against the seeded sample
knowledge base).

Offer terms in the synthetic offer scenes are SYNTHETIC test data (``verified_by`` starts
with SYNTHETIC, source is ``example.invalid``). They are not issuer terms. The first scene
uses the shipped catalog, which is empty, to demonstrate the honest default.
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
from evals.welcome_support import (
    plan_and_save,
    request_acquisition_assessment,
    synthetic_offer,
    use_catalog,
)

TODAY = date(2026, 10, 24)  # pinned so the demo's dates are reproducible
HELD_CARD = "sbi-cashback"
CANDIDATE_CARD = "axis-atlas"


def _scene(title: str) -> None:
    print(f"\n=== {title} ===")


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "trip_id": report["trip_id"],
        "revision": report["revision"],
        "as_of": report["as_of"],
        "held_cards_strategy": report["held_cards_strategy"],
        "suggestion_count": len(report["suggestions"]),
        "refusal_count": len(report["refusals"]),
        "limitations": [item["code"] for item in report["limitations"]],
    }


def _synthetic_candidate_offer(**overrides: Any) -> Any:
    defaults: dict[str, Any] = {
        "card_id": CANDIDATE_CARD,
        "bonus_points": None,
        "bonus_currency_id": None,
        "bonus_flat_minor": 2_000_000,  # ₹20,000 flat bonus
        "min_spend_minor": 1_000_000,  # ₹10,000 spend requirement
        "spend_window_days": 90,
        "expected_approval_days": 7,
        "expected_card_in_hand_days": 7,
        "annual_fee_minor": 500_000,  # ₹5,000 annual fee
        "eligibility_exclusions": [
            "Must be a new Axis Bank credit card customer.",
            "Existing cardholders of any Axis credit card are ineligible.",
        ],
    }
    defaults.update(overrides)
    return synthetic_offer(**defaults)


def main() -> None:
    monkeypatch = pytest.MonkeyPatch()
    tmp = Path(tempfile.mkdtemp(prefix="acquisition-demo-"))
    try:
        _scene("1. Sign in, hold SBI Cashback, plan and save a trip (real planning job)")
        client, _store, created, _entries = plan_and_save(
            tmp,
            monkeypatch,
            cards=[(HELD_CARD, None)],
        )
        trip_id = created["trip"]["id"]
        me = client.get("/auth/me").json()
        print(f"signed in as {me['email']}; trip {trip_id} revision 1 saved")

        _scene("2. Normal path: shipped catalog (no approved offer data)")
        app.dependency_overrides[get_as_of] = lambda: TODAY
        pt = {
            "booking_date": "2026-10-24",
            "first_bookable_spend_date": "2026-11-20",
        }
        res = request_acquisition_assessment(client, trip_id, payment_timing=pt).json()
        print(json.dumps(_summary(res), indent=2))
        print("Held card strategy gross:", res["held_cards_strategy"]["gross_minor"])
        print("Held card strategy cards:", res["held_cards_strategy"]["card_ids"])
        print("Suggestions:", res["suggestions"])
        print("Limitations:", [item["code"] for item in res["limitations"]])

        _scene("3. SYNTHETIC qualifying offer: conditional suggestion, exact framing, gates passed")
        qualifying_offer = _synthetic_candidate_offer()
        use_catalog([qualifying_offer], as_of=TODAY)
        res = request_acquisition_assessment(
            client, trip_id, candidate_card_id=CANDIDATE_CARD, payment_timing=pt
        ).json()
        print(json.dumps(_summary(res), indent=2))
        sug = res["suggestions"][0]
        print(f"Card: {sug['card_name']} ({sug['card_id']})")
        print(f"Verbatim Framing: \"{sug['verbatim_framing']}\"")
        print(f"Net First Year Value: ₹{sug['net_first_year_minor'] / 100:,.2f}")
        print(f"  - Bonus Value: ₹{sug['bonus_value_minor'] / 100:,.2f}")
        print(f"  - Incremental Trip Earn Delta: ₹{sug['trip_earn_delta_minor'] / 100:,.2f}")
        print(f"  - First Year Fee: ₹{sug['annual_fee_minor'] / 100:,.2f}")
        print(f"Eligible Trip Spend: ₹{sug['trip_eligible_spend_minor'] / 100:,.2f}")
        print(f"Min Spend Required: ₹{sug['offer']['min_spend_minor'] / 100:,.2f}")
        print("Timing Assessment:")
        print(f"  - Expected Lead Time: {sug['timing']['expected_lead_time_days']} days")
        print(f"  - Earliest Usable Date: {sug['timing']['earliest_usable_date']}")
        print(f"  - First Bookable Spend Date: {sug['timing']['first_bookable_spend_date']}")
        print(f"  - Spend Window Closes: {sug['timing']['window_closes_on']}")
        print("Eligibility Exclusions (verbatim):")
        for exc in sug["eligibility_exclusions"]:
            print(f"  - {exc}")
        print("Held cards strategy remains unchanged:")
        print(f"  - Held cards: {res['held_cards_strategy']['card_ids']}")
        held_benefit = res["held_cards_strategy"]["total_benefit_minor"] / 100
        print(f"  - Held total benefit: ₹{held_benefit:,.2f}")

        _scene("4. Refusal cases: timing, unknown input, nonpositive value, unmapped points")
        # 4a. Timing refusal
        tight_pt = {
            "booking_date": "2026-10-24",
            "first_bookable_spend_date": "2026-10-30",  # Only 6 days lead time, 14 needed
        }
        ref_timing = request_acquisition_assessment(
            client, trip_id, candidate_card_id=CANDIDATE_CARD, payment_timing=tight_pt
        ).json()
        print("4a. Tight lead time:")
        print(f"    Reason: {ref_timing['refusals'][0]['reason']}")
        print(f"    Message: {ref_timing['refusals'][0]['message']}")

        # 4b. Unknown payment timing
        ref_unknown = request_acquisition_assessment(
            client, trip_id, candidate_card_id=CANDIDATE_CARD, payment_timing=None
        ).json()
        print("4b. Omitted payment timing:")
        print(f"    Reason: {ref_unknown['refusals'][0]['reason']}")
        print(f"    Message: {ref_unknown['refusals'][0]['message']}")

        # 4c. Nonpositive net value
        low_val_offer = _synthetic_candidate_offer(
            bonus_flat_minor=10_000,  # ₹100 bonus
            annual_fee_minor=5_000_000,  # ₹50,000 fee
        )
        use_catalog([low_val_offer], as_of=TODAY)
        ref_nonpos = request_acquisition_assessment(
            client, trip_id, candidate_card_id=CANDIDATE_CARD, payment_timing=pt
        ).json()
        print("4c. Fee exceeds bonus + earn delta:")
        print(f"    Reason: {ref_nonpos['refusals'][0]['reason']}")
        print(f"    Message: {ref_nonpos['refusals'][0]['message']}")

        # 4d. Points bonus without program valuation mapping
        points_offer = synthetic_offer(
            card_id=CANDIDATE_CARD,
            bonus_points=50_000,
            bonus_currency_id="unmapped-airline-miles",
        )
        use_catalog([points_offer], as_of=TODAY)
        ref_points = request_acquisition_assessment(
            client, trip_id, candidate_card_id=CANDIDATE_CARD, payment_timing=pt
        ).json()
        print("4d. Unvalued points bonus:")
        print(f"    Reason: {ref_points['refusals'][0]['reason']}")
        print(f"    Message: {ref_points['refusals'][0]['message']}")

        _scene("5. Wrong owner is refused identically to missing record")
        mallory = second_client("mallory@example.com")
        use_catalog([qualifying_offer], as_of=TODAY)
        stolen = request_acquisition_assessment(mallory, trip_id)
        missing = request_acquisition_assessment(mallory, "no-such-trip")
        print(f"Foreign trip request   -> {stolen.status_code} {stolen.json()['detail']}")
        print(f"Missing trip request   -> {missing.status_code} {missing.json()['detail']}")
        print("Identical responses:  ", stolen.json() == missing.json())

    finally:
        app.dependency_overrides.clear()
        monkeypatch.undo()


if __name__ == "__main__":
    main()
