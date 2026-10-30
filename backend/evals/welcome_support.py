"""Shared fixtures for the welcome-status tests and demo (not itself a test module).

EVERYTHING OFFER-SHAPED HERE IS SYNTHETIC. The rows are authored for tests and the demo,
carry ``verified_by="SYNTHETIC_TEST_FIXTURE"`` and an ``example.invalid`` source, and are
never loaded by the shipped catalog (``load_offer_catalog`` rejects them). They state no
issuer term; the numbers exist only so the arithmetic can be exercised.

The plan side is real: ``plan_and_save`` drives the actual authenticated planning path
(eight typed answers, explicit confirmation, the real pipeline with a scripted LLM against
the seeded sample knowledge base) and saves the result through ``POST /account/trips``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from accounts.store import AccountStore
from api.main import app
from api.welcome import get_as_of, get_offer_catalog
from core.models import Provenance, UserWallet
from evals.a4_support import PlanningKit, csrf, finished_plan, signed_in_client
from welcome.catalog import OfferCatalog
from welcome.models import CardAcquisitionOffer

# The A4 pipeline is pinned to a 2026-11-01..05 DEL->SIN trip booked on 2026-10-24.
BOOKING_DATE = date(2026, 10, 24)
TRIP_START = date(2026, 11, 1)
TRIP_END = date(2026, 11, 5)

SYNTHETIC_PROVENANCE = Provenance(
    source_url="https://example.invalid/synthetic-welcome-offer",
    source_type="manual_curation",
    last_verified=date(2026, 10, 1),
    verified_by="SYNTHETIC_TEST_FIXTURE",
    needs_verification=True,
    confidence=0.5,
    notes="SYNTHETIC TEST FIXTURE - authored for tests and the demo; not issuer terms.",
)


def synthetic_offer(card_id: str = "hdfc-infinia", **overrides: Any) -> CardAcquisitionOffer:
    """A points-denominated synthetic offer; override any field to vary a scenario."""
    fields: dict[str, Any] = {
        "id": f"synthetic-{card_id}",
        "card_id": card_id,
        "title": "SYNTHETIC welcome offer (test fixture, not issuer terms)",
        "bonus_points": 10_000,
        "bonus_currency_id": "synthetic-card-points",
        "min_spend_minor": 5_000_000,
        "spend_window_days": 90,
        "expected_approval_days": 7,
        "expected_card_in_hand_days": 7,
        "annual_fee_minor": 1_000_000,
        "eligibility_exclusions": ["SYNTHETIC exclusion text, not an issuer term."],
        "currency": "INR",
        "valid_to": date(2030, 12, 31),
        "provenance": SYNTHETIC_PROVENANCE,
    }
    fields.update(overrides)
    return CardAcquisitionOffer.model_validate(fields)


def use_catalog(offers: list[CardAcquisitionOffer], *, as_of: date) -> None:
    """Point the app's welcome route at an authored catalog and a pinned clock."""
    app.dependency_overrides[get_offer_catalog] = lambda: OfferCatalog(offers)
    app.dependency_overrides[get_as_of] = lambda: as_of


def plan_and_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    cards: list[tuple[str, date | None]],
    email: str = "traveler@example.com",
) -> tuple[TestClient, AccountStore, dict[str, Any], list[str]]:
    """Sign in, hold ``cards``, run the real planning job, and save the trip.

    ``cards`` are ``(card_id, opened_on)`` pairs added through the wallet API *before*
    planning, because the confirmed plan's wallet is projected from the stored entries.
    Returns the client, its store, the created trip body (``trip`` + ``revision``) and the
    wallet entry ids in the order given.
    """
    client, store = signed_in_client(tmp_path, email)
    entry_ids = [add_card(client, card_id, opened_on=opened_on) for card_id, opened_on in cards]
    wallet = UserWallet.model_validate(client.get("/account/wallet/projection").json())
    kit = PlanningKit(monkeypatch, tmp_path)
    session, _job = finished_plan(client, kit, wallet=wallet)
    response = client.post(
        "/account/trips",
        headers=csrf(client),
        json={"session_id": session["id"], "client_event_id": "save-1"},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return client, store, body, entry_ids


def add_card(
    client: TestClient,
    card_id: str,
    *,
    opened_on: date | None,
    nickname: str = "My card",
) -> str:
    """Add a wallet entry through the real wallet API; returns its id."""
    response = client.post(
        "/account/wallet",
        headers=csrf(client),
        json={
            "card_id": card_id,
            "nickname": nickname,
            "opened_on": opened_on.isoformat() if opened_on else None,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def request_status(
    client: TestClient,
    entry_id: str,
    trip_id: str,
    *,
    revision: int = 1,
    prior: int | None = None,
) -> Any:
    body: dict[str, Any] = {"trip_id": trip_id, "revision": revision}
    if prior is not None:
        body["prior_qualifying_spend_minor"] = prior
    return client.post(
        f"/account/wallet/{entry_id}/welcome-status", headers=csrf(client), json=body
    )
