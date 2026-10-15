"""ONE anonymous, read-only Open-Meteo MCP forecast probe (G4) — human-supervised.

This script makes exactly one tool call (``openmeteo_get_forecast``) through the
production ``StdioWeatherTransport`` against the *pinned, audited* upstream
server, for a bounded Singapore request inside the provider's genuine forecast
horizon. It needs no account, credential, payment method or paid tier.

Guard rails:
* refuses to run without an explicit acknowledgement env var;
* refuses if the output fixture already exists (a probe is a one-off);
* refuses a node runtime below the server's required major version;
* makes a single transport call with no retry path (it does not use the
  adapter, whose bounded retry could add a second call);
* captures only a *sanitized, whitelisted, numeric* fixture and only if the
  real payload passes the project's strict normalizer; on failure it prints a
  structural summary (key names / types / unit strings) so the mismatch can be
  fixed offline — never raw provider text.

Usage (see reports/g4_open_meteo_weather_context.md):
    TRIPWISE_OPEN_METEO_PROBE_ACK=ONE_ANONYMOUS_READ_ONLY_CALL \\
      python -m gateway.weather.scripts.probe_live \\
      --install-root /abs/path/to/provisioned/tree --node /abs/path/to/node24
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gateway.weather.contracts import CurrentAndForecastRequest, WeatherLocation
from gateway.weather.errors import WeatherGatewayError
from gateway.weather.normalize import normalize_tool_result
from gateway.weather.sanitize import sanitize_provider_text
from gateway.weather.stdio_transport import StdioWeatherTransport, pinned_upstream_launch
from gateway.weather.tool_policy import build_tool_call
from gateway.weather.upstream_pin import REQUIRED_NODE_MAJOR, UPSTREAM_COMMIT, UPSTREAM_VERSION

ACK_ENV = "TRIPWISE_OPEN_METEO_PROBE_ACK"
ACK_VALUE = "ONE_ANONYMOUS_READ_ONLY_CALL"
DEFAULT_OUT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "singapore_live_capture.forecast.json"
)
# Singapore, 3 forecast days (+ current conditions): far inside the 16-day horizon.
PROBE_REQUEST = CurrentAndForecastRequest(
    location=WeatherLocation(latitude=1.3521, longitude=103.8198, label="Singapore"),
    forecast_days=3,
    include_current=True,
)
_WHITELIST = (
    "latitude",
    "longitude",
    "elevation",
    "timezone",
    "utc_offset_seconds",
    "current",
    "current_units",
    "daily",
    "daily_units",
)


def node_major(node: Path) -> int:
    out = subprocess.run([str(node), "--version"], capture_output=True, text=True, timeout=10)
    return int(out.stdout.strip().lstrip("v").split(".")[0])


def structural_summary(value: Any) -> Any:
    """Key names, value types and (short, sanitized) strings — never raw prose."""
    if isinstance(value, dict):
        return {k: structural_summary(v) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        if not value:
            return []
        return {"__len__": len(value), "__first__": structural_summary(value[0])}
    if isinstance(value, str):
        return f"str:{(sanitize_provider_text(value) or '')[:24]}"
    return type(value).__name__


def sanitized_capture(payload: dict[str, Any], captured_at: datetime) -> dict[str, Any]:
    kept = {k: payload[k] for k in _WHITELIST if k in payload}
    return {
        "_fixture_meta": {
            "origin": "sanitized_capture",
            "description": (
                "Sanitized capture of one real response from the pinned upstream "
                f"open-meteo-mcp-server@{UPSTREAM_VERSION}. Numeric weather data only."
            ),
            "captured_at": captured_at.isoformat(),
            "upstream_version": UPSTREAM_VERSION,
            "upstream_commit": UPSTREAM_COMMIT,
            "sanitization": (
                "whitelisted keys only; provider free text (notice, models) dropped; "
                "all values re-validated by the strict normalizer before saving"
            ),
            "attribution": "Weather data by Open-Meteo.com (CC BY 4.0) — https://open-meteo.com/",
        },
        "tool": build_tool_call(PROBE_REQUEST)[0],
        "payload": kept,
    }


async def run(install_root: Path, node: Path, out: Path) -> int:
    launch = pinned_upstream_launch(install_root, node)
    transport = StdioWeatherTransport(launch, total_timeout_s=40)
    tool, arguments = build_tool_call(PROBE_REQUEST)
    now = datetime.now(UTC)
    started = time.monotonic()
    try:
        result = await transport.call_tool(tool, arguments)  # the ONE call
    except WeatherGatewayError as exc:
        print(json.dumps({"probe": "failed_before_data", "code": exc.code, "message": exc.message}))
        return 2
    elapsed = round(time.monotonic() - started, 2)

    report: dict[str, Any] = {
        "probe": "ran",
        "tool": tool,
        "elapsed_s": elapsed,
        "origin": result.origin,
        "payload_bytes": len(json.dumps(result.payload).encode("utf-8")),
        "retrieved_at": now.isoformat(),
    }
    try:
        evidence = normalize_tool_result(PROBE_REQUEST, result, now=now)
    except WeatherGatewayError as exc:
        report |= {
            "normalization": "rejected",
            "code": exc.code,
            "reason": exc.message,
            "shape": structural_summary(result.payload),
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 3

    report |= {
        "normalization": "accepted",
        "evidence": [
            {
                "kind": e.kind,
                "origin": e.meta.origin,
                "confidence": e.meta.confidence,
                "needs_verification": e.meta.needs_verification,
                "valid_from": e.meta.valid_from.isoformat(),
                "valid_to": e.meta.valid_to.isoformat(),
            }
            for e in evidence
        ],
    }
    capture = sanitized_capture(result.payload, now)
    out.write_text(json.dumps(capture, indent=2, ensure_ascii=False) + "\n")
    report["fixture_written"] = str(out)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="One anonymous read-only Open-Meteo MCP probe")
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if os.environ.get(ACK_ENV) != ACK_VALUE:
        print(f"refusing: set {ACK_ENV}={ACK_VALUE} to acknowledge exactly one anonymous call")
        return 64
    if args.out.exists():
        print("refusing: the capture fixture already exists — a probe is a one-off")
        return 65
    if node_major(args.node) < REQUIRED_NODE_MAJOR:
        print(f"refusing: node >= {REQUIRED_NODE_MAJOR} is required by the pinned server")
        return 66
    return asyncio.run(run(args.install_root, args.node, args.out))


if __name__ == "__main__":
    sys.exit(main())
