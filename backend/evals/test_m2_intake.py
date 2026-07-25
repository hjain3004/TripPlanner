from datetime import date

from agents.intake import run_intake
from agents.llm import ScriptedLLMClient
from core.db import load_kb


def _valid_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "home_country": "IN",
        "origin_city": "DEL",
        "destination_city": "SIN",
        "start_date": "2026-08-01",
        "end_date": "2026-08-05",
        "travelers": 2,
        "budget_minor": 25000000,
        "budget_currency": "INR",
        "style": "balanced",
        "interests": ["nature", "food"],
        "pace": "moderate",
        "dietary": ["vegetarian"],
        "wallet": {"card_ids": ["hdfc-infinia"], "points_balances": {}},
        "optimization": {"objective": "max_savings"},
        "unresolved": [],
    }
    payload.update(updates)
    return payload


def test_intake_returns_trip_spec_for_clean_request() -> None:
    result = run_intake("Plan DEL to SIN", load_kb(), ScriptedLLMClient({"intake": [_valid_payload()]}))
    assert result.needs_clarification is False
    assert result.trip_spec is not None
    assert result.trip_spec.start_date == date(2026, 8, 1)


def test_intake_returns_clarification_for_missing_dates() -> None:
    result = run_intake(
        "Plan Singapore",
        load_kb(),
        ScriptedLLMClient({"intake": [_valid_payload(unresolved=["missing dates"])]}),
    )
    assert result.needs_clarification is True
    assert "missing dates" in result.unresolved


def test_intake_rejects_unknown_card_id_as_unresolved() -> None:
    result = run_intake(
        "I have an unknown card",
        load_kb(),
        ScriptedLLMClient(
            {"intake": [_valid_payload(wallet={"card_ids": ["not-real"], "points_balances": {}})]}
        ),
    )
    assert result.needs_clarification is True
    assert result.trip_spec is None
    assert any("unknown card" in row for row in result.unresolved)


def test_intake_schema_failure_becomes_clarification() -> None:
    result = run_intake(
        "bad traveler count",
        load_kb(),
        ScriptedLLMClient({"intake": [_valid_payload(travelers=0), _valid_payload(travelers=0)]}),
    )
    assert result.needs_clarification is True
    assert result.trip_spec is None
    assert result.unresolved


def test_intake_unsupported_route_is_unresolved() -> None:
    result = run_intake(
        "Plan SFO to LHR",
        load_kb(),
        ScriptedLLMClient({"intake": [_valid_payload(origin_city="SFO", destination_city="LHR")]}),
    )
    assert result.needs_clarification is True
    assert any("unsupported route" in row for row in result.unresolved)
