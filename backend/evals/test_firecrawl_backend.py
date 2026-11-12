from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest

from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import (
    FetchFailureKind,
    FetchRequest,
    FetchResult,
    PageKind,
    SourcePolicyRecord,
    WatchTarget,
)
from ingestion.firecrawl_backend import FirecrawlBackend
from ingestion.firecrawl_transport import (
    FIRECRAWL_SCRAPE_URL,
    FirecrawlHttpTransport,
    FirecrawlScrapeRequest,
    FirecrawlTransportError,
)
from ingestion.preflight import RobotsRules, SourcePreflight


def policy() -> SourcePolicyRecord:
    return SourcePolicyRecord(
        policy_id="issuer-example",
        name="Example issuer",
        owner="Example Bank",
        domain="issuer.example",
        source_url="https://issuer.example/card",
        terms_url="https://issuer.example/terms",
        terms_read_on=date(2026, 11, 1),
        automated_access_permitted=True,
        manual_only=False,
        allowed_page_classes=("card_page", "tnc_pdf"),
        minimum_delay_seconds=10,
        reviewed_on=date(2026, 11, 1),
        reviewed_by="curator-1",
    )


def request(**updates: Any) -> FetchRequest:
    return FetchRequest(
        request_id="firecrawl-1",
        canonical_url="https://issuer.example/card",
        source_policy_id="issuer-example",
        evidence_kind="official_page",
        page_class=PageKind.CARD_PAGE,
        max_bytes=4096,
        max_pages=1,
        timeout_seconds=3,
        forced_freshness=False,
        run_id="run-1",
    ).model_copy(update=updates)


