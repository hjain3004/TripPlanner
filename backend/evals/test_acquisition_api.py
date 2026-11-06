"""Card-acquisition assessment API tests (spec 18 Case B).

Real SQLite, real session cookies and CSRF, and the real planning job against the seeded
knowledge base, so the assignments read here are genuine optimizer output saved by A4's
route.

Offer terms are SYNTHETIC (see ``welcome_support``); with the shipped catalog the
route must say honestly that no approved offer exists.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from accounts.store import AccountStore
from api.main import app
from api.welcome import get_as_of
from evals.a4_support import second_client
from evals.welcome_support import (
    plan_and_save,
    request_acquisition_assessment,
    synthetic_offer,
    use_catalog,
)

OPENED = date(2026, 10, 1)
AS_OF = date(2026, 10, 24)
CARD = "sbi-cashback"
CANDIDATE_CARD = "axis-atlas"
EXPORT_NOW = datetime(2026, 10, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, opened_on: date | None = OPENED
) -> tuple[TestClient, AccountStore, str]:
    client, store, body, _entry_ids = plan_and_save(
        tmp_path, monkeypatch, cards=[(CARD, opened_on)]
    )
    return client, store, body["trip"]["id"]


def _flat_candidate_offer(**overrides: Any) -> Any:
    defaults: dict[str, Any] = {
        "card_id": CANDIDATE_CARD,
        "bonus_points": None,
        "bonus_currency_id": None,
        "bonus_flat_minor": 2_000_000,
        "min_spend_minor": 1_000_000,
        "spend_window_days": 90,
        "expected_approval_days": 7,
        "expected_card_in_hand_days": 7,
        "annual_fee_minor": 500_000,
    }
    defaults.update(overrides)
    return synthetic_offer(**defaults)


# --- shipped catalog: honest empty state -------------------------------------- #


def test_with_the_shipped_catalog_route_reports_no_approved_offer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id = _setup(tmp_path, monkeypatch)
    app.dependency_overrides[get_as_of] = lambda: AS_OF
    pt = {
        "booking_date": "2026-10-24",
        "first_bookable_spend_date": "2026-11-20",
    }
    response = request_acquisition_assessment(client, trip_id, payment_timing=pt)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["suggestions"] == []
    assert body["refusals"] == []
    assert any(item["code"] == "NO_APPROVED_OFFER" for item in body["limitations"])
    # Held card strategy is still reported in full
    assert body["held_cards_strategy"]["card_ids"] == [CARD]
    assert body["held_cards_strategy"]["gross_minor"] > 0
    assert body["held_cards_strategy"]["currency"] == "INR"


# --- demonstrated workflow with SYNTHETIC qualifying offer -------------------- #


def test_qualifying_synthetic_offer_produces_suggestion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id = _setup(tmp_path, monkeypatch)
    offer = _flat_candidate_offer(
        eligibility_exclusions=["Exclusion rule text verbatim."]
    )
    use_catalog([offer], as_of=AS_OF)

    pt = {
        "booking_date": "2026-10-24",
        "first_bookable_spend_date": "2026-11-20",
    }
    response = request_acquisition_assessment(
        client, trip_id, candidate_card_id=CANDIDATE_CARD, payment_timing=pt
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert len(body["suggestions"]) == 1
    assert len(body["refusals"]) == 0
    sug = body["suggestions"][0]
    assert sug["card_id"] == CANDIDATE_CARD
    assert sug["verbatim_framing"].startswith("This card's current welcome bonus would be worth")
    assert sug["verbatim_framing"].endswith("on this trip if you held it")
    assert sug["eligibility_exclusions"] == ["Exclusion rule text verbatim."]
    assert sug["net_first_year_minor"] > 0
    assert sug["timing"]["lead_time_sufficient"] is True
    assert sug["offer"]["provenance"]["verification_status"] == "synthetic_fixture"

    # Held strategy is untouched
    assert body["held_cards_strategy"]["card_ids"] == [CARD]


# --- refusals ---------------------------------------------------------------- #


def test_timing_gate_refusal_through_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id = _setup(tmp_path, monkeypatch)
    # 7 approval + 7 in-hand = 14 days lead time (earliest usable = 2026-11-07)
    offer = _flat_candidate_offer()
    use_catalog([offer], as_of=AS_OF)

    # First bookable spend is 2026-11-01 (< 2026-11-07)
    pt = {
        "booking_date": "2026-10-24",
        "first_bookable_spend_date": "2026-11-01",
    }
    response = request_acquisition_assessment(
        client, trip_id, candidate_card_id=CANDIDATE_CARD, payment_timing=pt
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["suggestions"]) == 0
    assert len(body["refusals"]) == 1
    assert body["refusals"][0]["reason"] == "TIMING_GATE_FAILED"
    assert "~14 days' lead time you don't have" in body["refusals"][0]["message"]


def test_unknown_payment_timing_refusal_through_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id = _setup(tmp_path, monkeypatch)
    offer = _flat_candidate_offer()
    use_catalog([offer], as_of=AS_OF)

    # payment_timing omitted
    response = request_acquisition_assessment(
        client, trip_id, candidate_card_id=CANDIDATE_CARD, payment_timing=None
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["suggestions"]) == 0
    assert len(body["refusals"]) == 1
    assert body["refusals"][0]["reason"] == "PAYMENT_TIMING_UNKNOWN"


def test_nonpositive_value_refusal_through_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id = _setup(tmp_path, monkeypatch)
    # Huge fee, tiny bonus -> net <= 0
    offer = _flat_candidate_offer(bonus_flat_minor=10_000, annual_fee_minor=5_000_000)
    use_catalog([offer], as_of=AS_OF)

    pt = {
        "booking_date": "2026-10-24",
        "first_bookable_spend_date": "2026-11-20",
    }
    response = request_acquisition_assessment(
        client, trip_id, candidate_card_id=CANDIDATE_CARD, payment_timing=pt
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["suggestions"]) == 0
    assert len(body["refusals"]) == 1
    assert body["refusals"][0]["reason"] == "NONPOSITIVE_NET_VALUE"


def test_already_held_card_refusal_through_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id = _setup(tmp_path, monkeypatch)
    offer = synthetic_offer(card_id=CARD)
    use_catalog([offer], as_of=AS_OF)

    pt = {
        "booking_date": "2026-10-24",
        "first_bookable_spend_date": "2026-11-20",
    }
    response = request_acquisition_assessment(
        client, trip_id, candidate_card_id=CARD, payment_timing=pt
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["suggestions"]) == 0
    assert len(body["refusals"]) == 1
    assert body["refusals"][0]["reason"] == "ALREADY_HELD_CARD"


def test_points_bonus_without_mapping_refusal_through_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id = _setup(tmp_path, monkeypatch)
    offer = synthetic_offer(
        card_id=CANDIDATE_CARD,
        bonus_points=50_000,
        bonus_currency_id="some-points-program",
    )
    use_catalog([offer], as_of=AS_OF)

    pt = {
        "booking_date": "2026-10-24",
        "first_bookable_spend_date": "2026-11-20",
    }
    response = request_acquisition_assessment(
        client, trip_id, candidate_card_id=CANDIDATE_CARD, payment_timing=pt
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["suggestions"]) == 0
    assert len(body["refusals"]) == 1
    assert body["refusals"][0]["reason"] == "POINTS_PROGRAM_NOT_ESTABLISHED"


# --- ownership and authorization --------------------------------------------- #


def test_foreign_trip_is_indistinguishable_from_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _owner, _store, trip_id = _setup(tmp_path, monkeypatch)
    mallory = second_client("mallory@example.com")

    stolen = request_acquisition_assessment(mallory, trip_id)
    missing = request_acquisition_assessment(mallory, "no-such-trip")
    assert stolen.status_code == missing.status_code == 404
    assert stolen.json() == missing.json()
    assert stolen.json()["detail"]["code"] == "TRIP_NOT_FOUND"


def test_unknown_revision_is_typed_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id = _setup(tmp_path, monkeypatch)
    response = request_acquisition_assessment(client, trip_id, revision=99)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "REVISION_NOT_FOUND"


def test_authentication_and_csrf_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id = _setup(tmp_path, monkeypatch)
    path = f"/account/acquisition/trips/{trip_id}/revisions/1"
    # Cookie but no CSRF header -> 403
    assert client.post(path, json={}).status_code == 403
    # Anonymous -> 401
    with TestClient(app) as anon:
        assert anon.post(path, json={}).status_code == 401


# --- stored plan is unchanged by asking --------------------------------------- #


def test_stored_plan_remains_unchanged_by_asking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, trip_id = _setup(tmp_path, monkeypatch)
    offer = _flat_candidate_offer()
    use_catalog([offer], as_of=AS_OF)

    before = client.get(f"/account/trips/{trip_id}/revisions/1").json()["report"]
    wallet_before = client.get("/account/wallet").json()

    pt = {
        "booking_date": "2026-10-24",
        "first_bookable_spend_date": "2026-11-20",
    }
    request_acquisition_assessment(
        client, trip_id, candidate_card_id=CANDIDATE_CARD, payment_timing=pt
    )

    after = client.get(f"/account/trips/{trip_id}/revisions/1").json()["report"]
    wallet_after = client.get("/account/wallet").json()

    assert before == after
    assert wallet_before == wallet_after
