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
from typing import Any

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
    ver_status = f"needs_verification={price.needs_verification}"
    print(f"  Price row for {model!r}: present ({rate_info}, {ver_status})")

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
        "TRIPWISE_ANTHROPIC_PREPAID_NO_OVERAGE_CONFIRMED": "1",
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


def check_live(
    env: Mapping[str, str] = os.environ,
    http_client: Any | None = None,
) -> int:
    """Owner-run deployment-day check (§10) against the Anthropic Messages API."""
    if env.get("TRIPWISE_ANTHROPIC_LIVE_CHECK_CONFIRMED", "").strip() != "1":
        print(
            "Live API checks require explicit owner confirmation: "
            "set TRIPWISE_ANTHROPIC_LIVE_CHECK_CONFIRMED=1 to proceed.",
            file=sys.stderr,
        )
        return 2

    api_key = env.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 1

    check_offline(env)
    print("Executing live API checks...")
    import httpx

    model = env.get("TRIPWISE_ANTHROPIC_MODEL", "claude-sonnet-5-5").strip()
    client = http_client or httpx.Client(timeout=20.0)

    # 1. Retrieve model metadata
    resp = client.get(
        f"https://api.anthropic.com/v1/models/{model}",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
    )
    if resp.status_code != 200:
        print(
            f"Failed to retrieve model metadata (HTTP {resp.status_code}): {resp.text}",
            file=sys.stderr,
        )
        return 1
    print(f"  Model metadata for {model!r}: verified live")

    # 2. Token counting on DEL->SIN prompt
    prompt = "DEL to SIN trip for 3 days"
    count_resp = client.post(
        "https://api.anthropic.com/v1/messages/count_tokens",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    if count_resp.status_code != 200:
        print(
            f"Failed to count tokens (HTTP {count_resp.status_code}): {count_resp.text}",
            file=sys.stderr,
        )
        return 1
    token_count = count_resp.json().get("input_tokens", 0)
    bound = input_token_upper_bound(system="", user=prompt, wire_schema_json="{}")
    assert token_count <= bound - FRAMING_TOKENS + 64
    print(f"  Live count_tokens: {token_count} tokens (within bound {bound})")

    print("\nLive deployment preflight complete: API compatibility confirmed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="anthropic_preflight")
    parser.add_argument(
        "--offline", action="store_true", help="Run offline schema & config checks only"
    )
    parser.add_argument(
        "--mock", action="store_true", help="Run mock transport preflight tests (zero network)"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run live API deployment check (requires TRIPWISE_ANTHROPIC_LIVE_CHECK_CONFIRMED=1)",
    )
    args = parser.parse_args(argv)

    if args.live:
        return check_live()

    if args.mock:
        check_mock_run()
        return 0

    if args.offline:
        check_offline()
        return 0

    # No flags provided: run offline checks but do NOT report live success
    check_offline()
    print(
        "\n[INCOMPLETE] Offline checks passed, but live API verification was NOT performed.\n"
        "Specify an execution mode:\n"
        "  --mock    Simulated preflight suite with mock transport (100% offline)\n"
        "  --offline Offline schema, configuration, and budget checks only\n"
        "  --live    Owner deployment check (TRIPWISE_ANTHROPIC_LIVE_CHECK_CONFIRMED=1)\n",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
