from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from ingestion.artifacts import ArtifactIntegrityError, ContentAddressedStore
from ingestion.canonical import canonicalize_content
from ingestion.contracts import (
    FetchAttempt,
    FetchRequest,
    PageKind,
    SourcePolicyRecord,
    WatchTarget,
)
from ingestion.diff import diff_text
from ingestion.fetch import Crawl4AIBackend, ManualUploadBackend
from ingestion.preflight import RobotsRules, SourcePreflight, canonicalize_url, robots_url
from ingestion.snapshots import SnapshotService
from ingestion.storage import ConflictingWriteError, FinancialIngestionStore

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
FIXTURES = Path(__file__).parents[1] / "ingestion" / "fixtures"


def policy(*, manual_only: bool = False) -> SourcePolicyRecord:
    return SourcePolicyRecord(
        policy_id="issuer-hdfc",
        name="HDFC official",
        owner="HDFC Bank",
        domain="hdfcbank.com",
        source_url="https://www.hdfcbank.com/cards/infinia",
        terms_url="https://www.hdfcbank.com/terms",
        terms_read_on=date(2026, 10, 1),
        automated_access_permitted=not manual_only,
        manual_only=manual_only,
        allowed_page_classes=("card_page", "tnc_pdf"),
        minimum_delay_seconds=10,
        reviewed_on=date(2026, 10, 1),
        reviewed_by="curator-1",
    )


def request(
    *, url: str = "https://www.hdfcbank.com/cards/infinia", max_bytes: int = 50_000
) -> FetchRequest:
    return FetchRequest(
        request_id="fetch-1",
        canonical_url=url,
        source_policy_id="issuer-hdfc",
        evidence_kind="official_page",
        page_class=PageKind.CARD_PAGE,
        max_bytes=max_bytes,
        max_pages=1,
        timeout_seconds=3,
        run_id="run-1",
    )


def target() -> WatchTarget:
    return WatchTarget(
        target_id="watch-1",
        canonical_url="https://www.hdfcbank.com/cards/infinia",
        source_policy_id="issuer-hdfc",
        target_fact_ids=("card:hdfc-infinia",),
        page_kind=PageKind.CARD_PAGE,
        check_frequency_days=365,
        preferred_backend="local",
    )


def attempt(attempt_id: str = "attempt-1") -> FetchAttempt:
    return FetchAttempt(
        attempt_id=attempt_id,
        request_id="fetch-1",
        backend="manual",
        backend_version="fi1",
        started_at=NOW,
        ended_at=NOW,
        final_url=target().canonical_url,
        response_class="success",
        retry_index=0,
    )


def test_content_addressed_store_is_deduplicated_and_immutable(tmp_path: Path) -> None:
    store = ContentAddressedStore(tmp_path / "artifacts")
    first = store.put(b"same bytes", media_type="text/plain")
    second = store.put(b"same bytes", media_type="text/plain")
    assert first == second
    assert store.read(first) == b"same bytes"
    assert first.relative_path is not None
    first_path = tmp_path / "artifacts" / first.relative_path
    first_path.write_bytes(b"tampered")
    with pytest.raises(ArtifactIntegrityError):
        store.read(first)


def test_url_and_redirect_policy_are_canonical_and_ssrf_safe() -> None:
    assert canonicalize_url("HTTPS://WWW.HDFCBANK.COM:443/cards?utm_source=x&b=2&a=1") == (
        "https://www.hdfcbank.com/cards?a=1&b=2"
    )
    assert (
        robots_url("https://www.hdfcbank.com/cards/infinia")
        == "https://www.hdfcbank.com/robots.txt"
    )
    preflight = SourcePreflight()
    blocked = preflight.check(request(url="http://127.0.0.1/private"), policy())
    assert not blocked.allowed and blocked.failure_kind is not None
    assert blocked.failure_kind.value == "policy_blocked"
    with pytest.raises(ValueError):
        preflight.check_redirect(request().canonical_url, "https://evil.example/steal", policy())
    resolver = SourcePreflight(resolve_host=lambda host: ("127.0.0.1",))
    assert not resolver.check(request(), policy()).allowed
    with pytest.raises(ValueError):
        preflight.check_redirect_chain(
            (request().canonical_url, "https://www.hdfcbank.com/one", "https://evil.example/two"),
            policy(),
        )


