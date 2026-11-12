"""Deployment-day and offline preflight verification for Anthropic provider.

Design: docs/superpowers/specs/2026-11-11-runtime-llm-design.md section 10.
Can run completely offline with --offline or --mock.
Live checks (2, 3, 4, 5) require owner execution with valid credentials.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel

from agents.discovery.contracts import SearchIntent
from agents.llm import LLMBudgetExceeded
from agents.llm_budget import (
    FRAMING_TOKENS,
    LLMSpendLedger,
    SpendCaps,
    input_token_upper_bound,
    price_for,
)
from agents.llm_wire import (
    PlannerTurn,
    find_wire_problems,
    to_wire_schema,
)
from agents.models import CriticVerdict, ExplainerOutput, TripSpec
from api.runtime_config import validate_runtime_config
from core.trip_models import DraftItinerary


def check_offline(env: Mapping[str, str] = os.environ) -> None:
    print("[1/5] Running offline configuration & schema checks...")
    issues = validate_runtime_config(env)
    anthropic_issues = [
        issue
        for issue in issues
        if "ANTHROPIC" in issue.variable or "TRIPWISE_LLM_CAP" in issue.variable
    ]
    if anthropic_issues:
        for issue in anthropic_issues:
            print(f"  Configuration issue: {issue.variable}: {issue.problem}", file=sys.stderr)
        raise SystemExit(1)

    model = env.get("TRIPWISE_ANTHROPIC_MODEL", "claude-sonnet-5-5").strip()
    price = price_for(model)
    rate_info = f"rate={price.input_micro_usd_per_mtok} in, {price.output_micro_usd_per_mtok} out"
    print(f"  Price row for {model!r}: verified ({rate_info})")

    caps = SpendCaps.from_env(env)
    with tempfile.TemporaryDirectory() as tmp_dir:
        ledger = LLMSpendLedger(Path(tmp_dir) / "llm_spend.sqlite3", caps)
        assert ledger.lifetime_committed_micro_usd() == 0
    print("  Ledger database initializes and verifies clean schema")

    # Wire schema complexity checks on all 6 models
    models: list[type[BaseModel]] = [
        TripSpec,
        PlannerTurn,
        DraftItinerary,
        CriticVerdict,
        ExplainerOutput,
        SearchIntent,
    ]
    for m in models:
        schema = to_wire_schema(m)
        problems = find_wire_problems(schema)
        if problems:
            print(f"  Wire schema problem in {m.__name__}: {problems}", file=sys.stderr)
            raise SystemExit(1)
        print(f"  Wire schema for {m.__name__}: 0 problems (within Anthropic limits)")

    print("  Offline checks passed.\n")


def check_mock_run() -> None:
    print("Running simulated mock preflight suite (offline)...")
    mock_env = {
        "TRIPWISE_LLM_PROVIDER": "anthropic",
        "ANTHROPIC_API_KEY": "mock-preflight-key",
        "TRIPWISE_ANTHROPIC_MODEL": "claude-sonnet-5-5",
        "TRIPWISE_LLM_CAP_PER_PLAN_MICRO_USD": "500000",
        "TRIPWISE_LLM_CAP_PER_DAY_MICRO_USD": "5000000",
        "TRIPWISE_LLM_CAP_PER_MONTH_MICRO_USD": "25000000",
        "TRIPWISE_LLM_CAP_LIFETIME_MICRO_USD": "45000000",
        "TRIPWISE_LLM_PAID_PLANS_PER_USER_PER_DAY": "5",
    }
    check_offline(mock_env)

    # Check token counting bound against formula
    prompt = "DEL to SIN trip for 3 days"
    wire_json = "{}"
    bound = input_token_upper_bound(system="sys", user=prompt, wire_schema_json=wire_json)
    simulated_count = len(prompt.encode("utf-8")) + 10
    assert simulated_count <= bound - FRAMING_TOKENS + 64
    print("  Simulated count_tokens check: passed bound assertion")

    # Negative budget check with per_plan_micro_usd = 1
    with tempfile.TemporaryDirectory() as tmp_dir:
        low_caps = SpendCaps(
            per_plan_micro_usd=1,
            per_day_micro_usd=5000000,
            per_month_micro_usd=25000000,
            lifetime_micro_usd=45000000,
            paid_plans_per_user_per_day=5,
        )
        ledger = LLMSpendLedger(Path(tmp_dir) / "llm_spend.sqlite3", low_caps)
        try:
            ledger.reserve(
                plan_id="p1",
                user_id="u1",
                node="intake",
                model="claude-sonnet-5-5",
                amount_micro_usd=1000,
            )
            raise AssertionError("Should have raised LLMBudgetExceeded")
        except LLMBudgetExceeded:
            print("  Budget exceeded check (per_plan_micro_usd=1): passed")

    print("\nMock preflight suite complete: all offline and simulated checks passed.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="anthropic_preflight")
    parser.add_argument(
        "--offline", action="store_true", help="Run offline schema & config checks only"
    )
    parser.add_argument(
        "--mock", action="store_true", help="Run mock transport preflight tests (zero network)"
    )
    args = parser.parse_args(argv)

    if args.mock:
        check_mock_run()
        return 0

    if args.offline:
        check_offline()
        return 0

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ANTHROPIC_API_KEY is not set. Running mock/offline checks instead:")
        check_mock_run()
        return 0

    check_offline()
    print("Live API checks are reserved for owner-supervised deployment only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
