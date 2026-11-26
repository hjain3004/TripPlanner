"""Narrow, injected transport for Firecrawl's documented v2 scrape endpoint.

This module deliberately does not read environment variables or create a client at
import time.  Constructing it is not live enablement; callers must supply a key and
set ``enabled=True`` after the surrounding acquisition control has authorized a
specific request.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from ingestion.artifacts import write_private_file
from ingestion.contracts import FetchFailureKind

FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v2/scrape"
DEFAULT_MAX_AGE_MS = 172_800_000
_MIN_PROVIDER_TIMEOUT_SECONDS = 1
_MAX_PROVIDER_TIMEOUT_SECONDS = 300


JSON_EXTRACTION_EXTRA_CREDITS = 4  # billing page: "JSON format (LLM extraction): +4 credits / page"
HTML_SCRAPE_CREDITS = 1


@dataclass(frozen=True)
class JsonExtraction:
    """Firecrawl-hosted structured extraction requested alongside the retained HTML.

    ``schema_json`` is canonical JSON text so the request stays hashable and its identity can be
    bound into the acquisition fingerprint. v2 embeds the schema in the format object:
    ``formats: [{"type": "json", "schema": {...}, "prompt": "..."}]``.
    """

    schema_json: str
    prompt: str

    def __post_init__(self) -> None:
        try:
            schema = json.loads(self.schema_json)
        except json.JSONDecodeError as error:
            raise ValueError("JSON extraction schema must be valid JSON") from error
        if not isinstance(schema, dict) or not schema:
            raise ValueError("JSON extraction schema must be a non-empty object")
        if not self.prompt.strip():
            raise ValueError("JSON extraction prompt must not be blank")

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256(f"{self.schema_json}\n--\n{self.prompt}".encode())
        return digest.hexdigest()

    def wire_format(self) -> dict[str, object]:
        return {"type": "json", "schema": json.loads(self.schema_json), "prompt": self.prompt}


def canonical_schema_json(schema: Mapping[str, Any]) -> str:
    return json.dumps(schema, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class FirecrawlScrapeRequest:
    """The non-agent subset of Firecrawl's scrape request: raw HTML, optionally with JSON."""

    url: str
    timeout_seconds: float
    max_response_bytes: int
    formats: tuple[str, ...] = ("rawHtml",)
    only_main_content: bool = False
    only_clean_content: bool = False
    max_age_ms: int = DEFAULT_MAX_AGE_MS
    proxy: str = "basic"
    parsers: tuple[str, ...] = ()
    actions: tuple[object, ...] = ()
    json_extraction: JsonExtraction | None = None

    @property
    def estimated_credits(self) -> int:
        """The documented cost of this request: one page, plus 4 when JSON extraction is on."""
        extra = JSON_EXTRACTION_EXTRA_CREDITS if self.json_extraction is not None else 0
        return HTML_SCRAPE_CREDITS + extra

    def __post_init__(self) -> None:
        if self.formats != ("rawHtml",):
            raise ValueError("Firecrawl financial ingestion accepts only rawHtml")
        if self.proxy != "basic":
            raise ValueError("Firecrawl financial ingestion permits only the basic proxy")
        if self.parsers:
            raise ValueError("Firecrawl parsers must be explicitly disabled")
        if self.actions:
            raise ValueError("Firecrawl browser actions are not permitted")
        if not self.max_response_bytes > 0:
            raise ValueError("max_response_bytes must be positive")
        if (
            not _MIN_PROVIDER_TIMEOUT_SECONDS
            <= self.timeout_seconds
            <= _MAX_PROVIDER_TIMEOUT_SECONDS
        ):
            raise ValueError("timeout_seconds is outside Firecrawl's documented range")
        if self.max_age_ms < 0:
            raise ValueError("max_age_ms cannot be negative")

    def wire_payload(self) -> dict[str, object]:
        """Return the documented v2 JSON shape without unsupported features."""
        return {
            "url": self.url,
            "formats": [
                *self.formats,
                *([self.json_extraction.wire_format()] if self.json_extraction else []),
            ],
            "onlyMainContent": self.only_main_content,
            "onlyCleanContent": self.only_clean_content,
            "maxAge": self.max_age_ms,
            "timeout": int(self.timeout_seconds * 1000),
            "proxy": self.proxy,
            # An explicit empty list is Firecrawl's documented way to disable PDF/image parsing
            # (per-page charges); omitting it would leave both parsers on.
            "parsers": list(self.parsers),
            "storeInCache": True,
            "removeBase64Images": True,
        }


class FirecrawlTransport(Protocol):
    async def scrape(self, scrape_request: FirecrawlScrapeRequest) -> Mapping[str, Any]:
        """Dispatch exactly one scrape request; callers own all retry policy."""


class _ByteStream(Protocol):
    def aiter_bytes(self) -> AsyncIterator[bytes]: ...


class FirecrawlTransportError(RuntimeError):
    """A safe, classified provider-boundary error with no response body."""

    def __init__(self, kind: FetchFailureKind, diagnostic: str, *, retryable: bool = False) -> None:
        super().__init__(diagnostic)
        self.kind = kind
        self.diagnostic = diagnostic
        self.retryable = retryable


def _error_code(body: bytes) -> str | None:
    """The provider's short machine ``code`` only; never the message or any body text."""
    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    code = decoded.get("code") if isinstance(decoded, dict) else None
    return code if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_]{1,64}", code) else None