def test_robots_rules_choose_longest_allow_match() -> None:
    rules = RobotsRules.parse((FIXTURES / "fi1_robots.txt").read_text())
    assert not rules.allowed("https://www.hdfcbank.com/private")
    assert rules.allowed("https://www.hdfcbank.com/private/public-terms")
    assert rules.crawl_delay() == 10


def test_canonicalization_removes_untrusted_markup_and_bounds_content() -> None:
    result = canonicalize_content(
        (FIXTURES / "fi1_hostile.html").read_bytes(), media_type="text/html", max_chars=500
    )
    assert result == "Visible issuer text"
    with pytest.raises(ValueError):
        canonicalize_content(b"x" * 20, media_type="text/plain", max_chars=10)
    with pytest.raises(ValueError):
        canonicalize_content(b"secret", media_type="application/pdf", max_chars=100)


def test_page_class_and_robots_are_required_before_automated_dispatch() -> None:
    tnc_request = request().model_copy(update={"evidence_kind": "tnc_pdf", "page_class": None})
    missing_robots = SourcePreflight().check(tnc_request, policy())
    assert missing_robots.failure_kind is not None
    assert missing_robots.failure_kind.value == "robots_blocked"
    disallowed_class = SourcePreflight().check(
        tnc_request,
        policy().model_copy(update={"allowed_page_classes": ("card_page",)}),
        robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
    )
    assert disallowed_class.failure_kind is not None
    assert (
        disallowed_class.failure_kind.value
        == "policy_blocked"
    )
    with pytest.raises(ValueError, match="tnc_pdf"):
        FetchRequest.model_validate(
            request().model_dump()
            | {"evidence_kind": "tnc_pdf", "page_class": PageKind.CARD_PAGE}
        )
    with pytest.raises(ValueError, match="manual_capture"):
        FetchRequest.model_validate(
            request().model_dump()
            | {"evidence_kind": "manual_capture", "page_class": PageKind.CARD_PAGE}
        )


def test_robots_wildcards_and_end_anchors_are_deterministic() -> None:
    rules = RobotsRules.parse("User-agent: *\nDisallow: /private/*\nAllow: /exact$\n")
    assert not rules.allowed("https://www.hdfcbank.com/private/terms")
    assert rules.allowed("https://www.hdfcbank.com/exactly")
    assert rules.allowed("https://www.hdfcbank.com/exact")


def test_manual_upload_capture_replays_and_preserves_lineage(tmp_path: Path) -> None:
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    database = FinancialIngestionStore(tmp_path / "ingestion.sqlite", now=lambda: NOW)
    database.put_source_policy(policy(manual_only=True))
    database.put_watch_target(target())
    upload = tmp_path / "capture.html"
    upload.write_bytes((FIXTURES / "fi1_success.html").read_bytes())
    backend = ManualUploadBackend(upload, artifacts=artifacts, policy=policy(manual_only=True))
    result = asyncio.run(backend.fetch(request()))
    assert result.failure is None
    service = SnapshotService(store=database, artifacts=artifacts, now=lambda: NOW)
    first = service.capture(target_id="watch-1", result=result, attempt=attempt())
    second = service.capture(target_id="watch-1", result=result, attempt=attempt("attempt-2"))
    assert first is not None and second == first
    assert first.supersedes_snapshot_id is None
    assert database.list_audit_events(entity_id=first.snapshot_id)
    assert artifacts.read(first.raw_artifact).startswith(b"<!doctype html>")
    assert service.compare(target_id="watch-1", current=result).changed is False


def test_changed_capture_supersedes_and_immutable_replay_conflicts(tmp_path: Path) -> None:
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    database = FinancialIngestionStore(tmp_path / "ingestion.sqlite", now=lambda: NOW)
    database.put_source_policy(policy())
    database.put_watch_target(target())
    upload = tmp_path / "capture.html"
    upload.write_bytes((FIXTURES / "fi1_success.html").read_bytes())
    backend = ManualUploadBackend(upload, artifacts=artifacts, policy=policy(manual_only=True))
    result = asyncio.run(backend.fetch(request()))
    service = SnapshotService(store=database, artifacts=artifacts, now=lambda: NOW)
    first = service.capture(target_id="watch-1", result=result, attempt=attempt())
    assert first is not None
    upload.write_text("<html><body><main><p>Changed issuer terms.</p></main></body></html>")
    changed = asyncio.run(backend.fetch(request()))
    assert service.compare(target_id="watch-1", current=changed).changed is True
    second = service.capture(target_id="watch-1", result=changed, attempt=attempt("attempt-2"))
    assert second is not None and second.snapshot_id != first.snapshot_id
    assert second.supersedes_snapshot_id == first.snapshot_id
    assert service.compare(target_id="watch-1", current=changed).changed is False
    with pytest.raises(ConflictingWriteError):
        database.put_snapshot(first.model_copy(update={"canonical_markdown": "tampered"}))


