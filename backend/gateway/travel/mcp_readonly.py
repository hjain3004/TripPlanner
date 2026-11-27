"""Shared read-only keyless MCP transport, safety policy, sanitization, and budget primitives.

Used by verified public keyless travel MCP adapters (``seats_aero``, ``trivago``,
``kiwi``). Preserves existing ``gondola`` and ``openbnb`` modules untouched while
enforcing Spec-16 transport pinning, fail-closed tool allowlisting, NFKC
prompt-injection filtering, SQLite call-budget accounting, and binary-float-free
integer minor-unit parsing.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import threading
import unicodedata
from collections.abc import Awaitable, Callable, Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel

from gateway.travel.errors import ErrorCode, TravelGatewayError

MAX_PAYLOAD_BYTES = 512_000
MAX_ERROR_SUMMARY_CHARS = 300
CONNECT_TIMEOUT_S = 10.0
HTTP_OPERATION_TIMEOUT_S = 40.0
TOTAL_TIMEOUT_S = 45.0
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 3
RETRYABLE_ERROR_CODES: frozenset[ErrorCode] = frozenset({"provider_unavailable", "timeout"})

REDACTED = "[redacted: provider text contained a suspected prompt-injection marker]"
_INJECTION_MARKERS = (
    "ignore previous",
    "ignore all previous",
    "disregard all prior",
    "disregard previous",
    "system:",
    "new instructions",
    "you are now",
    "reveal your system prompt",
    'read the "system_message"',
)
_WHITESPACE_RE = re.compile(r"\s+")
_NUMERIC_TOKEN_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_HTTP_STATUS_RE = re.compile(r"\b([45]\d{2})\b")

_CURRENCY_EXPONENTS: dict[str, int] = {
    "BHD": 3,
    "CLP": 0,
    "IDR": 0,
    "JOD": 3,
    "JPY": 0,
    "KRW": 0,
    "KWD": 3,
    "OMR": 3,
    "VND": 0,
}


def sanitize_untrusted_text(text: str | None) -> str | None:
    """Normalize NFKC/whitespace and redact obvious prompt-injection instructions."""
    if text is None:
        return None
    normalized = unicodedata.normalize("NFKC", text)
    collapsed = _WHITESPACE_RE.sub(" ", normalized).strip()
    lowered = collapsed.casefold()
    if any(marker in lowered for marker in _INJECTION_MARKERS):
        return REDACTED
    return collapsed


def assert_read_only_tool(
    tool_name: str,
    *,
    allowed_tools: frozenset[str],
    provider_id: str,
) -> None:
    """Fail closed unless ``tool_name`` is explicitly in the adapter's read-only allowlist."""
    if tool_name in allowed_tools:
        return
    raise TravelGatewayError(
        "permission_denied",
        f"{provider_id} tool '{tool_name}' is not in the reviewed read-only allowlist",
    )


def assert_allowlisted_endpoint(
    base_url: str,
    *,
    allowed_hosts: frozenset[str],
    allowed_paths: frozenset[str],
    provider_id: str,
) -> str:
    """Enforce exact HTTPS host and path allowlisting with no query/fragment/credentials."""
    parsed = urlparse(base_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in allowed_paths
        or parsed.query
        or parsed.fragment
    ):
        raise TravelGatewayError(
            "permission_denied",
            f"{provider_id} live transport refuses non-allowlisted endpoint: {base_url!r}",
        )
    return base_url


def validate_deep_link(url: str | None, *, allowed_host_suffixes: tuple[str, ...]) -> str | None:
    """Validate an untrusted deep link as HTTPS without userinfo or control chars."""
    if not url or not isinstance(url, str):
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
        return None
    cleaned = url.strip()
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    if not any(host == sfx or host.endswith(f".{sfx}") for sfx in allowed_host_suffixes):
        return None
    return cleaned


def currency_exponent(currency: str) -> int:
    return _CURRENCY_EXPONENTS.get(currency.strip().upper(), 2)


