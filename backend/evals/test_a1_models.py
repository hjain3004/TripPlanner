from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from accounts.models import (
    FORBIDDEN_FIELD_NAMES,
    User,
    UserProfile,
    WalletEntry,
)

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def test_user_normalizes_email_to_lowercase() -> None:
    user = User(id="u1", email="  Himanshu.Jain@SJSU.edu ", created_at=NOW)

    assert user.email == "himanshu.jain@sjsu.edu"
    assert user.status == "active"


def test_user_rejects_an_email_without_a_domain() -> None:
    with pytest.raises(ValidationError):
        User(id="u1", email="himanshu", created_at=NOW)


def test_user_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        User(id="u1", email="a@b.com", created_at=NOW, password="hunter2")


def test_no_account_model_declares_a_forbidden_field() -> None:
    for model in (User, UserProfile):
        for field_name in model.model_fields:
            assert field_name.lower() not in FORBIDDEN_FIELD_NAMES, (
                f"{model.__name__}.{field_name} is a payment-instrument secret "
                "and must never be stored"
            )


def test_profile_normalizes_currency_and_origin_city() -> None:
    profile = UserProfile(
        user_id="u1",
        display_name="Himanshu",
        home_country="IN",
        home_currency="inr",
        origin_city="del",
        updated_at=NOW,
    )

    assert profile.home_currency == "INR"
    assert profile.origin_city == "DEL"


def test_profile_rejects_a_non_iata_origin_city() -> None:
    with pytest.raises(ValidationError):
        UserProfile(
            user_id="u1",
            display_name="Himanshu",
            home_country="IN",
            home_currency="INR",
            origin_city="Delhi",
            updated_at=NOW,
        )

def _entry(**overrides: object) -> WalletEntry:
    kwargs: dict[str, object] = {
        "id": "w1",
        "user_id": "u1",
        "card_id": "hdfc-infinia",
        "nickname": "Main Infinia",
        "added_at": NOW,
    }
    kwargs.update(overrides)
    return WalletEntry(**kwargs)  # type: ignore[arg-type]


def test_wallet_entry_stores_a_product_reference_with_optional_details() -> None:
    entry = _entry(
        last4="4321",
        statement_day=18,
        opened_on=date(2026, 5, 2),
        points_balances={"hdfc-reward-points": 140000},
    )

    assert entry.card_id == "hdfc-infinia"
    assert entry.last4 == "4321"
    assert entry.statement_day == 18
    assert entry.opened_on == date(2026, 5, 2)
    assert entry.points_balances == {"hdfc-reward-points": 140000}


def test_wallet_entry_defaults_omit_every_optional_detail() -> None:
    entry = _entry()

    assert entry.last4 is None
    assert entry.statement_day is None
    assert entry.opened_on is None
    assert entry.points_balances == {}


def test_wallet_entry_rejects_a_full_card_number_as_last4() -> None:
    with pytest.raises(ValidationError):
        _entry(last4="4111111111111111")


def test_wallet_entry_rejects_non_numeric_last4() -> None:
    with pytest.raises(ValidationError):
        _entry(last4="12a4")


def test_wallet_entry_rejects_an_out_of_range_statement_day() -> None:
    with pytest.raises(ValidationError):
        _entry(statement_day=0)
    with pytest.raises(ValidationError):
        _entry(statement_day=32)


def test_wallet_entry_rejects_a_negative_points_balance() -> None:
    with pytest.raises(ValidationError):
        _entry(points_balances={"hdfc-reward-points": -1})


def test_wallet_entry_rejects_a_smuggled_pan() -> None:
    with pytest.raises(ValidationError):
        _entry(pan="4111111111111111")


def test_wallet_entry_declares_no_forbidden_field() -> None:
    for field_name in WalletEntry.model_fields:
        assert field_name.lower() not in FORBIDDEN_FIELD_NAMES