def _http_failure(status_code: int, code: str | None = None) -> FirecrawlTransportError:
    if code == "THIRD_PARTY_DATA_TERMS_REQUIRED":
        return FirecrawlTransportError(
            FetchFailureKind.POLICY_BLOCKED, "Firecrawl requires third-party data terms acceptance"
        )
    if status_code in {401, 403}:
        return FirecrawlTransportError(
            FetchFailureKind.AUTHENTICATION_REQUIRED, "Firecrawl authentication was refused"
        )
    if status_code == 402:
        return FirecrawlTransportError(
            FetchFailureKind.BUDGET_EXHAUSTED, "Firecrawl credits are unavailable"
        )
    if status_code == 429:
        return FirecrawlTransportError(
            FetchFailureKind.RATE_LIMITED, "Firecrawl rate limit", retryable=True
        )
    if status_code in {408, 504}:
        return FirecrawlTransportError(
            FetchFailureKind.TIMEOUT, "Firecrawl request timed out", retryable=True
        )
    if 500 <= status_code:
        return FirecrawlTransportError(
            FetchFailureKind.UNEXPECTED_FAILURE,
            "Firecrawl service failure",
            retryable=True,
        )
    return FirecrawlTransportError(FetchFailureKind.INVALID_RESPONSE, "Firecrawl rejected request")


class FirecrawlHttpTransport:
    """HTTP implementation with a fixed endpoint and bounded streamed body.

    ``client`` is injectable for offline tests.  The application never obtains a
    key, enables this transport, or invokes it implicitly.
    """

    def __init__(
        self,
        *,
        api_key: str,
        enabled: bool = False,
        client: Any | None = None,
        retain_dir: Path | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Firecrawl API key is required")
        self._api_key = api_key
        self.enabled = enabled
        self._client = client
        # When set, every complete response body is written here, verbatim and before it is
        # parsed or analysed, together with the request that produced it (never the credential).
        self._retain_dir = retain_dir

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(enabled={self.enabled!r}, client={self._client is not None!r})"
        )

    async def scrape(self, scrape_request: FirecrawlScrapeRequest) -> Mapping[str, Any]:
        if not self.enabled:
            raise FirecrawlTransportError(
                FetchFailureKind.POLICY_BLOCKED, "Firecrawl transport is disabled"
            )
        try:
            import httpx
        except ImportError as error:  # pragma: no cover - production package has an explicit extra
            raise FirecrawlTransportError(
                FetchFailureKind.UNEXPECTED_FAILURE,
                "Firecrawl HTTP dependency is unavailable",
            ) from error

        owned_client = self._client is None
        client = self._client or httpx.AsyncClient(follow_redirects=False)
        try:
            try:
                async with client.stream(
                    "POST",
                    FIRECRAWL_SCRAPE_URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=scrape_request.wire_payload(),
                    timeout=httpx.Timeout(scrape_request.timeout_seconds),
                ) as response:
                    status_code = int(response.status_code)
                    body = await self._read_bounded(
                        cast(_ByteStream, response), scrape_request.max_response_bytes
                    )
            except httpx.TimeoutException as error:
                raise FirecrawlTransportError(
                    FetchFailureKind.TIMEOUT, "Firecrawl request timed out", retryable=True
                ) from error
            except httpx.HTTPError as error:
                raise FirecrawlTransportError(
                    FetchFailureKind.UNEXPECTED_FAILURE,
                    "Firecrawl transport failure",
                    retryable=True,
                ) from error
            self._retain(scrape_request, status_code, body)
            if status_code < 200 or status_code >= 300:
                raise _http_failure(status_code, _error_code(body))
            try:
                decoded = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise FirecrawlTransportError(
                    FetchFailureKind.INVALID_RESPONSE, "Firecrawl returned malformed JSON"
                ) from error
            if not isinstance(decoded, dict):
                raise FirecrawlTransportError(
                    FetchFailureKind.INVALID_RESPONSE, "Firecrawl returned a non-object response"
                )
            return cast(Mapping[str, Any], decoded)
        finally:
            if owned_client:
                await client.aclose()

    def _retain(
        self, scrape_request: FirecrawlScrapeRequest, status_code: int, body: bytes
    ) -> None:
        if self._retain_dir is None:
            return
        request_bytes = json.dumps(scrape_request.wire_payload()).encode()
        if self._api_key.encode() in body or self._api_key.encode() in request_bytes:
            raise FirecrawlTransportError(
                FetchFailureKind.INVALID_RESPONSE,
                "response or request contains the configured credential; retention refused",
            )
        self._retain_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(body).hexdigest()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        meta = {
            "retained_at": datetime.now(UTC).isoformat(),
            "http_status": status_code,
            "response_sha256": digest,
            "response_bytes": len(body),
            "endpoint": FIRECRAWL_SCRAPE_URL,
            "request": scrape_request.wire_payload(),
            "estimated_credits": scrape_request.estimated_credits,
        }
        for suffix, data in (
            (".response.json", body),
            (".request.json", json.dumps(meta).encode()),
        ):
            path = self._retain_dir / f"{stamp}-{digest[:12]}{suffix}"
            write_private_file(path, data)

    @staticmethod
    async def _read_bounded(response: _ByteStream, max_response_bytes: int) -> bytes:
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_response_bytes:
                raise FirecrawlTransportError(
                    FetchFailureKind.INVALID_RESPONSE, "Firecrawl response exceeds byte bound"
                )
            chunks.append(chunk)
        return b"".join(chunks)
