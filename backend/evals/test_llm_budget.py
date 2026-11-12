"""Spend arithmetic and the reservation ledger (runtime LLM design, section 7).

Expected values are worked by hand from the price rows, not copied from the code.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agents.llm import LLMBudgetExceeded
from agents.llm_budget import (
    FRAMING_TOKENS,
    PRICE_TABLE,
    LLMSpendLedger,
    SpendCaps,
    UsageCounts,
    input_token_upper_bound,
    price_for,
    reservation_micro_usd,
    settled_micro_usd,
)

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def caps(**updates: int) -> SpendCaps:
    base = {
        "per_plan_micro_usd": 5_000,
        "per_day_micro_usd": 50_000,
        "per_month_micro_usd": 500_000,
        "paid_plans_per_user_per_day": 2,
    }
    base.update(updates)
    return SpendCaps(**base)


def ledger(tmp_path: Path, clock: datetime = NOW, **updates: int) -> LLMSpendLedger:
    return LLMSpendLedger(tmp_path / "llm_spend.sqlite3", caps(**updates), now=lambda: clock)


def reserve(db: LLMSpendLedger, plan: str = "p1", user: str | None = "u1", amount: int = 1_000):
    return db.reserve(plan_id=plan, user_id=user, node="intake", model="m", amount_micro_usd=amount)


def test_reservation_is_the_worst_case_for_each_model() -> None:
    # 10_000 input tokens and 4_096 max output, micro-USD:
    #   opus   10_000*4 + 4_096*20 = 40_000 + 81_920 = 121_920
    #   sonnet 10_000*2 + 4_096*10 = 20_000 + 40_960 = 60_960
    #   haiku  10_000*0.1 + 4_096*0.5 = 1_000 + 2_048 = 3_048
    got = {
        name: reservation_micro_usd(price_for(name), input_upper=10_000, max_tokens=4_096)
        for name in PRICE_TABLE
    }
    assert got == {
        "claude-opus-5-5": 121_920,
        "claude-sonnet-5-5": 60_960,
        "claude-haiku-5-5": 3_048,
    }


def test_haiku_switches_to_long_prompt_rates_above_the_threshold() -> None:
    haiku = price_for("claude-haiku-5-5")
    # 100_000 tokens is still the short rate; 100_001 prices input at 0.5 and output at 2.5:
    #   100_001*0.5 + 1_000*2.5 = 50_000.5 + 2_500 = 52_500.5 -> 52_501
    assert reservation_micro_usd(haiku, input_upper=100_000, max_tokens=1_000) == 10_500
    assert reservation_micro_usd(haiku, input_upper=100_001, max_tokens=1_000) == 52_501


def test_settlement_prices_cache_tokens_separately_and_rounds_up() -> None:
    opus = price_for("claude-opus-5-5")
    usage = UsageCounts(
        input_tokens=1_000,
        output_tokens=500,
        cache_creation_input_tokens=200,
        cache_read_input_tokens=300,
    )
    # 1_000*4 + 500*20 + 200*5 + 300*0.2 = 4_000 + 10_000 + 1_000 + 60 = 15_060
    assert settled_micro_usd(opus, usage) == 15_060
    # One input token at 0.1 micro-USD rounds up to a whole micro-USD.
    assert settled_micro_usd(price_for("claude-haiku-5-5"), UsageCounts(input_tokens=1)) == 1


def test_cache_write_price_is_one_and_a_quarter_times_input() -> None:
    for price in PRICE_TABLE.values():
        assert (
            price.cache_write_5m_micro_usd_per_mtok == price.input_micro_usd_per_mtok * 125 // 100
        )
        assert price.needs_verification is True
        assert price.source_url.startswith("https://")


def test_unknown_model_fails_closed() -> None:
    with pytest.raises(LLMBudgetExceeded) as error:
        price_for("claude-unknown")
    assert error.value.scope == "unknown_model"


def test_input_upper_bound_counts_utf8_bytes_not_characters() -> None:
    # "₹" is one character and three bytes.
    assert (
        input_token_upper_bound(system="₹", user="ab", wire_schema_json="{}")
        == 3 + 2 + 2 + FRAMING_TOKENS
    )


def test_caps_come_from_positive_integers_only() -> None:
    env = {
        "TRIPWISE_LLM_CAP_PER_PLAN_MICRO_USD": "1000",
        "TRIPWISE_LLM_CAP_PER_DAY_MICRO_USD": "2000",
        "TRIPWISE_LLM_CAP_PER_MONTH_MICRO_USD": "3000",
        "TRIPWISE_LLM_PAID_PLANS_PER_USER_PER_DAY": "4",
    }
    assert SpendCaps.from_env(env) == SpendCaps(1000, 2000, 3000, 4)
    for bad in ("0", "-1", "1.5", "", "abc"):
        with pytest.raises(ValueError):
            SpendCaps.from_env({**env, "TRIPWISE_LLM_CAP_PER_DAY_MICRO_USD": bad})
    with pytest.raises(ValueError):
        SpendCaps(1, 1, 1, True)


def test_per_plan_cap_counts_reserved_and_uncertain_but_not_released(tmp_path: Path) -> None:
    db = ledger(tmp_path, per_plan_micro_usd=3_000)
    first = reserve(db)
    second = reserve(db)
    third = reserve(db)
    with pytest.raises(LLMBudgetExceeded) as error:
        reserve(db)
    assert error.value.scope == "per_plan"
    db.release(first)  # confirmed not billed: the allowance returns
    reserve(db)
    db.mark_uncertain(second)  # may have been billed: stays charged
    with pytest.raises(LLMBudgetExceeded):
        reserve(db)
    assert db.plan_committed_micro_usd("p1") == 3_000
    del third


def test_settlement_replaces_the_reservation_with_actual_spend(tmp_path: Path) -> None:
    db = ledger(tmp_path, per_plan_micro_usd=2_000)
    rid = reserve(db, amount=1_500)
    db.settle(rid, UsageCounts(input_tokens=10, output_tokens=5), 400)
    assert db.plan_committed_micro_usd("p1") == 400
    reserve(db, amount=1_500)  # the unspent part is available again
    with pytest.raises(ValueError):
        db.settle(rid, UsageCounts(), 1)  # a settled reservation cannot be settled twice


def test_settling_above_the_reservation_opens_a_breaker_that_blocks_dispatch(
    tmp_path: Path,
) -> None:
    db = ledger(tmp_path)
    rid = reserve(db, amount=500)
    db.settle(rid, UsageCounts(input_tokens=1), 900)
    assert db.plan_committed_micro_usd("p1") == 900  # the real figure is kept
    assert "reservation_underestimated" in db.open_breakers()
    with pytest.raises(LLMBudgetExceeded) as error:
        reserve(db, plan="other")
    assert error.value.scope == "reservation_underestimated"
    db.reset_breaker("reservation_underestimated", operator="owner")
    reserve(db, plan="other")
    with pytest.raises(ValueError):
        db.reset_breaker("x", operator="  ")


def test_day_and_month_caps_use_utc_calendar_windows(tmp_path: Path) -> None:
    path = tmp_path / "llm_spend.sqlite3"
    day_one = LLMSpendLedger(
        path, caps(per_day_micro_usd=2_000, per_month_micro_usd=2_500), now=lambda: NOW
    )
    reserve(day_one, plan="a", user="u1", amount=2_000)
    with pytest.raises(LLMBudgetExceeded) as error:
        reserve(day_one, plan="b", user="u2", amount=1_000)
    assert error.value.scope == "per_day"
    next_day = LLMSpendLedger(
        path,
        caps(per_day_micro_usd=2_000, per_month_micro_usd=2_500),
        now=lambda: NOW + timedelta(days=1),
    )
    reserve(next_day, plan="c", user="u3", amount=500)  # new day, same month: 2_500 used
    with pytest.raises(LLMBudgetExceeded) as month:
        reserve(next_day, plan="d", user="u4", amount=1)
    assert month.value.scope == "per_month"
    next_month = LLMSpendLedger(
        path,
        caps(per_day_micro_usd=2_000, per_month_micro_usd=2_500),
        now=lambda: NOW + timedelta(days=31),
    )
    reserve(next_month, plan="e", user="u5", amount=1_000)


def test_paid_plans_per_user_per_day_limits_new_plans_not_calls_within_one(
    tmp_path: Path,
) -> None:
    db = ledger(tmp_path, per_plan_micro_usd=10_000, paid_plans_per_user_per_day=2)
    reserve(db, plan="p1", amount=100)
    reserve(db, plan="p1", amount=100)  # more calls inside an existing plan are fine
    reserve(db, plan="p2", amount=100)
    with pytest.raises(LLMBudgetExceeded) as error:
        reserve(db, plan="p3", amount=100)
    assert error.value.scope == "plans_per_user_per_day"
    reserve(db, plan="p3", user="someone-else", amount=100)


def test_a_plan_whose_only_reservation_was_released_does_not_use_up_the_daily_plan_limit(
    tmp_path: Path,
) -> None:
    db = ledger(tmp_path, paid_plans_per_user_per_day=1)
    db.release(reserve(db, plan="p1"))
    reserve(db, plan="p2")


def test_restart_turns_stale_in_flight_reservations_into_charged_uncertain_ones(
    tmp_path: Path,
) -> None:
    path = tmp_path / "llm_spend.sqlite3"
    before = LLMSpendLedger(path, caps(), now=lambda: NOW)
    stale = reserve(before, plan="p1", amount=700)
    del stale
    after = LLMSpendLedger(path, caps(), now=lambda: NOW + timedelta(minutes=5))
    assert after.recover_stale(older_than=timedelta(seconds=40)) == 1
    assert after.recover_stale(older_than=timedelta(seconds=40)) == 0
    assert after.plan_committed_micro_usd("p1") == 700  # not refunded


def test_concurrent_reservations_across_connections_never_exceed_the_cap(tmp_path: Path) -> None:
    db = ledger(tmp_path, per_plan_micro_usd=5_000)
    outcomes: list[str] = []
    guard = threading.Lock()
    start = threading.Barrier(12)

    def worker() -> None:
        own = LLMSpendLedger(db.path, db.caps, now=lambda: NOW)  # its own connections
        start.wait()
        try:
            reserve(own, amount=1_000)
            result = "ok"
        except LLMBudgetExceeded:
            result = "refused"
        with guard:
            outcomes.append(result)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("ok") == 5
    assert outcomes.count("refused") == 7
    assert db.plan_committed_micro_usd("p1") == 5_000


def test_two_processes_share_one_allowance(tmp_path: Path) -> None:
    db = ledger(tmp_path, per_plan_micro_usd=3_000)
    script = (
        "import sys\n"
        "from datetime import datetime, UTC\n"
        "from pathlib import Path\n"
        "from agents.llm import LLMBudgetExceeded\n"
        "from agents.llm_budget import LLMSpendLedger, SpendCaps\n"
        "db = LLMSpendLedger(Path(sys.argv[1]), SpendCaps(3000, 50000, 500000, 2),"
        " now=lambda: datetime(2026, 11, 11, 12, tzinfo=UTC))\n"
        "ok = 0\n"
        "for _ in range(4):\n"
        "    try:\n"
        "        db.reserve(plan_id='p1', user_id='u1', node='n', model='m',"
        " amount_micro_usd=1000)\n"
        "        ok += 1\n"
        "    except LLMBudgetExceeded:\n"
        "        pass\n"
        "print(ok)\n"
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(db.path)],
            stdout=subprocess.PIPE,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        for _ in range(2)
    ]
    granted = sum(int((p.communicate()[0] or "0").strip()) for p in procs)
    assert granted == 3
    assert db.plan_committed_micro_usd("p1") == 3_000


def test_ledger_stores_counts_only(tmp_path: Path) -> None:
    import sqlite3

    db = ledger(tmp_path)
    rid = reserve(db)
    db.settle(rid, UsageCounts(input_tokens=3, output_tokens=2), 7)
    conn = sqlite3.connect(db.path)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(reservations)")]
    usage = conn.execute("SELECT usage_json FROM reservations").fetchone()[0]
    conn.close()
    assert not {"prompt", "response", "system", "user", "text"} & set(columns)
    assert usage == (
        '{"cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, '
        '"input_tokens": 3, "output_tokens": 2}'
    )


def test_operator_cli_lists_and_resets_breakers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from agents.llm_budget import main

    db = ledger(tmp_path)
    db.open_breaker("workspace_spend_limit", "provider said so")
    assert main(["--db", str(db.path), "breakers"]) == 0
    assert "workspace_spend_limit" in capsys.readouterr().out
    assert (
        main(
            [
                "--db",
                str(db.path),
                "reset-breaker",
                "--scope",
                "workspace_spend_limit",
                "--operator",
                "owner",
            ]
        )
        == 0
    )
    assert db.open_breakers() == {}
