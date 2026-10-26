"""Provider-neutral fetching with offline manual and optional Crawl4AI backends."""

from __future__ import annotations

import asyncio
import importlib.metadata
import mimetypes
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from ingestion.artifacts import ContentAddressedStore
from ingestion.canonical import ContentLimitError, UnsupportedContentError, canonicalize_content
from ingestion.contracts import (
    FetchFailure,
    FetchFailureKind,
    FetchRequest,
    FetchResult,
    SourcePolicyRecord,
)
from ingestion.preflight import RobotsRules, SourcePreflight


class FetchBackend(Protocol):
    async def fetch(self, request: FetchRequest) -> FetchResult:
        """Fetch one approved request without creating a financial proposal."""


def _failure(
    request_id: str, kind: FetchFailureKind, diagnostic: str, *, retryable: bool = False
) -> FetchResult:
    return FetchResult(
        request_id=request_id,
        failure=FetchFailure(kind=kind, diagnostic=diagnostic[:1000], retryable=retryable),
    )


class ManualUploadBackend:
    """Read a curator-supplied local file through the same result contract."""

    backend_name = "manual"
    backend_version = "fi1"

    def __init__(
        self,
        upload_path: Path,
        *,
        artifacts: ContentAddressedStore,
        policy: SourcePolicyRecord,
        robots: RobotsRules | None = None,
        preflight: SourcePreflight | None = None,
    ) -> None:
        self.upload_path = upload_path
        self.artifacts = artifacts
        self.policy = policy
        self.robots = robots
        self.preflight = preflight or SourcePreflight()

    async def fetch(self, request: FetchRequest) -> FetchResult:
        decision = self.preflight.check(request, self.policy, robots=self.robots, manual=True)
        if not decision.allowed:
            return _failure(
                request.request_id,
                decision.failure_kind or FetchFailureKind.POLICY_BLOCKED,
                decision.diagnostic or "manual upload blocked",
            )
        try:
            data = await asyncio.wait_for(
                asyncio.to_thread(self.upload_path.read_bytes), timeout=request.timeout_seconds
            )
        except OSError as error:
            return _failure(
                request.request_id,
                FetchFailureKind.INVALID_RESPONSE,
                f"manual upload unavailable: {error}",
            )
        except TimeoutError:
            return _failure(
                request.request_id, FetchFailureKind.TIMEOUT, "manual capture timed out"
            )
        if len(data) > request.max_bytes:
            return _failure(
                request.request_id,
                FetchFailureKind.INVALID_RESPONSE,
                "manual upload exceeds byte bound",
            )
        media_type = mimetypes.guess_type(self.upload_path.name)[0] or "text/plain"
        try:
            normalized = await asyncio.wait_for(
                asyncio.to_thread(
                    canonicalize_content,
                    data,
                    media_type=media_type,
                    max_chars=request.max_bytes,
                    max_pages=request.max_pages,
                ),
                timeout=request.timeout_seconds,
            )
        except TimeoutError:
            return _failure(
                request.request_id, FetchFailureKind.TIMEOUT, "manual capture timed out"
            )
        except (ContentLimitError, UnsupportedContentError) as error:
            return _failure(request.request_id, FetchFailureKind.INVALID_RESPONSE, str(error))
        raw = self.artifacts.put(data, media_type=media_type)
        normalized_ref = self.artifacts.put(normalized.encode("utf-8"), media_type="text/plain")
        return FetchResult(
            request_id=request.request_id,
            final_url=decision.canonical_url,
            content_type=media_type,
            raw_artifact=raw,
            normalized_text=normalized,
            normalized_artifact=normalized_ref,
            engine=self.backend_name,
            engine_version=self.backend_version,
            duration_ms=0,
        )


