"""Exact-match golden tests over the optimizer (spec 04 §1).

Parametrized across every ``evals/golden/*.yaml``. Each file embeds its own
fictional KB so the tests never depend on (re-verified) seed data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.models import OptimizerResult
from evals._harness import golden_files, load_case

_FILES = golden_files()


def _assignment(result: OptimizerResult, line_id: str):
    for a in result.assignments:
        if a.line.id == line_id:
            return a
    raise AssertionError(f"no assignment for line {line_id!r}")


@pytest.mark.parametrize("path", _FILES, ids=[p.stem for p in _FILES])
def test_optimizer_golden(path: Path) -> None:
    case = load_case(path)
    result: OptimizerResult = case["result"]
    expect = case["expect"]

    for line_id, exp in expect.get("assignments", {}).items():
        a = _assignment(result, line_id)
        if "card" in exp:
            assert a.card_id == exp["card"], f"{line_id}.card"
        if "channel" in exp:
            assert a.channel.value == exp["channel"], f"{line_id}.channel"
        if "points" in exp:
            assert a.points_earned == exp["points"], f"{line_id}.points"
        if "points_value_minor" in exp:
            assert a.points_value_minor == exp["points_value_minor"], f"{line_id}.points_value"
        if "forex_fee_minor" in exp:
            assert a.forex_fee_minor == exp["forex_fee_minor"], f"{line_id}.forex_fee"
        if "benefit_minor" in exp:
            assert a.benefit_minor == exp["benefit_minor"], f"{line_id}.benefit"
        if "offers" in exp:
            got = sorted(o.offer_id for o in a.offers_applied)
            assert got == sorted(exp["offers"]), f"{line_id}.offers"
        if "discount_minor" in exp:
            got_d = sum(o.discount_minor for o in a.offers_applied)
            assert got_d == exp["discount_minor"], f"{line_id}.discount"
        if "explanation_contains" in exp:
            blob = " | ".join(a.explanation)
            assert exp["explanation_contains"] in blob, f"{line_id}.explanation ({blob})"

    totals = expect.get("totals", {})
    field_map = {
        "gross": "gross_minor",
        "discounts": "discounts_minor",
        "rewards_value": "rewards_value_minor",
        "forex_fees": "forex_fees_minor",
        "effective_cost": "effective_cost_minor",
        "cash_outlay_now": "cash_outlay_now_minor",
        "deferred_value": "deferred_value_minor",
        "savings_pct_bp": "savings_pct_bp",
    }
    for key, attr in field_map.items():
        if key in totals:
            assert getattr(result, attr) == totals[key], f"totals.{key}"

    if "pools_final" in expect:
        for key, val in expect["pools_final"].items():
            assert result.cap_pools_final.get(key) == val, f"pools_final.{key}"

    if "distinct_cards" in expect:
        used = {a.card_id for a in result.assignments}
        assert len(used) == expect["distinct_cards"], "distinct_cards"