def parse_decimal_to_minor(value: int | Decimal | str, currency: str) -> int:
    """Convert a decimal major-unit value (never binary float) into integer minor units."""
    if isinstance(value, bool):
        raise TravelGatewayError("invalid_response", "Boolean prohibited for monetary conversion")
    if isinstance(value, float):
        raise TravelGatewayError(
            "invalid_response",
            "Binary float prohibited for monetary conversion; expected Decimal/str/int",
        )
    if isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, Decimal):
        dec = value
    elif isinstance(value, str):
        match = _NUMERIC_TOKEN_RE.search(value.replace("\u00a0", " "))
        if match is None:
            raise TravelGatewayError(
                "invalid_response", f"Could not parse monetary amount {value!r}"
            )
        token = match.group(0).replace(",", "")
        try:
            dec = Decimal(token)
        except InvalidOperation as exc:
            raise TravelGatewayError(
                "invalid_response", f"Invalid decimal monetary token {token!r}: {exc}"
            ) from exc
    else:
        raise TravelGatewayError(
            "invalid_response", f"Unsupported money type {type(value).__name__}"
        )

    if not dec.is_finite() or dec < 0:
        raise TravelGatewayError("invalid_response", f"Negative or non-finite money value: {dec}")
    exp = currency_exponent(currency)
    scale = Decimal(10) ** exp
    return int((dec * scale).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class McpCallBudget:
    """Persistent atomic SQLite per-plan call ledger shared across keyless MCP providers."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        provider_id: str,
        calls_per_plan: int = 2,
        busy_timeout_s: float = 5.0,
    ) -> None:
        self._lock = threading.Lock()
        self._provider_id = provider_id
        self._calls_per_plan = calls_per_plan
        self._db_path = ":memory:" if db_path is None else str(db_path)
        self._busy_timeout_s = busy_timeout_s
        self._mem_conn: sqlite3.Connection | None = None
        if self._db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        if self._mem_conn is not None:
            return self._mem_conn
        return sqlite3.connect(self._db_path, timeout=self._busy_timeout_s, check_same_thread=False)

    def _close(self, conn: sqlite3.Connection) -> None:
        if self._mem_conn is None:
            conn.close()

    def _init_db(self) -> None:
        with self._lock:
            conn = self._conn()
            try:
                with conn:
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS mcp_provider_call_counts ("
                        "provider_id TEXT NOT NULL, "
                        "plan_id TEXT NOT NULL, "
                        "calls_used INTEGER NOT NULL DEFAULT 0, "
                        "PRIMARY KEY (provider_id, plan_id))"
                    )
            finally:
                self._close(conn)

    def reserve_call(self, plan_id: str) -> bool:
        with self._lock:
            conn = self._conn()
            try:
                try:
                    with conn:
                        conn.execute("BEGIN IMMEDIATE")
                        cur = conn.execute(
                            "SELECT calls_used FROM mcp_provider_call_counts "
                            "WHERE provider_id = ? AND plan_id = ?",
                            (self._provider_id, plan_id),
                        )
                        row = cur.fetchone()
                        used = int(row[0]) if row else 0
                        if used >= self._calls_per_plan:
                            return False
                        conn.execute(
                            "INSERT INTO mcp_provider_call_counts "
                            "(provider_id, plan_id, calls_used) "
                            "VALUES (?, ?, 1) ON CONFLICT(provider_id, plan_id) "
                            "DO UPDATE SET calls_used = calls_used + 1",
                            (self._provider_id, plan_id),
                        )
                        return True
                except sqlite3.OperationalError as exc:
                    raise TravelGatewayError(
                        "provider_unavailable",
                        f"{self._provider_id} call ledger contention for {plan_id!r}: {exc}",
                    ) from exc
            finally:
                self._close(conn)

    def calls_used(self, plan_id: str) -> int:
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.execute(
                    "SELECT calls_used FROM mcp_provider_call_counts "
                    "WHERE provider_id = ? AND plan_id = ?",
                    (self._provider_id, plan_id),
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0
            finally:
                self._close(conn)


class McpCircuitBreaker:
    """Consecutive-failure circuit breaker; treats 429/rate_limited as a failure."""

    def __init__(self, *, failure_threshold: int = CIRCUIT_BREAKER_FAILURE_THRESHOLD) -> None:
        self._failure_threshold = failure_threshold
        self.consecutive_failures = 0
        self.is_open = False

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self._failure_threshold:
            self.is_open = True


class RawMcpToolResponse(BaseModel):
    """Sanitized text content blocks from an MCP tool invocation."""

    provider_id: str
    tool_name: str
    text_blocks: list[str]
    structured_content: dict[str, Any] | None = None


def extract_call_tool_text_blocks(
    result: Any,
    *,
    provider_id: str,
    tool_name: str,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> RawMcpToolResponse:
    """Unwrap an MCP CallToolResult into size-checked text blocks / structured JSON."""
    if bool(getattr(result, "is_error", getattr(result, "isError", False))):
        summary = "(no text content in error result)"
        for block in getattr(result, "content", None) or []:
            text = getattr(block, "text", None)
            if isinstance(text, str) and text.strip():
                summary = text.strip()[:MAX_ERROR_SUMMARY_CHARS]
                break
        raise TravelGatewayError(
            "invalid_response",
            f"{provider_id}.{tool_name} returned isError=true: {summary}",
        )

    structured = getattr(
        result,
        "structured_content",
        getattr(result, "structuredContent", None),
    )
    validated_structured: dict[str, Any] | None = None
    if structured is not None:
        try:
            payload_bytes = json.dumps(structured).encode("utf-8")
        except TypeError as exc:
            raise TravelGatewayError(
                "invalid_response",
                f"{provider_id}.{tool_name} structured_content is not JSON-serializable: {exc}",
            ) from exc
        if len(payload_bytes) > max_payload_bytes:
            raise TravelGatewayError(
                "invalid_response",
                f"{provider_id}.{tool_name} response exceeds {max_payload_bytes} byte bound",
            )
        loaded = json.loads(payload_bytes, parse_float=Decimal)
        if not isinstance(loaded, dict):
            raise TravelGatewayError(
                "invalid_response",
                f"{provider_id}.{tool_name} structured_content is not a JSON object",
            )
        validated_structured = loaded

    text_blocks: list[str] = []
    total_bytes = 0
    for block in getattr(result, "content", None) or []:
        block_type = getattr(block, "type", "text")
        if isinstance(block, Mapping):
            block_type = block.get("type", "text")
            text = block.get("text")
        else:
            text = getattr(block, "text", None)
        if block_type != "text" or not isinstance(text, str):
            continue
        encoded = text.encode("utf-8")
        total_bytes += len(encoded)
        if total_bytes > max_payload_bytes:
            raise TravelGatewayError(
                "invalid_response",
                f"{provider_id}.{tool_name} text content exceeds {max_payload_bytes} byte bound",
            )
        text_blocks.append(text)

    if not text_blocks and validated_structured is None:
        raise TravelGatewayError(
            "invalid_response",
            f"{provider_id}.{tool_name} returned no text or structured content",
        )
    return RawMcpToolResponse(
        provider_id=provider_id,
        tool_name=tool_name,
        text_blocks=text_blocks,
        structured_content=validated_structured,
    )


class KeylessMcpTransport:
    """Fail-closed anonymous Streamable HTTP MCP transport pinned to allowlisted hosts."""

    def __init__(
        self,
        *,
        provider_id: str,
        base_url: str,
        allowed_hosts: frozenset[str],
        allowed_paths: frozenset[str],
        allowed_tools: frozenset[str],
        total_timeout_s: float = TOTAL_TIMEOUT_S,
        max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    ) -> None:
        self._provider_id = provider_id
        self._base_url = assert_allowlisted_endpoint(
            base_url,
            allowed_hosts=allowed_hosts,
            allowed_paths=allowed_paths,
            provider_id=provider_id,
        )
        self._allowed_tools = allowed_tools
        self._total_timeout_s = total_timeout_s
        self._max_payload_bytes = max_payload_bytes

    def validate_call(self, tool_name: str) -> None:
        assert_read_only_tool(
            tool_name, allowed_tools=self._allowed_tools, provider_id=self._provider_id
        )

    @staticmethod
    def _leaf_exceptions(exc: BaseException) -> list[BaseException]:
        if isinstance(exc, BaseExceptionGroup):
            leaves: list[BaseException] = []
            for child in exc.exceptions:
                leaves.extend(KeylessMcpTransport._leaf_exceptions(child))
            return leaves
        return [exc]

    def _map_http_status_code(
        self, code: int, tool_name: str, detail: str = ""
    ) -> TravelGatewayError:
        suffix = f": {detail}" if detail else ""
        if code == 401:
            return TravelGatewayError(
                "authentication_failed", f"{self._provider_id}.{tool_name} HTTP 401{suffix}"
            )
        if code == 403:
            return TravelGatewayError(
                "permission_denied", f"{self._provider_id}.{tool_name} HTTP 403{suffix}"
            )
        if code == 429:
            return TravelGatewayError(
                "rate_limited", f"{self._provider_id}.{tool_name} rate limited (HTTP 429){suffix}"
            )
        if code >= 500:
            return TravelGatewayError(
                "provider_unavailable",
                f"{self._provider_id}.{tool_name} upstream HTTP {code}{suffix}",
            )
        return TravelGatewayError(
            "invalid_response", f"{self._provider_id}.{tool_name} rejected (HTTP {code}){suffix}"
        )

    def _map_exception(self, exc: BaseException, tool_name: str) -> TravelGatewayError:
        leaves = self._leaf_exceptions(exc)
        for leaf in leaves:
            if isinstance(leaf, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise leaf
        for leaf in leaves:
            if isinstance(leaf, TravelGatewayError):
                return leaf
            if isinstance(leaf, (TimeoutError, asyncio.TimeoutError)):
                return TravelGatewayError(
                    "timeout",
                    f"{self._provider_id}.{tool_name} exceeded "
                    f"{self._total_timeout_s:.0f}s timeout",
                )
            try:
                from mcp.shared.exceptions import MCPError

                if isinstance(leaf, MCPError):
                    msg = str(leaf)
                    lowered = msg.casefold()
                    status_match = _HTTP_STATUS_RE.search(msg)
                    if status_match is not None:
                        return self._map_http_status_code(
                            int(status_match.group(1)), tool_name, msg[:200]
                        )
                    if "redirect" in lowered or "forbidden" in lowered:
                        return TravelGatewayError(
                            "permission_denied", f"{self._provider_id}.{tool_name} {msg[:200]}"
                        )
                    if "unauthorized" in lowered:
                        return TravelGatewayError(
                            "authentication_failed", f"{self._provider_id}.{tool_name} {msg[:200]}"
                        )
                    if "rate limit" in lowered or "too many requests" in lowered:
                        return TravelGatewayError(
                            "rate_limited", f"{self._provider_id}.{tool_name} {msg[:200]}"
                        )
                    return TravelGatewayError(
                        "invalid_response",
                        f"{self._provider_id}.{tool_name} MCP error ({leaf.code}): {msg[:200]}",
                    )
            except ImportError:  # pragma: no cover
                pass
            try:
                import httpx2

                if isinstance(leaf, httpx2.TimeoutException):
                    return TravelGatewayError(
                        "timeout",
                        f"{self._provider_id}.{tool_name} HTTP timeout",
                    )
                if isinstance(leaf, httpx2.HTTPStatusError):
                    return self._map_http_status_code(leaf.response.status_code, tool_name)
                if isinstance(leaf, httpx2.HTTPError):
                    return TravelGatewayError(
                        "provider_unavailable",
                        f"{self._provider_id}.{tool_name} transport error: {type(leaf).__name__}",
                    )
            except ImportError:  # pragma: no cover
                pass
        return TravelGatewayError(
            "provider_unavailable",
            f"{self._provider_id}.{tool_name} failed: {type(exc).__name__}",
        )

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> RawMcpToolResponse:
        self.validate_call(tool_name)
        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        http_client = httpx2.AsyncClient(
            timeout=httpx2.Timeout(HTTP_OPERATION_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
            follow_redirects=False,
        )
        try:
            async with asyncio.timeout(self._total_timeout_s):
                async with streamable_http_client(
                    self._base_url, http_client=http_client, terminate_on_close=False
                ) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        result = await session.call_tool(tool_name, arguments)
                        return extract_call_tool_text_blocks(
                            result,
                            provider_id=self._provider_id,
                            tool_name=tool_name,
                            max_payload_bytes=self._max_payload_bytes,
                        )
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            raise self._map_exception(exc, tool_name) from exc
        finally:
            await http_client.aclose()


class FixtureMcpTransport:
    """Offline recorded-fixture replay transport enforcing tool allowlists identically."""

    def __init__(
        self,
        *,
        provider_id: str,
        allowed_tools: frozenset[str],
        fixture_paths: Mapping[str, Path],
        max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    ) -> None:
        self._provider_id = provider_id
        self._allowed_tools = allowed_tools
        self._fixture_paths = dict(fixture_paths)
        self._max_payload_bytes = max_payload_bytes

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> RawMcpToolResponse:
        assert_read_only_tool(
            tool_name, allowed_tools=self._allowed_tools, provider_id=self._provider_id
        )
        path = self._fixture_paths.get(tool_name)
        if path is None or not path.exists():
            raise TravelGatewayError(
                "provider_unavailable",
                f"No recorded fixture for {self._provider_id}.{tool_name}",
            )
        raw_bytes = path.read_bytes()
        if len(raw_bytes) > self._max_payload_bytes:
            raise TravelGatewayError(
                "invalid_response",
                f"Fixture for {self._provider_id}.{tool_name} exceeds {self._max_payload_bytes} B",
            )
        data = json.loads(raw_bytes.decode("utf-8"), parse_float=Decimal)
        content_blocks = data.get("content") or []
        text_blocks: list[str] = []
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                txt = block.get("text")
                if isinstance(txt, str):
                    text_blocks.append(txt)
        structured = data.get("structured_content") or data.get("structuredContent")
        if not text_blocks and not isinstance(structured, dict):
            raise TravelGatewayError(
                "invalid_response",
                f"Fixture {path.name} has neither text content nor structured_content",
            )
        return RawMcpToolResponse(
            provider_id=self._provider_id,
            tool_name=tool_name,
            text_blocks=text_blocks,
            structured_content=structured if isinstance(structured, dict) else None,
        )


async def call_with_guard_and_retry(
    *,
    provider_id: str,
    live_enabled: bool,
    circuit_breaker: McpCircuitBreaker,
    budget: McpCallBudget,
    plan_id: str,
    action: Callable[[], Awaitable[list[Any]]],
) -> list[Any]:
    """Execute one guarded MCP fetch with kill switch, circuit breaker, budget, and 1 retry."""
    if not live_enabled:
        raise TravelGatewayError(
            "provider_unavailable", f"{provider_id} adapter is disabled (kill switch off)"
        )
    if circuit_breaker.is_open:
        raise TravelGatewayError(
            "provider_unavailable", f"{provider_id} circuit breaker is open; falling back"
        )
    if not budget.reserve_call(plan_id):
        raise TravelGatewayError(
            "budget_exhausted", f"{provider_id} per-plan call budget exhausted"
        )
    try:
        try:
            res = await action()
        except TravelGatewayError as exc:
            if exc.code not in RETRYABLE_ERROR_CODES:
                raise
            res = await action()
    except Exception:
        circuit_breaker.record_failure()
        raise
    circuit_breaker.record_success()
    return res
