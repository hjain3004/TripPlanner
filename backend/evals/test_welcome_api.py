"""``POST /account/wallet/{entry_id}/welcome-status`` through the real app.

Real SQLite, real session cookies and CSRF, and the real planning job against the seeded
knowledge base, so the assignments read here are genuine optimizer output saved by A4's
route. Offer terms are SYNTHETIC (see ``welcome_support``); with the shipped catalog the
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
from api.welcome import get_as_of, get_offer_catalog
from evals.a4_support import csrf, second_client
from evals.welcome_support import (
    add_card,
    plan_and_save,
    request_status,
    synthetic_offer,
    use_catalog,
)

OPENED = date(2026, 10, 1)
AS_OF = date(2026, 10, 24)
CARD = "hdfc-infinia"
EXPORT_NOW = datetime(2026, 10, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, opened_on: date | None = OPENED
) -> tuple[TestClient, AccountStore, str, str]:
    client, store, body, entry_ids = plan_and_save(
        tmp_path, monkeypatch, cards=[(CARD, opened_on), ("sbi-cashback", None)]
    )
    return client, store, body["trip"]["id"], entry_ids[0]


def _stored_card_lines(client: TestClient, trip_id: str, card_id: str) -> list[dict[str, Any]]:
    """Independently read this card's assigned lines out of the stored revision."""
    report = client.get(f"/account/trips/{trip_id}/revisions/1").json()["report"]
    return [a for a in report["optimizer_result"]["assignments"] if a["card_id"] == card_id]


# --- the normal path: no approved offer data --------------------------------- #


def test_with_the_shipped_catalog_the_route_reports_that_no_offer_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id, entry_id = _setup(tmp_path, monkeypatch)
    app.dependency_overrides[get_as_of] = lambda: AS_OF  # the shipped catalog stays default
    response = request_status(client, entry_id, trip_id, prior=100)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "unknown"
    assert {item["code"] for item in body["limitations"]} == {"NO_APPROVED_OFFER"}
    assert body["offer"] is None and body["bonus"] is None
    assert body["window_closes_on"] is None and body["shortfall_minor"] is None
    # The trip side is still the server's, from the stored plan.
    assert body["trip_assigned_spend_minor"] > 0
    assert body["conditional_trip_spend_minor"] == 0


# --- demonstrated workflow with SYNTHETIC offer terms ------------------------ #


def test_status_is_computed_from_the_stored_plan_and_the_users_figure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id, entry_id = _setup(tmp_path, monkeypatch)
    use_catalog([synthetic_offer()], as_of=AS_OF)

    response = request_status(client, entry_id, trip_id, prior=1_200_000)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "active"
    assert body["opened_on"] == "2026-10-01"
    assert body["window_closes_on"] == "2026-12-30"
    assert body["days_remaining"] == 67
    assert body["min_spend_minor"] == 5_000_000
    assert body["qualifying_spend_to_date_minor"] == 1_200_000
    assert body["shortfall_minor"] == 3_800_000

    # Trip amounts equal the stored optimizer result for this card — recomputed here from
    # the stored revision, not from the response under test.
    expected = [a for a in _stored_card_lines(client, trip_id, CARD) if a["line"]["amount_minor"]]
    assert body["trip_assigned_spend_minor"] == sum(a["line"]["amount_minor"] for a in expected)
    assert {line["line_id"] for line in body["lines"]} == {a["line"]["id"] for a in expected}
    assert body["conditional_trip_spend_minor"] == body["trip_counted_spend_minor"]
    assert body["shortfall_after_conditional_trip_minor"] == max(
        0, 3_800_000 - body["conditional_trip_spend_minor"]
    )

    # Bonus: 10_000 points through the card's existing best valuation (INR 1.00/pt).
    assert body["bonus"]["bonus_value_minor"] == 10_000 * 1_000_000 // 10_000
    assert body["bonus"]["valuation"]["valuation_id"] == "infinia-portal-val"

    # Provenance and verification are carried, and labelled synthetic.
    provenance = body["offer"]["provenance"]
    assert provenance["verification_status"] == "synthetic_fixture"
    assert provenance["needs_verification"] is True
    assert provenance["source_url"].startswith("https://example.invalid/")
    assert body["offer"]["eligibility_exclusions"] == [
        "SYNTHETIC exclusion text, not an issuer term."
    ]
    assert body["assumptions"]


