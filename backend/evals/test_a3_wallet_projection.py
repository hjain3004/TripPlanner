"""A3 Task 6 — the API-to-session projection boundary.

``test_a1_projection.py`` already pins the pure ``build_user_wallet`` function.
This file pins the same guarantees *through the surfaces a signed-in traveler
actually touches*: the HTTP projection endpoint, and the handoff that gives a
planning session its wallet. A rule that holds in the pure function but is
bypassed by the route or the session handoff would still be a product bug.

The load-bearing one is the last group: an authenticated traveler who has
deliberately stored no cards must reach planning with an empty wallet and get
truthful cash-only output — never a substituted demo wallet.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from accounts.projection import build_user_wallet
from accounts.store import AccountStore
from api.auth import CSRF_COOKIE, CSRF_HEADER, get_store
from api.conversation import _profile_for_user
from api.main import app
from core.db import load_kb
from core.models import (
    Channel,
    CostedTrip,
    OptimizationPrefs,
    SpendCategory,
    SpendLineItem,
    UserWallet,
)
from core.optimizer import optimize
from core.trip_models import TripSpec

PASSWORD = "long-password-123"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def _client(tmp_path: Path) -> tuple[TestClient, AccountStore]:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app, base_url="https://testserver")
    client.post(
        "/auth/register", json={"email": "traveler@example.com", "password": PASSWORD}
    )
    client.post(
        "/auth/login", json={"email": "traveler@example.com", "password": PASSWORD}
    )
    return client, store


def _csrf(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(CSRF_COOKIE)
    assert token is not None
    return {CSRF_HEADER: token}


def _add(client: TestClient, **body: object) -> dict[str, object]:
    response = client.post("/account/wallet", json=body, headers=_csrf(client))
    assert response.status_code == 201, response.text
    return dict(response.json())


# --- projection rules, through the route ----------------------------------- #


def test_duplicate_currencies_collapse_by_max_not_sum(tmp_path: Path) -> None:
    """Summing pooled issuer balances would overstate transferable points."""
    client, _store = _client(tmp_path)
    _add(
        client,
        card_id="hdfc-infinia",
        nickname="One",
        points_balances={"hdfc-reward-points": 100},
    )
    _add(
        client,
        card_id="axis-atlas",
        nickname="Two",
        points_balances={"hdfc-reward-points": 250},
    )

    projection = client.get("/account/wallet/projection").json()
    assert projection["points_balances"] == {"hdfc-reward-points": 250}
    assert projection["points_balances"]["hdfc-reward-points"] != 350


def test_two_entries_for_one_product_yield_one_optimizer_card_id(
    tmp_path: Path,
) -> None:
    """Two physical cards of one product must not look like two products."""
    client, _store = _client(tmp_path)
    first = _add(client, card_id="hdfc-infinia", nickname="Personal", last4="1111")
    second = _add(client, card_id="hdfc-infinia", nickname="Add-on", last4="2222")
    assert first["id"] != second["id"]

    # Both rows remain listable and distinguishable to the human...
    listed = client.get("/account/wallet").json()
    assert len(listed) == 2
    assert {e["last4"] for e in listed} == {"1111", "2222"}

    # ...but the optimizer sees one product.
    assert client.get("/account/wallet/projection").json()["card_ids"] == [
        "hdfc-infinia"
    ]


def test_projection_ordering_is_deterministic_after_a_sqlite_reopen(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "accounts.sqlite"
    store = AccountStore.open(db_path)
    user = store.create_user(
        email="traveler@example.com", now=NOW, user_id="u-traveler"
    )
    for card_id, nickname in (
        ("hdfc-infinia", "B"),
        ("axis-atlas", "A"),
        ("sbi-cashback", "C"),
    ):
        store.add_wallet_entry(
            user_id=user.id,
            card_id=card_id,
            nickname=nickname,
            now=NOW,
            points_balances={"hdfc-reward-points": 10},
        )

    before = build_user_wallet(store.wallet_entries(user.id))
    after = build_user_wallet(AccountStore.open(db_path).wallet_entries(user.id))
    assert before == after
    assert before.card_ids == sorted(before.card_ids)
    assert before.card_ids == ["axis-atlas", "hdfc-infinia", "sbi-cashback"]


# --- the authenticated empty wallet ---------------------------------------- #


def test_authenticated_empty_wallet_projects_to_an_empty_user_wallet(
    tmp_path: Path,
) -> None:
    client, _store = _client(tmp_path)
    projection = client.get("/account/wallet/projection").json()
    assert projection == {"card_ids": [], "points_balances": {}}


def test_empty_persisted_wallet_reaches_planning_empty(tmp_path: Path) -> None:
    """The session handoff must not invent cards the traveler never stored."""
    _unused, store = _client(tmp_path)
    user = store.get_user_by_email("traveler@example.com")
    assert user is not None
    assert store.wallet_entries(user.id) == []

    _home, _prefs, wallet = _profile_for_user(store, user)
    assert wallet == UserWallet(card_ids=[], points_balances={})


def test_an_empty_projected_wallet_produces_truthful_cash_only_output(
    tmp_path: Path,
) -> None:
    """Empty wallet in, cash-only out — with no fabricated rewards."""
    _unused, store = _client(tmp_path)
    user = store.get_user_by_email("traveler@example.com")
    assert user is not None
    _home, _prefs, wallet = _profile_for_user(store, user)

    trip = CostedTrip(
        origin="DEL",
        destination="SIN",
        home_currency="INR",
        booking_date=date(2026, 8, 1),
        trip_start_date=date(2026, 9, 1),
        lines=[
            SpendLineItem(
                id="dining:1",
                label="Dinner",
                category=SpendCategory.DINING,
                amount_minor=500000,
                currency="INR",
                available_channels=[Channel.POS_ABROAD],
            )
        ],
    )
    result = optimize(trip, wallet, load_kb(), OptimizationPrefs())

    assert {a.card_id for a in result.assignments} == {"cash_only"}
    assert result.rewards_value_minor == 0
    assert result.effective_cost_minor == 500000
    assert any("no valid cards" in item.casefold() for item in result.assumptions)


def test_the_authenticated_path_never_substitutes_the_demo_wallet() -> None:
    """Structural guard: the request-time path must not reach demo fixtures.

    ``core.optimizer.demo_data.demo_wallet`` exists for the CLI and golden
    tests. If it ever became importable from the API or orchestration layer, an
    authenticated traveler's deliberately-empty wallet could be silently
    replaced by a demo one, which would misreport their rewards as real.
    """
    backend = pathlib.Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for package in ("api", "agents"):
        for path in (backend / package).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if "demo_data" in source or "demo_wallet" in source:
                offenders.append(str(path.relative_to(backend)))
    assert offenders == [], f"demo wallet reachable from request path: {offenders}"


def test_the_legacy_plan_path_still_takes_a_client_supplied_wallet() -> None:
    """The unauthenticated fixture/demo `/plan` contract is unchanged.

    A3 adds an authenticated projection; it does not repoint the legacy path at
    account storage. ``TripSpec.wallet`` stays a required request field with no
    server-side default, so nothing about that flow changed.
    """
    field = TripSpec.model_fields["wallet"]
    assert field.is_required(), "TripSpec.wallet must stay caller-supplied"
    assert field.default_factory is None
