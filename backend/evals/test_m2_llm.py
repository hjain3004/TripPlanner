from datetime import date

import pytest

from agents.llm import LLMCallError, ScriptedLLMClient, complete_with_repair
from agents.models import TripSpec
from core.models import OptimizationPrefs, UserWallet


VALID_TRIP = {
    "home_country": "IN",
    "origin_city": "DEL",
    "destination_city": "SIN",
    "start_date": "2026-08-01",
    "end_date": "2026-08-05",
    "travelers": 2,
    "budget_minor": 25000000,
    "budget_currency": "INR",
    "style": "balanced",
    "interests": ["nature"],
    "pace": "moderate",
    "dietary": [],
    "wallet": {"card_ids": ["voyager-prime"], "points_balances": {}},
    "optimization": {"objective": "max_savings"},
    "unresolved": [],
}


def test_scripted_llm_counts_invocations() -> None:
    client = ScriptedLLMClient({"intake": [VALID_TRIP]})
    result = client.complete_json(
        node="intake",
        system="system",
        user="user",
        schema=TripSpec,
    )
    assert isinstance(result, TripSpec)
    assert client.invocations["intake"] == 1


def test_complete_with_repair_retries_once_after_schema_failure() -> None:
    client = ScriptedLLMClient({"intake": [{"travelers": 0}, VALID_TRIP]})
    result = complete_with_repair(
        client,
        node="intake",
        system="system",
        user="user",
        schema=TripSpec,
    )
    assert result.travelers == 2
    assert result.start_date == date(2026, 8, 1)
    assert client.invocations["intake"] == 2


def test_complete_with_repair_raises_after_second_schema_failure() -> None:
    client = ScriptedLLMClient({"intake": [{"travelers": 0}, {"travelers": 0}]})
    with pytest.raises(LLMCallError):
        complete_with_repair(
            client,
            node="intake",
            system="system",
            user="user",
            schema=TripSpec,
        )


def test_scripted_llm_can_raise_node_exception() -> None:
    client = ScriptedLLMClient({"critic": [RuntimeError("critic down")]})
    with pytest.raises(RuntimeError, match="critic down"):
        client.complete_json(node="critic", system="s", user="u", schema=TripSpec)