class Crawl4AIBackend:
    """Crawl4AI adapter whose import and execution are optional and explicit.

    ``crawler_factory`` exists for fixture-backed tests. Production construction
    imports Crawl4AI only when this backend is actually used.
    """

    backend_name = "local"

    def __init__(
        self,
        *,
        artifacts: ContentAddressedStore,
        policy: SourcePolicyRecord,
        robots: RobotsRules | None = None,
        user_agent: str = "Tripwise-FinancialIngestion/1.0",
        crawler_factory: Callable[[Any], Any] | None = None,
        preflight: SourcePreflight | None = None,
        resolve_host: Callable[[str], Any] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.artifacts = artifacts
        self.policy = policy
        self.robots = robots
        self.user_agent = user_agent
        self.crawler_factory = crawler_factory
        self.resolve_host = resolve_host
        self.preflight = preflight or SourcePreflight(
            user_agent=user_agent, resolve_host=resolve_host
        )
        self.now = now or (lambda: datetime.now(UTC))
        self._last_dispatch: dict[str, datetime] = {}
        self._dispatch_lock = asyncio.Lock()

    @staticmethod
    def _failure_kind(error_message: str) -> FetchFailureKind:
        lowered = error_message.lower()
        if "captcha" in lowered or "challenge" in lowered:
            return FetchFailureKind.CAPTCHA_DETECTED
        if "login" in lowered or "auth" in lowered:
            return FetchFailureKind.AUTHENTICATION_REQUIRED
        if "429" in lowered or "rate" in lowered:
            return FetchFailureKind.RATE_LIMITED
        if "timeout" in lowered:
            return FetchFailureKind.TIMEOUT
        return FetchFailureKind.INVALID_RESPONSE

    @staticmethod
    def _markdown(result: Any) -> str:
        markdown = getattr(result, "markdown", "")
        if isinstance(markdown, str):
            return markdown
        return str(getattr(markdown, "fit_markdown", None) or getattr(markdown, "raw_markdown", ""))

    async def _crawl(self, request: FetchRequest, url: str) -> Any:
        if self.crawler_factory is not None:
            crawler = self.crawler_factory(None)
        else:
            try:
                module = __import__(
                    "crawl4ai",
                    fromlist=["AsyncWebCrawler", "BrowserConfig", "CacheMode", "CrawlerRunConfig"],
                )
                AsyncWebCrawler = module.AsyncWebCrawler
                BrowserConfig = module.BrowserConfig
                CacheMode = module.CacheMode
                CrawlerRunConfig = module.CrawlerRunConfig
            except ImportError as error:
                raise RuntimeError(
                    "Crawl4AI is not installed; install the ingestion-local extra"
                ) from error
            browser_config = BrowserConfig(headless=True, user_agent=self.user_agent)
            run_config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                check_robots_txt=True,
                excluded_tags=["script", "style", "noscript", "nav", "footer"],
                max_retries=0,
                page_timeout=request.timeout_seconds * 1000,
                word_count_threshold=1,
            )
            crawler = AsyncWebCrawler(config=browser_config)
        async with crawler as active:
            return await active.arun(url=url, config=locals().get("run_config"))

    async def fetch(self, request: FetchRequest) -> FetchResult:
        if self.crawler_factory is None and self.preflight.resolve_host is None:
            return _failure(
                request.request_id,
                FetchFailureKind.POLICY_BLOCKED,
                "automated fetching requires an injected public DNS resolver",
            )
        decision = self.preflight.check(request, self.policy, robots=self.robots)
        if not decision.allowed:
            return _failure(
                request.request_id,
                decision.failure_kind or FetchFailureKind.POLICY_BLOCKED,
                decision.diagnostic or "preflight blocked",
            )
        host = urlsplit(decision.canonical_url).hostname or ""
        robots_delay = self.robots.crawl_delay() if self.robots else None
        delay = max(float(self.policy.minimum_delay_seconds), float(robots_delay or 0))
        async with self._dispatch_lock:
            started = self.now()
            last_dispatch = self._last_dispatch.get(host)
            if last_dispatch is not None and started - last_dispatch < timedelta(seconds=delay):
                return _failure(
                    request.request_id,
                    FetchFailureKind.RATE_LIMITED,
                    f"source delay requires {delay} seconds between requests",
                )
            self._last_dispatch[host] = started
        try:
            result = await asyncio.wait_for(
                self._crawl(request, decision.canonical_url), timeout=request.timeout_seconds
            )
        except TimeoutError:
            return _failure(
                request.request_id,
                FetchFailureKind.TIMEOUT,
                "bounded Crawl4AI timeout",
                retryable=True,
            )
        except RuntimeError as error:
            return _failure(request.request_id, FetchFailureKind.UNEXPECTED_FAILURE, str(error))
        except Exception as error:  # provider boundary: never expose raw crawler errors
            return _failure(
                request.request_id,
                FetchFailureKind.UNEXPECTED_FAILURE,
                f"Crawl4AI failure: {error}",
            )
        if not bool(getattr(result, "success", False)):
            message = str(
                getattr(result, "error_message", "Crawl4AI returned an unsuccessful result")
            )
            return _failure(
                request.request_id, self._failure_kind(message), message, retryable=False
            )
        redirect_chain_raw = getattr(result, "redirect_chain", None)
        redirect_chain: list[str] = [decision.canonical_url]
        if isinstance(redirect_chain_raw, (list, tuple)):
            for item in redirect_chain_raw:
                candidate = item.get("url") if isinstance(item, dict) else item
                if isinstance(candidate, str):
                    redirect_chain.append(candidate)
        final_url = str(
            getattr(result, "redirected_url", None)
            or getattr(result, "url", decision.canonical_url)
        )
        if redirect_chain[-1] != final_url:
            redirect_chain.append(final_url)
        try:
            current_decision = self.preflight.check(request, self.policy, robots=self.robots)
            if not current_decision.allowed:
                return _failure(
                    request.request_id,
                    current_decision.failure_kind or FetchFailureKind.POLICY_BLOCKED,
                    current_decision.diagnostic or "post-fetch policy revalidation failed",
                )
            final_url = self.preflight.check_redirect_chain(redirect_chain, self.policy)
        except ValueError as error:
            return _failure(request.request_id, FetchFailureKind.POLICY_BLOCKED, str(error))
        declared_type = str(getattr(result, "content_type", "") or "").split(";", 1)[0]
        raw_html = getattr(result, "html", None) or getattr(result, "cleaned_html", None)
        raw_body = getattr(result, "body", None)
        if request.evidence_kind == "tnc_pdf":
            raw_data = bytes(raw_body) if isinstance(raw_body, (bytes, bytearray)) else b""
            if not raw_data.startswith(b"%PDF"):
                return _failure(
                    request.request_id,
                    FetchFailureKind.INVALID_RESPONSE,
                    "T&C request did not return a PDF body",
                )
            media_type = "application/pdf"
        else:
            raw_data = (
                raw_html.encode("utf-8")
                if isinstance(raw_html, str)
                else bytes(raw_html or self._markdown(result), "utf-8")
            )
            media_type = declared_type or "text/html"
        if len(raw_data) > request.max_bytes:
            return _failure(
                request.request_id,
                FetchFailureKind.INVALID_RESPONSE,
                "Crawl4AI response exceeds byte bound",
            )
        try:
            normalized = canonicalize_content(
                raw_data,
                media_type=media_type,
                max_chars=request.max_bytes,
                max_pages=request.max_pages,
            )
        except (ContentLimitError, UnsupportedContentError) as error:
            return _failure(request.request_id, FetchFailureKind.INVALID_RESPONSE, str(error))
        raw_ref = self.artifacts.put(raw_data, media_type=media_type)
        normalized_ref = self.artifacts.put(normalized.encode("utf-8"), media_type="text/plain")
        links: list[str] = []
        raw_links = getattr(result, "links", {})
        for value in raw_links.get("internal", []) if isinstance(raw_links, dict) else []:
            href = value.get("href") if isinstance(value, dict) else None
            if isinstance(href, str):
                try:
                    links.append(self.preflight.check_redirect(final_url, href, self.policy))
                except ValueError:
                    continue
        duration_ms = max(0, int((datetime.now(UTC) - started).total_seconds() * 1000))
        try:
            version = importlib.metadata.version("crawl4ai")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        return FetchResult(
            request_id=request.request_id,
            final_url=final_url,
            content_type="text/html",
            raw_artifact=raw_ref,
            rendered_html_artifact=raw_ref if media_type == "text/html" else None,
            normalized_artifact=normalized_ref,
            normalized_text=normalized,
            outbound_links=tuple(sorted(set(links))),
            engine=self.backend_name,
            engine_version=version,
            duration_ms=duration_ms,
        )
