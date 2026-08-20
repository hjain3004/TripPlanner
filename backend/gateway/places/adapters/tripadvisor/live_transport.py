from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol

from gateway.places.adapters.tripadvisor.contracts import (
    TripadvisorLocation,
    TripadvisorSearchResponse,
)
from gateway.places.registry import PlaceGatewayError

# Verified static allowlist of permissible Tripadvisor tools
ALLOWLISTED_TOOLS = frozenset(
    [
        "search_locations",
        "get_location_details",
        "get_catalog_location",
    ]
)

MAX_RESPONSE_BYTES = 512 * 1024  # 512 KB payload ceiling
MAX_RESULTS_LIMIT = 50


def redact_secret(text: str) -> str:
    """Scrub potential API keys and secrets from error messages and logs."""
    if not text:
        return ""
    # Redact explicit env key if present
    env_key = os.environ.get("TRIPWISE_TRIPADVISOR_API_KEY", "")
    redacted = text
    if env_key and len(env_key) >= 6:
        redacted = redacted.replace(env_key, "[REDACTED_API_KEY]")
    # Redact common key/token patterns
    redacted = re.sub(
        r"(?i)(api[_-]?key\s*[:=]\s*['\"]?)[a-zA-Z0-9_-]{16,}(['\"]?)",
        r"\1[REDACTED_KEY]\2",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(bearer\s+)[a-zA-Z0-9_.\-]{16,}",
        r"\1[REDACTED_TOKEN]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(authorization\s*[:=]\s*['\"]?)[a-zA-Z0-9_.\-\s]{16,}(['\"]?)",
        r"\1[REDACTED_AUTH]\2",
        redacted,
    )
    return redacted


class TripadvisorClientProtocol(Protocol):
    """Protocol for injected low-level HTTP/MCP client boundary."""

    def execute_tool(
        self, tool_name: str, params: dict[str, Any], timeout_seconds: float
    ) -> bytes | str: ...


class LiveTripadvisorMcpTransport:
    """Live Tripadvisor MCP transport with complete security envelope.

    Invariants:
    - Static tool allowlist
    - Disabled by default (fails closed with LIVE-SCHEMA-VALIDATION-PENDING)
    - Secret redaction
    - Response size ceiling (512 KB)
    - Result count bounds (max 50)
    - Timeout controls
    - Never leaks raw headers or response bodies in user errors
    """

    def __init__(
        self,
        api_key: str | None = None,
        kill_switch: bool = False,
        timeout_seconds: float = 5.0,
        client: TripadvisorClientProtocol | None = None,
        activation_override_for_test: bool = False,
    ) -> None:
        self._api_key = api_key or os.environ.get("TRIPWISE_TRIPADVISOR_API_KEY")
        self._kill_switch = kill_switch or (
            os.environ.get("TRIPWISE_TRIPADVISOR_KILL_SWITCH", "0") == "1"
        )
        self.timeout_seconds = timeout_seconds
        self._client = client
        self._activation_override_for_test = activation_override_for_test

    @property
    def is_live(self) -> bool:
        return True

    def _execute_tool(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        # 1. Kill-switch check
        if self._kill_switch:
            msg = "Tripadvisor live transport blocked by operational kill-switch"
            raise PlaceGatewayError("permission_denied", msg)

        # 2. Activation check (fails closed in Phase I8A offline mode)
        if not self._activation_override_for_test:
            msg = (
                "LIVE-SCHEMA-VALIDATION-PENDING: Tripadvisor live account/billing activation is "
                "incomplete. Live calls are disabled."
            )
            raise PlaceGatewayError("permission_denied", msg)

        # 3. Tool allowlist check
        if tool_name not in ALLOWLISTED_TOOLS:
            raise PlaceGatewayError(
                "permission_denied",
                f"Tool '{tool_name}' not in static allowlist {sorted(ALLOWLISTED_TOOLS)}",
            )

        # 4. Credential check
        if not self._api_key:
            raise PlaceGatewayError(
                "authentication_failed",
                "Tripadvisor live transport requires TRIPWISE_TRIPADVISOR_API_KEY credential",
            )

        # 5. Client dispatch
        if self._client is None:
            raise PlaceGatewayError(
                "provider_unavailable",
                "Live MCP transport client not initialized",
            )

        try:
            raw_data = self._client.execute_tool(
                tool_name=tool_name,
                params=params,
                timeout_seconds=self.timeout_seconds,
            )
            if isinstance(raw_data, str):
                raw_bytes = raw_data.encode("utf-8")
            else:
                raw_bytes = raw_data

            # Response size ceiling
            if len(raw_bytes) > MAX_RESPONSE_BYTES:
                msg = (
                    f"Response payload exceeds maximum allowed size "
                    f"({len(raw_bytes)} > {MAX_RESPONSE_BYTES} bytes)"
                )
                raise PlaceGatewayError("invalid_response", msg)

            try:
                parsed = json.loads(raw_bytes.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise PlaceGatewayError(
                    "invalid_response",
                    f"Malformed JSON payload from provider: {e}",
                ) from e

            if not isinstance(parsed, dict):
                raise PlaceGatewayError(
                    "invalid_response",
                    "Provider response payload is not a JSON object",
                )

            # Check RFC 7807 problem payloads
            if "status" in parsed and isinstance(parsed["status"], int):
                st = parsed["status"]
                raw_detail = str(parsed.get("detail", "Provider error"))
                clean_detail = redact_secret(raw_detail)
                if st == 401:
                    raise PlaceGatewayError(
                        "authentication_failed",
                        f"Unauthorized: {clean_detail}",
                    )
                if st == 403:
                    raise PlaceGatewayError("permission_denied", f"Forbidden: {clean_detail}")
                if st == 429:
                    raise PlaceGatewayError("rate_limited", f"Rate limited: {clean_detail}")
                if st >= 500:
                    raise PlaceGatewayError("provider_unavailable", f"Server error: {clean_detail}")

            return parsed

        except PlaceGatewayError:
            raise
        except TimeoutError as te:
            msg = redact_secret(f"Request to Tripadvisor timed out: {te}")
            raise PlaceGatewayError("timeout", msg) from None
        except Exception as ex:
            msg = redact_secret(f"Tripadvisor client execution failure: {ex}")
            raise PlaceGatewayError("provider_unavailable", msg) from None

    def search_locations(
        self,
        query: str,
        destination: str | None = None,
        category: str | None = None,
        limit: int = 10,
    ) -> TripadvisorSearchResponse:
        bounded_limit = min(max(1, limit), MAX_RESULTS_LIMIT)
        params: dict[str, Any] = {
            "query": query,
            "destination": destination,
            "category": category,
            "limit": bounded_limit,
        }
        data = self._execute_tool("search_locations", params)
        return TripadvisorSearchResponse.model_validate(data)

    def get_location_details(self, location_id: str | int) -> TripadvisorLocation:
        params: dict[str, Any] = {"location_id": str(location_id)}
        data = self._execute_tool("get_location_details", params)
        return TripadvisorLocation.model_validate(data)