class FixtureTransport:
    def __init__(self, response: dict[str, Any] | Exception) -> None:
        self.response = response
        self.calls: list[FirecrawlScrapeRequest] = []

    async def scrape(self, scrape_request: FirecrawlScrapeRequest) -> dict[str, Any]:
        self.calls.append(scrape_request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class Claim:
    def __init__(
        self,
        state: Literal["dispatch", "replay", "blocked", "pending", "conflict"],
        replay_result: FetchResult | None = None,
    ) -> None:
        self.state = state
        self.safe_diagnostic = f"claim is {state}"
        self.replay_result = replay_result


class FixtureControl:
    def __init__(self, claim: Claim) -> None:
        self.next_claim = claim
        self.claims = 0
        self.dispatch_starts: list[str] = []
        self.completions: list[tuple[str, object, int | None]] = []

    def claim(
        self,
        request: FetchRequest,
        *,
        policy_hash: str,
        estimated_credits: int,
        now: datetime,
    ) -> Claim:
        del request, policy_hash, estimated_credits, now
        self.claims += 1
        return self.next_claim

    def complete(
        self,
        request_id: str,
        *,
        result: FetchResult,
        charged_credits: int | None,
        now: datetime,
    ) -> None:
        del now
        self.completions.append((request_id, result, charged_credits))

    def mark_dispatch_started(self, request_id: str, *, now: datetime) -> None:
        del now
        self.dispatch_starts.append(request_id)

    def due_targets(
        self, targets: Sequence[WatchTarget], *, now: datetime, limit: int
    ) -> list[str]:
        del targets, now, limit
        return []


def successful_response(**metadata: Any) -> dict[str, Any]:
    return {
        "success": True,
        "data": {
            "rawHtml": "<html><body><main>Issuer terms</main></body></html>",
            "metadata": {
                "url": "https://issuer.example/card",
                "sourceURL": "https://issuer.example/card",
                "statusCode": 200,
                "contentType": "text/html",
                **metadata,
            },
        },
    }


def backend(
    tmp_path: Path, transport: FixtureTransport, *, enabled: bool = True
) -> FirecrawlBackend:
    return FirecrawlBackend(
        artifacts=ContentAddressedStore(tmp_path / "artifacts"),
        policy=policy(),
        robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        transport=transport,
        enabled=enabled,
        preflight=SourcePreflight(resolve_host=lambda _host: ("93.184.216.34",)),
    )


def test_disabled_default_never_calls_transport(tmp_path: Path) -> None:
    transport = FixtureTransport(successful_response())
    result = asyncio.run(backend(tmp_path, transport, enabled=False).fetch(request()))
    assert result.failure is not None
    assert result.failure.kind is FetchFailureKind.POLICY_BLOCKED
    assert transport.calls == []


def test_preflight_runs_before_firecrawl_dispatch(tmp_path: Path) -> None:
    transport = FixtureTransport(successful_response())
    result = asyncio.run(
        backend(tmp_path, transport).fetch(request(canonical_url="https://evil.example/card"))
    )
    assert result.failure is not None
    assert result.failure.kind is FetchFailureKind.POLICY_BLOCKED
    assert transport.calls == []


def test_html_result_uses_explicit_safe_scrape_options_and_preserves_artifacts(
    tmp_path: Path,
) -> None:
    transport = FixtureTransport(successful_response())
    store = ContentAddressedStore(tmp_path / "artifacts")
    subject = FirecrawlBackend(
        artifacts=store,
        policy=policy(),
        robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        transport=transport,
        enabled=True,
        preflight=SourcePreflight(resolve_host=lambda _host: ("93.184.216.34",)),
    )
    result = asyncio.run(subject.fetch(request()))
    assert result.failure is None
    assert result.raw_artifact is not None
    assert result.normalized_artifact is not None
    assert result.rendered_html_artifact == result.raw_artifact
    assert result.provider_envelope_artifact is not None
    assert result.evidence_fidelity == "provider_rendered_html"
    envelope = json.loads(store.read(result.provider_envelope_artifact).decode("utf-8"))
    assert envelope["schema"] == "tripwise.firecrawl-provider-envelope/v1"
    assert envelope["evidence_fidelity"] == "provider_rendered_html"
    assert envelope["is_original_issuer_http_bytes"] is False
    assert envelope["complete_redirect_chain_available"] is False
    assert envelope["raw_html_sha256"] == result.raw_artifact.sha256
    assert envelope["normalized_sha256"] == result.normalized_artifact.sha256
    assert store.read(result.raw_artifact).startswith(b"<html>")
    assert result.normalized_text == "Issuer terms"
    assert len(transport.calls) == 1
    wire = transport.calls[0]
    assert wire.url == "https://issuer.example/card"
    assert wire.formats == ("rawHtml",)
    assert wire.max_age_ms == 172_800_000
    assert wire.proxy == "basic"
    assert wire.parsers == ()
    assert wire.only_main_content is False
    assert wire.only_clean_content is False
    assert wire.actions == ()
    assert "actions" not in wire.wire_payload()
    assert wire.wire_payload()["parsers"] == []


def test_forced_freshness_disables_provider_cache_reuse(tmp_path: Path) -> None:
    transport = FixtureTransport(successful_response())
    result = asyncio.run(backend(tmp_path, transport).fetch(request(forced_freshness=True)))
    assert result.failure is None
    assert transport.calls[0].max_age_ms == 0


def test_challenge_login_and_pdf_are_refused_without_claiming_success(
    tmp_path: Path,
) -> None:
    login_url = "https://issuer.example/login?next=/card"
    cases: tuple[tuple[str, dict[str, Any], FetchFailureKind], ...] = (
        (
            "<html><head><title>Just a moment...</title></head><body>wait</body></html>",
            {},
            FetchFailureKind.CAPTCHA_DETECTED,
        ),
        (
            '<html><body><div class="g-recaptcha"></div>Card</body></html>',
            {},
            FetchFailureKind.CAPTCHA_DETECTED,
        ),
        (
            "<html><body>Welcome</body></html>",
            {"url": login_url},
            FetchFailureKind.AUTHENTICATION_REQUIRED,
        ),
        (
            '<html><body><form><input type="password" name="p"></form></body></html>',
            {},
            FetchFailureKind.AUTHENTICATION_REQUIRED,
        ),
    )
    for body, overrides, expected in cases:
        response = successful_response(**overrides)
        response["data"]["rawHtml"] = body
        transport = FixtureTransport(response)
        result = asyncio.run(backend(tmp_path, transport).fetch(request()))
        assert result.failure is not None, body
        assert result.failure.kind is expected, body
        assert result.raw_artifact is None


def test_ordinary_issuer_page_mentioning_login_is_not_refused(tmp_path: Path) -> None:
    page = (
        "<html><head><title>Example Card</title></head><body>"
        '<nav><a href="/netbanking/login">Login</a> <a href="/signin">Sign in</a></nav>'
        "<main>Annual fee 500. Reward 2 points per 100.</main>"
        "<footer>Beware of phishing: this is not a challenge or captcha page.</footer>"
        "</body></html>"
    )
    response = successful_response()
    response["data"]["rawHtml"] = page
    transport = FixtureTransport(response)
    result = asyncio.run(backend(tmp_path, transport).fetch(request()))
    assert result.failure is None
    assert "Annual fee 500" in result.normalized_text


def test_pdf_evidence_is_refused_before_dispatch(tmp_path: Path) -> None:
    transport = FixtureTransport(successful_response())
    result = asyncio.run(
        backend(tmp_path, transport).fetch(
            request(evidence_kind="tnc_pdf", page_class=PageKind.TNC_PDF)
        )
    )
    assert result.failure is not None
    assert result.failure.kind is FetchFailureKind.INVALID_RESPONSE
    assert transport.calls == []


def test_provider_failure_is_typed_and_never_retried(tmp_path: Path) -> None:
    transport = FixtureTransport(
        FirecrawlTransportError(
            FetchFailureKind.RATE_LIMITED, "provider rate limit", retryable=True
        )
    )
    result = asyncio.run(backend(tmp_path, transport).fetch(request()))
    assert result.failure is not None
    assert result.failure.kind is FetchFailureKind.RATE_LIMITED
    assert result.failure.retryable is True
    assert len(transport.calls) == 1


def test_durable_claim_replays_without_dispatch_and_completes_one_dispatch(tmp_path: Path) -> None:
    replay = request().model_copy(update={"request_id": "other"})
    stored = backend(tmp_path, FixtureTransport(successful_response())).artifacts.put(
        b"stored", media_type="text/plain"
    )
    replay_result = FetchResult(
        request_id=replay.request_id,
        raw_artifact=stored,
        normalized_artifact=stored,
        normalized_text="stored",
    )
    replay_transport = FixtureTransport(successful_response())
    replay_control = FixtureControl(Claim("replay", replay_result))
    replay_subject = FirecrawlBackend(
        artifacts=ContentAddressedStore(tmp_path / "replay-artifacts"),
        policy=policy(),
        robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        transport=replay_transport,
        control=replay_control,
        enabled=True,
        preflight=SourcePreflight(resolve_host=lambda _host: ("93.184.216.34",)),
    )
    assert asyncio.run(replay_subject.fetch(replay)) == replay_result
    assert replay_transport.calls == []
    assert replay_control.completions == []

    dispatch_transport = FixtureTransport(successful_response())
    dispatch_control = FixtureControl(Claim("dispatch"))
    dispatch_subject = FirecrawlBackend(
        artifacts=ContentAddressedStore(tmp_path / "dispatch-artifacts"),
        policy=policy(),
        robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        transport=dispatch_transport,
        control=dispatch_control,
        enabled=True,
        preflight=SourcePreflight(resolve_host=lambda _host: ("93.184.216.34",)),
    )
    result = asyncio.run(dispatch_subject.fetch(request()))
    assert result.failure is None
    assert len(dispatch_transport.calls) == 1
    assert len(dispatch_control.completions) == 1


def test_http_transport_uses_fixed_endpoint_bounds_response_and_does_not_retry() -> None:
    calls: list[httpx.Request] = []

    def handler(incoming: httpx.Request) -> httpx.Response:
        calls.append(incoming)
        return httpx.Response(200, content=b"x" * 129)

    transport = FirecrawlHttpTransport(
        api_key="not-a-real-secret",
        enabled=True,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(FirecrawlTransportError) as error:
        asyncio.run(
            transport.scrape(
                FirecrawlScrapeRequest(
                    url="https://issuer.example/card",
                    timeout_seconds=3,
                    max_response_bytes=128,
                )
            )
        )
    assert error.value.kind is FetchFailureKind.INVALID_RESPONSE
    assert len(calls) == 1
    assert str(calls[0].url) == FIRECRAWL_SCRAPE_URL
    body = json.loads(calls[0].content)
    assert body["formats"] == ["rawHtml"]
    assert body["proxy"] == "basic"
    assert body["parsers"] == []


def test_provider_redirect_outside_source_policy_is_blocked(tmp_path: Path) -> None:
    transport = FixtureTransport(successful_response(url="https://evil.example/card"))
    result = asyncio.run(backend(tmp_path, transport).fetch(request()))
    assert result.failure is not None
    assert result.failure.kind is FetchFailureKind.POLICY_BLOCKED


def test_missing_target_identity_or_status_is_refused(tmp_path: Path) -> None:
    for metadata in ({"statusCode": 200}, {"url": request().canonical_url}):
        transport = FixtureTransport(
            {"success": True, "data": {"rawHtml": "<main>Terms</main>", "metadata": metadata}}
        )
        result = asyncio.run(backend(tmp_path, transport).fetch(request()))
        assert result.failure is not None
        assert result.failure.kind is FetchFailureKind.INVALID_RESPONSE


@pytest.mark.parametrize(
    ("status", "payload", "kind"),
    [
        (
            403,
            {"success": False, "code": "THIRD_PARTY_DATA_TERMS_REQUIRED"},
            FetchFailureKind.POLICY_BLOCKED,
        ),
        (403, {"success": False, "error": "forbidden"}, FetchFailureKind.AUTHENTICATION_REQUIRED),
        (402, {"success": False, "error": "no credits"}, FetchFailureKind.BUDGET_EXHAUSTED),
    ],
)
def test_http_error_bodies_map_to_typed_failures_without_retry(
    status: int, payload: dict[str, Any], kind: FetchFailureKind
) -> None:
    calls = 0

    def handler(_incoming: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json=payload)

    transport = FirecrawlHttpTransport(
        api_key="not-a-real-secret",
        enabled=True,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(FirecrawlTransportError) as error:
        asyncio.run(
            transport.scrape(
                FirecrawlScrapeRequest(
                    url="https://issuer.example/card", timeout_seconds=3, max_response_bytes=4096
                )
            )
        )
    assert error.value.kind is kind
    assert calls == 1
    assert "forbidden" not in error.value.diagnostic