def test_changed_raw_artifact_retains_lineage_when_normalized_text_is_same(tmp_path: Path) -> None:
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    database = FinancialIngestionStore(tmp_path / "ingestion.sqlite", now=lambda: NOW)
    database.put_source_policy(policy(manual_only=True))
    database.put_watch_target(target())
    upload = tmp_path / "capture.html"
    upload.write_text("<html><body><main><p>Stable text.</p></main></body></html>")
    backend = ManualUploadBackend(upload, artifacts=artifacts, policy=policy(manual_only=True))
    service = SnapshotService(store=database, artifacts=artifacts, now=lambda: NOW)
    first = service.capture(
        target_id="watch-1", result=asyncio.run(backend.fetch(request())), attempt=attempt()
    )
    upload.write_text("<html><body><div><main>Stable text.</main></div></body></html>")
    second = service.capture(
        target_id="watch-1",
        result=asyncio.run(backend.fetch(request())),
        attempt=attempt("attempt-2"),
    )
    assert first is not None and second is not None
    assert first.canonical_markdown == second.canonical_markdown
    assert first.snapshot_id != second.snapshot_id
    assert second.supersedes_snapshot_id == first.snapshot_id


def test_manual_upload_rejects_oversized_and_unsupported_material(tmp_path: Path) -> None:
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    huge = tmp_path / "huge.txt"
    huge.write_bytes(b"x" * 20)
    backend = ManualUploadBackend(huge, artifacts=artifacts, policy=policy(manual_only=True))
    result = asyncio.run(backend.fetch(request(max_bytes=10)))
    assert result.failure is not None and result.failure.kind.value == "invalid_response"
    unsupported = tmp_path / "capture.bin"
    unsupported.write_bytes(b"bytes")
    binary_result = asyncio.run(
        ManualUploadBackend(
            unsupported, artifacts=artifacts, policy=policy(manual_only=True)
        ).fetch(request())
    )
    assert (
        binary_result.failure is not None and binary_result.failure.kind.value == "invalid_response"
    )


class _FakeResult:
    success = True
    url = "https://www.hdfcbank.com/cards/infinia"
    redirected_url = url
    html = "<html><body><main><p>Annual fee is INR 12,500.</p></main></body></html>"
    links: dict[str, list[dict[str, str]]] = {"internal": []}


class _FakeCrawler:
    async def __aenter__(self) -> _FakeCrawler:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def arun(self, *, url: str, config: Any) -> _FakeResult:
        assert url == request().canonical_url
        return _FakeResult()


def test_crawl4ai_adapter_uses_fixture_client_without_importing_or_networking(
    tmp_path: Path,
) -> None:
    artifacts = ContentAddressedStore(tmp_path / "artifacts")

    def factory(config: Any) -> _FakeCrawler:
        assert config is None  # injected fixture path never constructs the optional SDK
        return _FakeCrawler()

    backend = Crawl4AIBackend(
        artifacts=artifacts,
        policy=policy(),
        robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        crawler_factory=factory,
    )
    result = asyncio.run(backend.fetch(request()))
    assert result.failure is None
    assert result.engine == "local"
    assert result.normalized_text == "Annual fee is INR 12,500."


def test_crawl4ai_adapter_rejects_untrusted_redirect_and_unavailable_sdk(tmp_path: Path) -> None:
    class Redirected(_FakeResult):
        redirected_url = "https://evil.example/redirect"

    class RedirectCrawler(_FakeCrawler):
        async def arun(self, *, url: str, config: Any) -> Redirected:
            return Redirected()

    backend = Crawl4AIBackend(
        artifacts=ContentAddressedStore(tmp_path / "artifacts"),
        policy=policy(),
        robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        crawler_factory=lambda config: RedirectCrawler(),
    )
    blocked = asyncio.run(backend.fetch(request()))
    assert blocked.failure is not None and blocked.failure.kind.value == "policy_blocked"

    unavailable = Crawl4AIBackend(
        artifacts=ContentAddressedStore(tmp_path / "other"),
        policy=policy(),
        robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        resolve_host=lambda host: ("93.184.216.34",),
    )
    result = asyncio.run(unavailable.fetch(request()))
    assert result.failure is not None
    assert "Crawl4AI" in result.failure.diagnostic