def test_the_stored_plan_is_unchanged_by_asking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, trip_id, entry_id = _setup(tmp_path, monkeypatch)
    use_catalog([synthetic_offer()], as_of=AS_OF)
    user_id = client.get("/auth/me").json()["id"]
    before_revision = client.get(f"/account/trips/{trip_id}/revisions/1").json()
    before_export = store.export_user(user_id, now=EXPORT_NOW).model_dump_json()

    assert request_status(client, entry_id, trip_id, prior=0).status_code == 200
    assert request_status(client, entry_id, trip_id).status_code == 200

    assert client.get(f"/account/trips/{trip_id}/revisions/1").json() == before_revision
    assert store.export_user(user_id, now=EXPORT_NOW).model_dump_json() == before_export


def test_the_same_request_gives_the_same_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id, entry_id = _setup(tmp_path, monkeypatch)
    use_catalog([synthetic_offer()], as_of=AS_OF)
    first = request_status(client, entry_id, trip_id, prior=500).json()
    second = request_status(client, entry_id, trip_id, prior=500).json()
    assert first == second


# --- unknown inputs ---------------------------------------------------------- #


def test_an_entry_without_an_open_date_is_unknown_through_the_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id, entry_id = _setup(tmp_path, monkeypatch, opened_on=None)
    use_catalog([synthetic_offer()], as_of=AS_OF)
    body = request_status(client, entry_id, trip_id, prior=0).json()
    assert body["status"] == "unknown"
    assert body["opened_on"] is None and body["window_closes_on"] is None
    assert body["days_remaining"] is None
    assert body["conditional_trip_spend_minor"] == 0
    assert "OPENED_ON_UNKNOWN" in {item["code"] for item in body["limitations"]}


def test_an_omitted_prior_spend_is_not_treated_as_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id, entry_id = _setup(tmp_path, monkeypatch)
    use_catalog([synthetic_offer()], as_of=AS_OF)
    omitted = request_status(client, entry_id, trip_id).json()
    zero = request_status(client, entry_id, trip_id, prior=0).json()
    assert omitted["qualifying_spend_to_date_minor"] is None
    assert omitted["shortfall_minor"] is None
    assert "PRIOR_SPEND_UNKNOWN" in {item["code"] for item in omitted["limitations"]}
    assert zero["shortfall_minor"] == 5_000_000


def test_the_client_cannot_supply_trip_amounts_or_dates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id, entry_id = _setup(tmp_path, monkeypatch)
    use_catalog([synthetic_offer()], as_of=AS_OF)
    for extra in (
        {"trip_spend_minor": 99_999_999},
        {"opened_on": "2026-01-01"},
        {"as_of": "2026-01-01"},
        {"user_id": "someone-else"},
    ):
        response = client.post(
            f"/account/wallet/{entry_id}/welcome-status",
            headers=csrf(client),
            json={"trip_id": trip_id, "revision": 1, **extra},
        )
        assert response.status_code == 422, extra


def test_invalid_figures_are_rejected_not_clamped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id, entry_id = _setup(tmp_path, monkeypatch)
    use_catalog([synthetic_offer()], as_of=AS_OF)
    for bad in (-1, 10**13 + 1):
        assert request_status(client, entry_id, trip_id, prior=bad).status_code == 422
    assert request_status(client, entry_id, trip_id, revision=0).status_code == 422


# --- ownership --------------------------------------------------------------- #


