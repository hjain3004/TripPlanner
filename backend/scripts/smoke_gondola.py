"""Bounded, human-supervised live-smoke acceptance script for the Gondola
MCP integration (G3.2). NOT part of pytest/make gate — pytest's testpaths
is ["evals"], so this module is never collected. NOT imported by any
production code (agents/, api/, core/). Never run at normal application
startup.

Requires TWO explicit gates before touching the network:
  1. The ``--acknowledge`` command-line flag.
  2. ``TRIPWISE_GONDOLA_LIVE_SMOKE=1`` in the environment.
Both must be present or the script exits nonzero without any network call.

Reuses the already-implemented, already-tested TripPlanner Gondola
boundary exclusively: ``LiveGondolaTransport`` (host lock, tool-policy
enforcement, payload cap), ``GondolaCallBudget`` (persistent per-exercise
call ceiling), ``ALLOWED_TOOLS``/``DENIED_TOOLS``, and
``KeychainTokenStore`` for the authenticated phase. Never issues an ad-hoc
HTTP request of its own.

Hard-caps the entire acceptance exercise at 2 anonymous + 2 authenticated
real network calls (matching ``GondolaCallBudget.CALLS_PER_PLAN`` under two
distinct plan ids). Never prints a raw MCP response, token, cookie,
Authorization header, or client secret — only sanitized structural
summaries (counts, field-presence booleans, elapsed time, error
classification). Exits nonzero on any safety-policy violation. Never calls
a booking, mutation, payment, or account-history tool — enforced by the
same static allowlist every other Gondola call path uses.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from gateway.travel.adapters.gondola.budget import GondolaCallBudget
from gateway.travel.adapters.gondola.mcp_client import ALLOWED_HOST, LiveGondolaTransport
from gateway.travel.adapters.gondola.oauth import REQUIRED_SCOPE, KeychainTokenStore
from gateway.travel.adapters.gondola.tool_policy import ALLOWED_TOOLS, DENIED_TOOLS
from gateway.travel.errors import TravelGatewayError

MCP_ENDPOINT = f"https://{ALLOWED_HOST}/mcp"
LIVE_SMOKE_ENV_VAR = "TRIPWISE_GONDOLA_LIVE_SMOKE"
BUDGET_DB_PATH = Path(__file__).parent / ".gondola_smoke_budget.sqlite"
GONDOLA_FIXTURES_DIR = (
    Path(__file__).parent.parent / "gateway" / "travel" / "adapters" / "gondola" / "fixtures"
)
HIGH_RISK_TOOL_NAMES = frozenset(
    {"book_hotel", "book_vehicle", "get_payment_methods", "cancel_vehicle_booking"}
)


def require_gates(acknowledged: bool) -> None:
    if not acknowledged:
        print(
            "Refusing to run: pass --acknowledge to confirm you understand this makes a "
            f"real, bounded network call to {MCP_ENDPOINT}.",
            file=sys.stderr,
        )
        sys.exit(2)
    if os.environ.get(LIVE_SMOKE_ENV_VAR, "").strip().lower() not in {"1", "true", "yes"}:
        print(
            f"Refusing to run: set {LIVE_SMOKE_ENV_VAR}=1 in the environment to explicitly "
            "enable live Gondola smoke calls.",
            file=sys.stderr,
        )
        sys.exit(2)


def sanitize_structural_fixture(value: Any) -> Any:
    """Recursively replace every leaf value in a real provider response with
    a synthetic placeholder, preserving key names, container structure, and
    list lengths. Used to turn a real Gondola response into a fixture that
    is genuinely useful for schema reconciliation (real field names) without
    ever persisting a real price, name, identifier, or URL."""
    if isinstance(value, dict):
        return {k: sanitize_structural_fixture(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_structural_fixture(v) for v in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return 12345
    if isinstance(value, float):
        return 1.5
    if isinstance(value, str):
        if value.startswith("http://") or value.startswith("https://"):
            return "https://example.invalid/sanitized-link"
        return "SANITIZED_STRING"
    return "SANITIZED_UNKNOWN_TYPE"


def write_sanitized_fixture(name: str, real_response: dict[str, Any]) -> Path:
    """Write a sanitized structural fixture derived from a real live
    response: real top-level key names and structure, every leaf value
    replaced with a synthetic placeholder. Never writes the raw response
    itself. Preserves whatever Gondola's actual top-level keys are, rather
    than guessing a key name like "results" -- that guess is exactly what
    caused the G3.2 hotel-search gap this fixture-writing step exists to
    close."""
    sanitized = sanitize_structural_fixture(real_response)
    envelope: dict[str, Any] = {
        "_fixture_provenance": (
            f"schema observed from live Gondola MCP on "
            f"{datetime.now(UTC).date().isoformat()}; content sanitized and synthetic"
        ),
        "_fixture_meta": {"status": "estimated", "source_method": "provider_mcp"},
    }
    if isinstance(sanitized, dict):
        envelope.update(sanitized)
    else:
        envelope["value"] = sanitized
    out_path = GONDOLA_FIXTURES_DIR / f"{name}.json"
    out_path.write_text(json.dumps(envelope, indent=2) + "\n")
    return out_path


def _find_result_list(result: dict[str, Any]) -> tuple[str | None, list[Any]]:
    """Finds the first top-level key whose value is a list, without
    assuming the key is named "results" or "hotels" -- Gondola's actual
    top-level key name is exactly what this function exists to discover,
    not assume."""
    for key, value in result.items():
        if isinstance(value, list):
            return key, value
    return None, []


def classify_tools(names: list[str]) -> dict[str, list[str]]:
    allowed = sorted(n for n in names if n in ALLOWED_TOOLS)
    denied = sorted(n for n in names if n in DENIED_TOOLS)
    unexpected = sorted(n for n in names if n not in ALLOWED_TOOLS and n not in DENIED_TOOLS)
    return {"allowlisted": allowed, "denylisted": denied, "unexpected_unknown": unexpected}


def extract_travel_gateway_error(exc: BaseException) -> TravelGatewayError | None:
    """anyio task groups (used internally by the mcp SDK's streamable HTTP
    transport) wrap raised exceptions in a BaseExceptionGroup, which a plain
    ``except TravelGatewayError`` clause does not match. Walks one level of
    grouping to find the underlying TravelGatewayError, if any."""
    if isinstance(exc, TravelGatewayError):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            found = extract_travel_gateway_error(sub)
            if found is not None:
                return found
    return None


def summarize_tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    """Structural-only summary of one discovered tool: name and the field
    names of its input schema. Never includes example values or free-text
    descriptions verbatim (descriptions could carry arbitrary provider text)."""
    schema = tool.get("inputSchema") or {}
    properties = schema.get("properties") or {}
    return {
        "name": tool.get("name"),
        "required_fields": sorted(schema.get("required") or []),
        "all_field_names": sorted(properties.keys()),
    }


async def run_anonymous_discovery() -> list[dict[str, Any]]:
    transport = LiveGondolaTransport(base_url=MCP_ENDPOINT, get_access_token=lambda: None)
    start = time.monotonic()
    tools = await transport.list_tools()
    elapsed = time.monotonic() - start

    names = [t.get("name", "") for t in tools]
    classification = classify_tools(names)
    high_risk_present = sorted(set(names) & HIGH_RISK_TOOL_NAMES)

    print("=== Anonymous tools/list ===")
    print(f"tool_count={len(names)} elapsed_s={elapsed:.2f}")
    print(f"allowlisted_present={classification['allowlisted']}")
    print(f"denylisted_present={classification['denylisted']}")
    print(f"unexpected_unknown_tools={classification['unexpected_unknown']}")
    print(f"high_risk_tool_names_present={high_risk_present}")
    if high_risk_present:
        print(
            "NOTE: high-risk tool names are present in discovery but remain denied "
            "regardless of discovery -- tool availability is never authorization."
        )

    for tool_name in ("search_hotels", "search_flights"):
        match = next((t for t in tools if t.get("name") == tool_name), None)
        if match is not None:
            print(f"schema[{tool_name}]={summarize_tool_schema(match)}")

    return tools


def _hotel_search_dates() -> tuple[str, str]:
    check_in = datetime.now(UTC).date() + timedelta(days=75)
    check_out = check_in + timedelta(days=3)
    return check_in.isoformat(), check_out.isoformat()


async def run_anonymous_hotel_search() -> None:
    transport = LiveGondolaTransport(base_url=MCP_ENDPOINT, get_access_token=lambda: None)
    check_in, check_out = _hotel_search_dates()
    arguments = {
        "city": "Singapore",
        "check_in": check_in,
        "check_out": check_out,
        "adults": 1,
        "rooms": 1,
    }
    print("=== Anonymous search_hotels ===")
    print(f"request_shape=city,check_in,check_out,adults,rooms check_in={check_in}")
    start = time.monotonic()
    try:
        result = await transport.call_tool("search_hotels", arguments)
    except BaseException as exc:  # noqa: BLE001 - task-group-wrapped errors need broad catch
        gateway_error = extract_travel_gateway_error(exc)
        if gateway_error is None:
            raise
        elapsed = time.monotonic() - start
        print(f"status=error elapsed_s={elapsed:.2f} error_code={gateway_error.code}")
        print(f"error_message={gateway_error.message}")
        return
    elapsed = time.monotonic() - start

    top_level_keys = sorted(result.keys())
    list_key, results = _find_result_list(result)
    result_count = len(results)
    first = results[0] if results and isinstance(results[0], dict) else {}
    first_keys = sorted(first.keys())

    print(f"status=success elapsed_s={elapsed:.2f}")
    print(f"top_level_keys={top_level_keys}")
    print(f"result_list_key={list_key!r}")
    print(f"result_count={result_count}")
    print(f"first_result_field_names={first_keys}")
    has_price = any(k in first_keys for k in ("cash_rate_minor", "price", "rate", "total"))
    has_currency = any(k in first_keys for k in ("cash_currency", "currency"))
    has_link = any("link" in k.lower() or "url" in k.lower() for k in first_keys)
    print(f"price_field_present={has_price} currency_field_present={has_currency}")
    print(f"booking_or_verification_link_present={has_link}")

    fixture_path = write_sanitized_fixture("search_hotels_live_g321", result)
    print(f"sanitized_fixture_written={fixture_path.name}")


async def run_authenticated_discovery(access_token: str) -> list[dict[str, Any]]:
    transport = LiveGondolaTransport(base_url=MCP_ENDPOINT, get_access_token=lambda: access_token)
    start = time.monotonic()
    tools = await transport.list_tools()
    elapsed = time.monotonic() - start

    names = [t.get("name", "") for t in tools]
    classification = classify_tools(names)
    high_risk_present = sorted(set(names) & HIGH_RISK_TOOL_NAMES)

    print("=== Authenticated tools/list ===")
    print(f"tool_count={len(names)} elapsed_s={elapsed:.2f}")
    print(f"allowlisted_present={classification['allowlisted']}")
    print(f"denylisted_present={classification['denylisted']}")
    print(f"unexpected_unknown_tools={classification['unexpected_unknown']}")
    print(f"high_risk_tool_names_present={high_risk_present}")
    print(f"search_flights_now_available={'search_flights' in names}")

    match = next((t for t in tools if t.get("name") == "search_flights"), None)
    if match is not None:
        print(f"schema[search_flights]={summarize_tool_schema(match)}")

    return tools


def _flight_search_date() -> str:
    return (datetime.now(UTC).date() + timedelta(days=90)).isoformat()


async def run_authenticated_flight_search(access_token: str) -> None:
    transport = LiveGondolaTransport(base_url=MCP_ENDPOINT, get_access_token=lambda: access_token)
    depart_date = _flight_search_date()
    arguments = {
        "origin": "DEL",
        "destination": "SIN",
        "depart_date": depart_date,
        "adults": 1,
        "cabin": "economy",
        "currency": "INR",
    }
    print("=== Authenticated search_flights (DEL -> SIN) ===")
    print(
        "request_shape=origin,destination,depart_date,adults,cabin,currency "
        f"depart_date={depart_date}"
    )
    start = time.monotonic()
    try:
        result = await transport.call_tool("search_flights", arguments)
    except BaseException as exc:  # noqa: BLE001 - task-group-wrapped errors need broad catch
        gateway_error = extract_travel_gateway_error(exc)
        if gateway_error is None:
            raise
        elapsed = time.monotonic() - start
        print(f"status=error elapsed_s={elapsed:.2f} error_code={gateway_error.code}")
        print(f"error_message={gateway_error.message}")
        print("del_sin_coverage=unknown (call failed; not evidence of no coverage)")
        return
    elapsed = time.monotonic() - start

    top_level_keys = sorted(result.keys())
    list_key, results = _find_result_list(result)
    result_count = len(results)
    first = results[0] if results and isinstance(results[0], dict) else {}
    first_keys = sorted(first.keys())
    segments = first.get("segments")
    segment_count = len(segments) if isinstance(segments, list) else 0

    print(f"status=success elapsed_s={elapsed:.2f}")
    print(f"top_level_keys={top_level_keys}")
    print(f"result_list_key={list_key!r}")
    print(f"result_count={result_count}")
    print(f"first_result_field_names={first_keys}")
    print(f"segment_count={segment_count}")
    has_price = any(k in first_keys for k in ("total_price_minor", "price", "total"))
    has_currency = "currency" in first_keys
    print(f"price_field_present={has_price} currency_field_present={has_currency}")
    fixture_path = write_sanitized_fixture("search_flights_live_g321", result)
    print(f"sanitized_fixture_written={fixture_path.name}")
    if result_count == 0:
        print(
            "del_sin_coverage=empty_result (truthful evidence of no coverage found; "
            "NOT a failed call)"
        )
    else:
        print("del_sin_coverage=results_returned")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge", action="store_true", default=False)
    parser.add_argument(
        "phase",
        choices=["anon-discover", "anon-hotel-search", "auth-discover", "auth-flight-search"],
    )
    args = parser.parse_args()

    require_gates(args.acknowledge)

    budget = GondolaCallBudget(BUDGET_DB_PATH)

    if args.phase in ("anon-discover", "anon-hotel-search"):
        if not budget.reserve_call("g3.2-anonymous"):
            print("SAFETY VIOLATION: anonymous acceptance call budget exhausted", file=sys.stderr)
            return 1
        if args.phase == "anon-discover":
            asyncio.run(run_anonymous_discovery())
        else:
            asyncio.run(run_anonymous_hotel_search())
        return 0

    if not budget.reserve_call("g3.2-authenticated"):
        print("SAFETY VIOLATION: authenticated acceptance call budget exhausted", file=sys.stderr)
        return 1

    tokens = KeychainTokenStore().load()
    if tokens is None:
        print(
            "Refusing to run: no Gondola OAuth tokens found. Run "
            "gateway/travel/adapters/gondola/scripts/bootstrap_oauth.py first.",
            file=sys.stderr,
        )
        return 1
    if tokens.scope != REQUIRED_SCOPE:
        print(
            f"SAFETY VIOLATION: stored token scope {tokens.scope!r} is not exactly "
            f"{REQUIRED_SCOPE!r}",
            file=sys.stderr,
        )
        return 1
    if tokens.expires_at <= datetime.now(UTC):
        print(
            "Refusing to run: stored Gondola token is expired. Re-run bootstrap_oauth.py "
            "(this script does not perform token refresh).",
            file=sys.stderr,
        )
        return 1

    if args.phase == "auth-discover":
        asyncio.run(run_authenticated_discovery(tokens.access_token))
    else:
        asyncio.run(run_authenticated_flight_search(tokens.access_token))
    return 0


if __name__ == "__main__":
    sys.exit(main())