def test_crawl4ai_failure_is_typed_without_retry_or_fallback(tmp_path: Path) -> None:
    class FailedResult:
        success = False
        error_message = "CAPTCHA challenge"

    class FailedCrawler:
        async def __aenter__(self) -> FailedCrawler:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def arun(self, *, url: str, config: Any) -> FailedResult:
            return FailedResult()

    backend = Crawl4AIBackend(
        artifacts=ContentAddressedStore(tmp_path / "artifacts"),
        policy=policy(),
        robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        crawler_factory=lambda config: FailedCrawler(),
    )
    result = asyncio.run(backend.fetch(request()))
    assert result.failure is not None
    assert result.failure.kind.value == "captcha_detected"
    assert result.failure.retryable is False


def test_crawl4ai_rejects_pdf_under_official_page_evidence(tmp_path: Path) -> None:
    class PdfResult(_FakeResult):
        content_type = "application/pdf"
        body = b"%PDF-1.7 fixture"

    class PdfCrawler(_FakeCrawler):
        async def arun(self, *, url: str, config: Any) -> PdfResult:
            return PdfResult()

    backend = Crawl4AIBackend(
        artifacts=ContentAddressedStore(tmp_path / "artifacts"),
        policy=policy(),
        robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        crawler_factory=lambda config: PdfCrawler(),
    )
    result = asyncio.run(backend.fetch(request()))
    assert result.failure is not None and result.failure.kind.value == "invalid_response"


def test_automated_preflight_turns_robots_and_manual_policy_into_typed_failures() -> None:
    preflight = SourcePreflight()
    robots = RobotsRules.parse("User-agent: *\nDisallow: /cards\n")
    blocked = preflight.check(request(), policy(), robots=robots)
    assert not blocked.allowed and blocked.failure_kind is not None
    assert blocked.failure_kind.value == "robots_blocked"
    manual = preflight.check(request(), policy(manual_only=True))
    assert manual.allowed is False and manual.failure_kind is not None
    assert manual.failure_kind.value == "policy_blocked"


def test_crawl4ai_enforces_domain_delay_and_redirect_chain(tmp_path: Path) -> None:
    class Chained(_FakeResult):
        redirect_chain = [
            {"url": "https://www.hdfcbank.com/step-one"},
            {"url": "https://evil.example/step-two"},
        ]

    class ChainedCrawler(_FakeCrawler):
        async def arun(self, *, url: str, config: Any) -> Chained:
            return Chained()

    ticks = iter((NOW, NOW))
    backend = Crawl4AIBackend(
        artifacts=ContentAddressedStore(tmp_path / "artifacts"),
        policy=policy(),
        robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        crawler_factory=lambda config: ChainedCrawler(),
        now=lambda: next(ticks),
    )
    first = asyncio.run(backend.fetch(request()))
    assert first.failure is not None and first.failure.kind.value == "policy_blocked"

    class GoodCrawler(_FakeCrawler):
        async def arun(self, *, url: str, config: Any) -> _FakeResult:
            return _FakeResult()

    backend = Crawl4AIBackend(
        artifacts=ContentAddressedStore(tmp_path / "other"),
        policy=policy(),
        robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        crawler_factory=lambda config: GoodCrawler(),
        now=lambda: NOW,
    )
    assert asyncio.run(backend.fetch(request())).failure is None
    delayed = asyncio.run(backend.fetch(request()))
    assert delayed.failure is not None and delayed.failure.kind.value == "rate_limited"


def test_diff_is_byte_deterministic_and_only_changes_on_normalized_content() -> None:
    first = diff_text("Annual fee\n", "Annual fee\n")
    second = diff_text("Annual fee\n", "Annual fee\nUpdated")
    assert not first.changed and first.unified_diff == ""
    assert (
        second.changed
        and second.unified_diff == "--- previous\n+++ current\n@@ -1 +1,2 @@\n Annual fee\n+Updated"
    )
