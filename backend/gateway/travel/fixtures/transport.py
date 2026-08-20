"""Recorded/local fixture replay harness — reusable seam for future (G3+)
live adapters.

Reads only committed sanitized local fixtures. Never opens a socket, never
reads credentials, never uses the wall clock for loading (the injected
``now`` exists so a caller can thread a frozen clock into identity/freshness
code deterministically alongside the fixture read). A fixture that claims
``status="live"`` is rejected outright: fixture replay is never live
provider evidence, even if the JSON itself (accidentally or maliciously)
claims otherwise.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from gateway.travel.errors import ErrorCode, TravelGatewayError

_ERROR_FIXTURE_DEFAULT_CODE: dict[str, ErrorCode] = {
    "flight_rate_limited": "rate_limited",
    "flight_auth_failed": "authentication_failed",
    "flight_timeout": "timeout",
}


class FixtureTravelTransport:
    MAX_PAYLOAD_BYTES = 512_000

    def __init__(self, fixture_dir: Path, *, now: Callable[[], datetime]) -> None:
        self.fixture_dir = fixture_dir
        self.now = now

    def load(self, name: str) -> dict[str, Any]:
        path = self.fixture_dir / f"{name}.json"
        raw = path.read_bytes()
        if len(raw) > self.MAX_PAYLOAD_BYTES:
            raise TravelGatewayError("invalid_response", f"fixture {name} exceeds payload bound")
        try:
            envelope: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TravelGatewayError(
                "invalid_response", f"malformed fixture {name}: {exc}"
            ) from exc

        meta = envelope.get("_fixture_meta", {})
        if meta.get("status") == "live":
            raise TravelGatewayError(
                "invalid_response", f"fixture {name} illegally claims status=live"
            )

        if "error" in envelope:
            code = envelope["error"].get(
                "code", _ERROR_FIXTURE_DEFAULT_CODE.get(name, "invalid_response")
            )
            message = envelope["error"].get("message", f"fixture {name} simulates {code}")
            raise TravelGatewayError(code, message)

        return envelope
