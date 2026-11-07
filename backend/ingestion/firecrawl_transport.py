"""Narrow, injected transport for Firecrawl's documented v2 scrape endpoint.

This module deliberately does not read environment variables or create a client at
import time.  Constructing it is not live enablement; callers must supply a key and
set ``enabled=True`` after the surrounding acquisition control has authorized a
specific request.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from ingestion.contracts import FetchFailureKind

FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v2/scrape"
DEFAULT_MAX_AGE_MS = 172_800_000
_MIN_PROVIDER_TIMEOUT_SECONDS = 1
_MAX_PROVIDER_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class FirecrawlScrapeRequest:
    """The non-agent, HTML-only subset of Firecrawl's scrape request."""

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
            "formats": list(self.formats),
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

    def __init__(self, *, api_key: str, enabled: bool = False, client: Any | None = None) -> None:
        if not api_key:
            raise ValueError("Firecrawl API key is required")
        self._api_key = api_key
        self.enabled = enabled
        self._client = client

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