def test_another_users_wallet_entry_is_indistinguishable_from_a_missing_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _store, trip_id, entry_id = _setup(tmp_path, monkeypatch)
    use_catalog([synthetic_offer()], as_of=AS_OF)
    mallory = second_client("mallory@example.com")

    stolen = request_status(mallory, entry_id, trip_id)
    missing = request_status(mallory, "no-such-entry", trip_id)
    assert stolen.status_code == missing.status_code == 404
    assert stolen.json() == missing.json()
    assert stolen.json()["detail"]["code"] == "WALLET_ENTRY_NOT_FOUND"
    # The owner is unaffected.
    assert request_status(owner, entry_id, trip_id).status_code == 200


def test_another_users_trip_is_indistinguishable_from_a_missing_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _owner, _store, trip_id, _entry_id = _setup(tmp_path, monkeypatch)
    use_catalog([synthetic_offer()], as_of=AS_OF)
    mallory = second_client("mallory@example.com")
    mallory_entry = add_card(mallory, CARD, opened_on=OPENED)

    stolen = request_status(mallory, mallory_entry, trip_id)
    missing = request_status(mallory, mallory_entry, "no-such-trip")
    assert stolen.status_code == missing.status_code == 404
    assert stolen.json() == missing.json()
    assert stolen.json()["detail"]["code"] == "TRIP_NOT_FOUND"


def test_an_unknown_revision_of_an_owned_trip_is_a_typed_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id, entry_id = _setup(tmp_path, monkeypatch)
    response = request_status(client, entry_id, trip_id, revision=7)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "REVISION_NOT_FOUND"


def test_authentication_and_csrf_are_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id, entry_id = _setup(tmp_path, monkeypatch)
    path = f"/account/wallet/{entry_id}/welcome-status"
    body = {"trip_id": trip_id, "revision": 1}
    assert client.post(path, json=body).status_code == 403  # cookie but no CSRF header
    with TestClient(app) as anonymous:
        assert anonymous.post(path, json=body).status_code == 401


# --- unreadable stored revisions --------------------------------------------- #


def test_a_revision_from_an_older_schema_is_refused_not_reshaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id, entry_id = _setup(tmp_path, monkeypatch)
    use_catalog([synthetic_offer()], as_of=AS_OF)
    real = AccountStore.get_revision

    def old_schema(self: AccountStore, user_id: str, trip: str, revision: int) -> Any:
        return real(self, user_id, trip, revision).model_copy(update={"schema_version": "0"})

    monkeypatch.setattr(AccountStore, "get_revision", old_schema)
    response = request_status(client, entry_id, trip_id)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "REVISION_NOT_READABLE"


def test_a_revision_without_an_optimizer_result_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id, entry_id = _setup(tmp_path, monkeypatch)
    use_catalog([synthetic_offer()], as_of=AS_OF)
    real = AccountStore.get_revision

    def hollow(self: AccountStore, user_id: str, trip: str, revision: int) -> Any:
        return real(self, user_id, trip, revision).model_copy(update={"report_json": "{}"})

    monkeypatch.setattr(AccountStore, "get_revision", hollow)
    response = request_status(client, entry_id, trip_id)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "REVISION_NOT_READABLE"


# --- two entries for one product --------------------------------------------- #


def test_two_wallet_entries_for_one_product_are_not_attributed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id, entry_id = _setup(tmp_path, monkeypatch)
    use_catalog([synthetic_offer()], as_of=AS_OF)
    add_card(client, CARD, opened_on=date(2026, 6, 1), nickname="Second Infinia")
    body = request_status(client, entry_id, trip_id, prior=0).json()
    assert "DUPLICATE_CARD_ENTRIES" in {item["code"] for item in body["limitations"]}
    assert body["conditional_trip_spend_minor"] == 0
    assert {line["assessment"] for line in body["lines"]} == {"ambiguous_card_entry"}


def test_the_default_dependencies_are_the_shipped_catalog_and_the_real_clock() -> None:
    assert get_offer_catalog().offers_for_card(CARD) == []
    assert isinstance(get_as_of(), date)
