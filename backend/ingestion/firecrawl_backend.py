"""Firecrawl HTML acquisition through the existing ingestion fetch contract."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlsplit

from ingestion.acquisition import AcquisitionControl
from ingestion.artifacts import ContentAddressedStore
from ingestion.canonical import ContentLimitError, UnsupportedContentError, acanonicalize_content
from ingestion.contracts import (
    FetchFailure,
    FetchFailureKind,
    FetchRequest,
    FetchResult,
    SourcePolicyRecord,
)
from ingestion.firecrawl_transport import (
    DEFAULT_MAX_AGE_MS,
    FirecrawlHttpTransport,
    FirecrawlScrapeRequest,
    FirecrawlTransport,
    FirecrawlTransportError,
)
from ingestion.preflight import RobotsRules, SourcePreflight

_PROVIDER_ENVELOPE_ALLOWANCE = 65_536
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_PASSWORD_INPUT_RE = re.compile(r"<input\b[^>]*\btype\s*=\s*[\"']?password", re.IGNORECASE)
# Fingerprints of interstitial pages, not words that appear on ordinary issuer pages (a card
# page's navigation routinely contains "Login" and "Net Banking").
_CHALLENGE_TITLES = ("just a moment", "attention required", "access denied", "are you a robot")
_CHALLENGE_BODY_MARKERS = (
    "cf-chl-",
    "g-recaptcha",
    "h-captcha",
    "hcaptcha.com/1/api",
    "challenges.cloudflare.com",
    "_incapsula_",
    "px-captcha",
)
_LOGIN_URL_MARKERS = ("/login", "/signin", "/sign-in", "/log-in", "/sso/", "/authenticate")
_SMALL_PAGE_CHARS = 8_000


def _failure(
    request_id: str, kind: FetchFailureKind, diagnostic: str, *, retryable: bool = False
) -> FetchResult:
    return FetchResult(
        request_id=request_id,
        failure=FetchFailure(kind=kind, diagnostic=diagnostic[:1000], retryable=retryable),
    )


def _mapping(value: object) -> Mapping[str, Any] | None:
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else None


def _policy_hash(policy: SourcePolicyRecord) -> str:
    encoded = json.dumps(policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _claim_failure(state: str) -> tuple[FetchFailureKind, str]:
    if state == "blocked":
        return (
            FetchFailureKind.BUDGET_EXHAUSTED,
            "Firecrawl dispatch blocked by acquisition control",
        )
    if state == "pending":
        return FetchFailureKind.UNEXPECTED_FAILURE, "Firecrawl dispatch needs reconciliation"
    return FetchFailureKind.UNEXPECTED_FAILURE, "Firecrawl acquisition claim conflicts"


class FirecrawlBackend:
    """Disabled-by-default, HTML-only ``FetchBackend`` implementation.

    The backend accepts an injected transport and optional durable acquisition
    control.  It never reads credentials, constructs a live transport, retries,
    or turns a Firecrawl-rendered document into a claim about the issuer's raw
    HTTP response.
    """

    backend_name = "firecrawl"
    backend_version = "v2-scrape-html"

    def __init__(
        self,
        *,
        artifacts: ContentAddressedStore,
        policy: SourcePolicyRecord,
        transport: FirecrawlTransport,
        robots: RobotsRules | None = None,
        preflight: SourcePreflight | None = None,
        control: AcquisitionControl | None = None,
        enabled: bool = False,
        estimated_credits: int = 1,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if estimated_credits < 0:
            raise ValueError("estimated_credits cannot be negative")
        self.artifacts = artifacts
        self.policy = policy
        self.transport = transport
        self.robots = robots
        self.preflight = preflight or SourcePreflight()
        self.control = control
        self.enabled = enabled
        self.estimated_credits = estimated_credits
        self.now = now or (lambda: datetime.now(UTC))

    async def fetch(self, request: FetchRequest) -> FetchResult:
        if not self.enabled:
            return _failure(
                request.request_id, FetchFailureKind.POLICY_BLOCKED, "Firecrawl backend is disabled"
            )
        if request.evidence_kind != "official_page":
            return _failure(
                request.request_id,
                FetchFailureKind.INVALID_RESPONSE,
                "Firecrawl backend currently accepts approved HTML pages only",
            )
        decision = self.preflight.check(request, self.policy, robots=self.robots)
        if not decision.allowed:
            return _failure(
                request.request_id,
                decision.failure_kind or FetchFailureKind.POLICY_BLOCKED,
                decision.diagnostic or "Firecrawl preflight blocked",
            )
        if isinstance(self.transport, FirecrawlHttpTransport) and self.control is None:
            return _failure(
                request.request_id,
                FetchFailureKind.POLICY_BLOCKED,
                "Firecrawl live transport requires durable acquisition control",
            )

        control = self.control
        claim = None
        if control is not None:
            claim = control.claim(
                request,
                policy_hash=_policy_hash(self.policy),
                estimated_credits=self.estimated_credits,
                now=self.now(),
            )
            if claim.state == "replay":
                if claim.replay_result is None:
                    return _failure(
                        request.request_id,
                        FetchFailureKind.UNEXPECTED_FAILURE,
                        "Firecrawl replay claim omitted its stored result",
                    )
                return claim.replay_result
            if claim.state != "dispatch":
                kind, diagnostic = _claim_failure(claim.state)
                return _failure(request.request_id, kind, claim.safe_diagnostic or diagnostic)

        started = time.monotonic()
        result: FetchResult
        charged_credits: int | None = None
        try:
            response = await asyncio.wait_for(
                self.transport.scrape(
                    FirecrawlScrapeRequest(
                        url=decision.canonical_url,
                        timeout_seconds=float(request.timeout_seconds),
                        max_response_bytes=request.max_bytes + _PROVIDER_ENVELOPE_ALLOWANCE,
                        max_age_ms=0 if request.forced_freshness else DEFAULT_MAX_AGE_MS,
                    )
                ),
                timeout=request.timeout_seconds,
            )
            result, charged_credits = await self._normalize(
                request, decision.canonical_url, response, started
            )
        except TimeoutError:
            result = _failure(
                request.request_id,
                FetchFailureKind.TIMEOUT,
                "bounded Firecrawl timeout",
                retryable=True,
            )
        except FirecrawlTransportError as error:
            result = _failure(
                request.request_id, error.kind, error.diagnostic, retryable=error.retryable
            )
        except Exception:
            result = _failure(
                request.request_id,
                FetchFailureKind.UNEXPECTED_FAILURE,
                "Firecrawl transport returned an unexpected failure",
            )
        if claim is not None and control is not None:
            try:
                control.complete(
                    request.request_id,
                    result=result,
                    charged_credits=charged_credits,
                    now=self.now(),
                )
            except Exception:
                return _failure(
                    request.request_id,
                    FetchFailureKind.UNEXPECTED_FAILURE,
                    "Firecrawl dispatch outcome could not be recorded",
                )
        return result

    async def _normalize(
        self,
        request: FetchRequest,
        requested_url: str,
        response: Mapping[str, Any],
        started: float,
    ) -> tuple[FetchResult, int | None]:
        if response.get("success") is not True:
            return (
                _failure(
                    request.request_id,
                    self._provider_failure_kind(response),
                    "Firecrawl returned an unsuccessful scrape",
                ),
                None,
            )
        data = _mapping(response.get("data"))
        if data is None:
            return _failure(
                request.request_id, FetchFailureKind.INVALID_RESPONSE, "Firecrawl omitted data"
            ), None
        raw_html = data.get("rawHtml")
        if not isinstance(raw_html, str) or not raw_html:
            return (
                _failure(
                    request.request_id,
                    FetchFailureKind.INVALID_RESPONSE,
                    "Firecrawl did not return raw HTML",
                ),
                self._credits(data),
            )
        raw_data = raw_html.encode("utf-8")
        if len(raw_data) > request.max_bytes:
            return (
                _failure(
                    request.request_id,
                    FetchFailureKind.INVALID_RESPONSE,
                    "Firecrawl raw HTML exceeds byte bound",
                ),
                self._credits(data),
            )
        metadata = _mapping(data.get("metadata")) or {}
        status = metadata.get("statusCode")
        if not isinstance(status, int):
            return (
                _failure(
                    request.request_id,
                    FetchFailureKind.INVALID_RESPONSE,
                    "Firecrawl did not establish a target status",
                ),
                self._credits(data),
            )
        if not 200 <= status < 300:
            return (
                _failure(
                    request.request_id,
                    self._provider_status_kind(status),
                    "Firecrawl target did not return a successful status",
                ),
                self._credits(data),
            )
        final_url = metadata.get("url") or metadata.get("sourceURL")
        if not isinstance(final_url, str):
            return (
                _failure(
                    request.request_id,
                    FetchFailureKind.INVALID_RESPONSE,
                    "Firecrawl returned an invalid target URL",
                ),
                self._credits(data),
            )
        try:
            final_url = self.preflight.check_redirect(requested_url, final_url, self.policy)
        except ValueError:
            return (
                _failure(
                    request.request_id,
                    FetchFailureKind.POLICY_BLOCKED,
                    "Firecrawl final URL leaves the approved source policy",
                ),
                self._credits(data),
            )
        rejection = self._target_rejection(raw_html, final_url)
        if rejection is not None:
            return (
                _failure(request.request_id, rejection, "Firecrawl returned a target access page"),
                self._credits(data),
            )
        content_type = metadata.get("contentType")
        normalized_type = (
            content_type.split(";", 1)[0].strip().lower()
            if isinstance(content_type, str)
            else "text/html"
        )
        if normalized_type not in {"text/html", "application/xhtml+xml"}:
            return (
                _failure(
                    request.request_id,
                    FetchFailureKind.INVALID_RESPONSE,
                    "Firecrawl returned unsupported non-HTML content",
                ),
                self._credits(data),
            )
        try:
            remaining = request.timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError
            normalized = await acanonicalize_content(
                raw_data,
                media_type=normalized_type,
                max_chars=request.max_bytes,
                max_pages=request.max_pages,
                timeout_seconds=remaining,
            )
        except TimeoutError:
            return (
                _failure(
                    request.request_id,
                    FetchFailureKind.TIMEOUT,
                    "Firecrawl normalization timed out",
                ),
                self._credits(data),
            )
        except (ContentLimitError, UnsupportedContentError):
            return (
                _failure(
                    request.request_id,
                    FetchFailureKind.INVALID_RESPONSE,
                    "Firecrawl HTML cannot be normalized within bounds",
                ),
                self._credits(data),
            )
        raw_ref = self.artifacts.put(raw_data, media_type=normalized_type)
        normalized_ref = self.artifacts.put(normalized.encode("utf-8"), media_type="text/plain")
        return (
            FetchResult(
                request_id=request.request_id,
                final_url=final_url,
                content_type=normalized_type,
                raw_artifact=raw_ref,
                rendered_html_artifact=raw_ref,
                normalized_artifact=normalized_ref,
                normalized_text=normalized,
                engine=self.backend_name,
                engine_version=self.backend_version,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            ),
            self._credits(data),
        )

    @staticmethod
    def _target_rejection(raw_html: str, final_url: str | None = None) -> FetchFailureKind | None:
        """Classify an interstitial returned with a success status.

        Deliberately narrow: challenge vendor fingerprints and challenge titles, a login-shaped
        final URL, or a short page whose only substance is a password form. A card page that
        merely links to "Login" is real content and must not be refused.
        """
        lowered = raw_html.lower()
        match = _TITLE_RE.search(raw_html)
        title = " ".join(match.group(1).split()).lower() if match else ""
        if any(m in title for m in _CHALLENGE_TITLES) or any(
            m in lowered for m in _CHALLENGE_BODY_MARKERS
        ):
            return FetchFailureKind.CAPTCHA_DETECTED
        path = urlsplit(final_url).path.lower() if final_url else ""
        if any(m in path for m in _LOGIN_URL_MARKERS):
            return FetchFailureKind.AUTHENTICATION_REQUIRED
        if _PASSWORD_INPUT_RE.search(raw_html) and len(raw_html) <= _SMALL_PAGE_CHARS:
            return FetchFailureKind.AUTHENTICATION_REQUIRED
        return None

    @staticmethod
    def _provider_status_kind(status: int) -> FetchFailureKind:
        if status in {401, 403}:
            return FetchFailureKind.AUTHENTICATION_REQUIRED
        if status == 429:
            return FetchFailureKind.RATE_LIMITED
        if status in {408, 504}:
            return FetchFailureKind.TIMEOUT
        return FetchFailureKind.INVALID_RESPONSE

    @staticmethod
    def _provider_failure_kind(response: Mapping[str, Any]) -> FetchFailureKind:
        code = response.get("code")
        if code == "insufficient_credits":
            return FetchFailureKind.BUDGET_EXHAUSTED
        if code == "THIRD_PARTY_DATA_TERMS_REQUIRED":
            return FetchFailureKind.POLICY_BLOCKED
        return FetchFailureKind.INVALID_RESPONSE

    @staticmethod
    def _credits(data: Mapping[str, Any]) -> int | None:
        metadata = _mapping(data.get("metadata"))
        provider = _mapping(metadata.get("provider")) if metadata is not None else None
        value = provider.get("creditsCost") if provider is not None else None
        return value if isinstance(value, int) and value >= 0 else None
