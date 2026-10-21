"""A3 Task 5 — the authenticated /account/wallet API boundary.

Negative paths first. Every assertion here is about something that must *not*
be possible: reading another user's wallet, learning whether their entry id
exists, mutating without CSRF, supplying your own ``user_id``, storing a PAN,
or getting a raw database exception back.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from accounts.store import AccountStore
from api.auth import CSRF_COOKIE, CSRF_HEADER, get_store
from api.main import app

PASSWORD = "long-password-123"
CARD = "hdfc-infinia"


def _client(tmp_path: Path, email: str = "traveler@example.com") -> TestClient:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app, base_url="https://testserver")
    client.post("/auth/register", json={"email": email, "password": PASSWORD})
    client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return client


def _second_client(email: str) -> TestClient:
    """A second signed-in user sharing the same overridden store."""
    client = TestClient(app, base_url="https://testserver")
    client.post("/auth/register", json={"email": email, "password": PASSWORD})
    client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return client


def _csrf(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(CSRF_COOKIE)
    assert token is not None
    return {CSRF_HEADER: token}


def _add(client: TestClient, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {"card_id": CARD, "nickname": "Primary"}
    body.update(overrides)
    response = client.post("/account/wallet", json=body, headers=_csrf(client))
    assert response.status_code == 201, response.text
    return dict(response.json())


# --- authentication and CSRF ------------------------------------------------ #


def test_every_route_requires_authentication(tmp_path: Path) -> None:
    app.dependency_overrides.clear()
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app) as anon:
        assert anon.get("/account/wallet").status_code == 401
        assert anon.get("/account/wallet/projection").status_code == 401
        assert anon.get("/account/card-products").status_code == 401
        assert anon.post("/account/wallet", json={"card_id": CARD}).status_code == 401
        assert anon.patch("/account/wallet/x", json={}).status_code == 401
        assert anon.delete("/account/wallet/x").status_code == 401


def test_mutations_require_csrf(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert (
        client.post(
            "/account/wallet", json={"card_id": CARD, "nickname": "x"}
        ).status_code
        == 403
    )
    assert (
        client.patch("/account/wallet/x", json={"expected_version": 1}).status_code
        == 403
    )
    assert client.delete("/account/wallet/x").status_code == 403


# --- cross-user isolation --------------------------------------------------- #


def test_cross_user_access_is_indistinguishable_from_missing(tmp_path: Path) -> None:
    owner = _client(tmp_path, "traveler@example.com")
    entry = _add(owner)
    intruder = _second_client("intruder@example.com")

    real = intruder.patch(
        f"/account/wallet/{entry['id']}",
        json={"expected_version": 1, "nickname": "stolen"},
        headers=_csrf(intruder),
    )
    fake = intruder.patch(
        "/account/wallet/does-not-exist",
        json={"expected_version": 1, "nickname": "stolen"},
        headers=_csrf(intruder),
    )
    assert real.status_code == fake.status_code == 404
    # Identical bodies: the response must not reveal that the entry exists.
    assert real.json() == fake.json()

    real_del = intruder.delete(f"/account/wallet/{entry['id']}", headers=_csrf(intruder))
    fake_del = intruder.delete("/account/wallet/does-not-exist", headers=_csrf(intruder))
    assert real_del.status_code == fake_del.status_code == 404
    assert real_del.json() == fake_del.json()

    # The owner's entry is untouched.
    listed = owner.get("/account/wallet").json()
    assert [e["id"] for e in listed] == [entry["id"]]
    assert listed[0]["nickname"] == "Primary"


def test_intruder_wallet_listing_is_empty_not_the_owners(tmp_path: Path) -> None:
    owner = _client(tmp_path, "traveler@example.com")
    _add(owner)
    intruder = _second_client("intruder@example.com")
    assert intruder.get("/account/wallet").json() == []
    assert intruder.get("/account/wallet/projection").json()["card_ids"] == []


def test_body_supplied_user_id_is_rejected(tmp_path: Path) -> None:
    """Authority comes from the session, never the payload."""
    owner = _client(tmp_path, "traveler@example.com")
    intruder = _second_client("intruder@example.com")
    response = intruder.post(
        "/account/wallet",
        json={"card_id": CARD, "nickname": "x", "user_id": "u-traveler"},
        headers=_csrf(intruder),
    )
    assert response.status_code == 422
    assert owner.get("/account/wallet").json() == []


# --- payload validation ----------------------------------------------------- #


def test_forbidden_payment_fields_are_rejected(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for field, value in (
        ("pan", "4111111111111111"),
        ("card_number", "4111111111111111"),
        ("cvv", "123"),
        ("cvc", "123"),
        ("expiry", "12/30"),
        ("pin", "1234"),
    ):
        response = client.post(
            "/account/wallet",
            json={"card_id": CARD, "nickname": "x", field: value},
            headers=_csrf(client),
        )
        assert response.status_code == 422, f"{field} was accepted"
    assert client.get("/account/wallet").json() == []


def test_unknown_card_product_is_rejected(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/account/wallet",
        json={"card_id": "not-a-real-card", "nickname": "x"},
        headers=_csrf(client),
    )
    assert response.status_code == 422
    assert client.get("/account/wallet").json() == []


def test_malformed_safe_fields_are_rejected(tmp_path: Path) -> None:
    client = _client(tmp_path)
    bad_bodies: list[dict[str, object]] = [
        {"card_id": CARD, "nickname": "x", "last4": "12"},
        {"card_id": CARD, "nickname": "x", "last4": "abcd"},
        {"card_id": CARD, "nickname": "x", "last4": "4111111111111111"},
        {"card_id": CARD, "nickname": "x", "statement_day": 0},
        {"card_id": CARD, "nickname": "x", "statement_day": 32},
        {"card_id": CARD, "nickname": "x", "opened_on": "not-a-date"},
        {
            "card_id": CARD,
            "nickname": "x",
            "points_balances": {"hdfc-reward-points": -5},
        },
    ]
    for body in bad_bodies:
        response = client.post("/account/wallet", json=body, headers=_csrf(client))
        assert response.status_code == 422, f"accepted {body}"
    assert client.get("/account/wallet").json() == []


# --- typed conflicts -------------------------------------------------------- #


def test_stale_expected_version_is_a_typed_409(tmp_path: Path) -> None:
    client = _client(tmp_path)
    entry = _add(client)
    first = client.patch(
        f"/account/wallet/{entry['id']}",
        json={"expected_version": 1, "nickname": "v2"},
        headers=_csrf(client),
    )
    assert first.status_code == 200
    stale = client.patch(
        f"/account/wallet/{entry['id']}",
        json={"expected_version": 1, "nickname": "v2-again"},
        headers=_csrf(client),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "wallet_version_conflict"


def test_conflicting_event_reuse_is_a_typed_409(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _add(client, client_event_id="evt-1")
    response = client.post(
        "/account/wallet",
        json={"card_id": CARD, "nickname": "Different", "client_event_id": "evt-1"},
        headers=_csrf(client),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "wallet_event_conflict"


def test_identical_replay_returns_the_original_result(tmp_path: Path) -> None:
    client = _client(tmp_path)
    body = {"card_id": CARD, "nickname": "Primary", "client_event_id": "evt-replay"}
    first = client.post("/account/wallet", json=body, headers=_csrf(client))
    again = client.post("/account/wallet", json=body, headers=_csrf(client))
    assert first.status_code == 201
    assert again.status_code in (200, 201)
    assert again.json()["id"] == first.json()["id"]
    assert len(client.get("/account/wallet").json()) == 1


# --- response hygiene ------------------------------------------------------- #


def test_no_authentication_material_appears_in_responses(tmp_path: Path) -> None:
    client = _client(tmp_path)
    entry = _add(client, last4="1234", points_balances={"hdfc-reward-points": 100})
    bodies = [
        client.get("/account/wallet").text,
        client.get("/account/wallet/projection").text,
        client.get("/account/card-products").text,
        str(entry),
    ]
    forbidden = (
        "password",
        "password_hash",
        "token_hash",
        "tp_session",
        "argon2",
        "credential",
        "session_token",
    )
    for body in bodies:
        lowered = body.lower()
        for needle in forbidden:
            assert needle not in lowered, f"{needle!r} leaked in {body[:120]}"


def test_projection_is_derived_and_has_no_write_endpoint(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _add(client, points_balances={"hdfc-reward-points": 100})
    projection = client.get("/account/wallet/projection")
    assert projection.status_code == 200
    assert projection.json()["card_ids"] == [CARD]
    # UserWallet is never stored, so there is no way to write it.
    for method in (client.post, client.put):
        response = method("/account/wallet/projection", json={}, headers=_csrf(client))
        assert response.status_code in (404, 405)
    # PATCH does match /wallet/{entry_id}; with a well-formed body it resolves
    # to "no entry called 'projection'", never to a writable projection.
    patched = client.patch(
        "/account/wallet/projection",
        json={"expected_version": 1, "nickname": "x"},
        headers=_csrf(client),
    )
    assert patched.status_code == 404
    assert patched.json()["detail"]["code"] == "wallet_entry_not_found"
    # The real projection is unchanged.
    assert client.get("/account/wallet/projection").json()["card_ids"] == [CARD]


def test_card_products_listing_is_available_to_a_signed_in_user(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    response = client.get("/account/card-products")
    assert response.status_code == 200
    products = response.json()
    assert products, "the seeded KB must expose card products"
    assert [p["card_id"] for p in products] == sorted(p["card_id"] for p in products)
    assert set(products[0]) == {"card_id", "display_name", "issuer", "is_eligible"}


def test_happy_path_round_trip(tmp_path: Path) -> None:
    client = _client(tmp_path)
    entry = _add(
        client,
        last4="1234",
        statement_day=11,
        opened_on="2026-10-19",
        points_balances={"hdfc-reward-points": 100},
    )
    assert entry["version"] == 1

    patched = client.patch(
        f"/account/wallet/{entry['id']}",
        json={"expected_version": 1, "nickname": "Renamed"},
        headers=_csrf(client),
    )
    assert patched.status_code == 200
    assert patched.json()["nickname"] == "Renamed"
    assert patched.json()["version"] == 2

    removed = client.delete(f"/account/wallet/{entry['id']}", headers=_csrf(client))
    assert removed.status_code in (200, 204)
    assert client.get("/account/wallet").json() == []
