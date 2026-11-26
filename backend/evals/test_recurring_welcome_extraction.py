"""Welcome offers through the real acquisition service, from Firecrawl-hosted JSON extraction.

Execution mode: retained synthetic captures served by ``RetainedCaptureTransport`` (no network, no
credits), real SQLite, real content-addressed artifacts, real deterministic validation. The
``data.json`` blocks stand for what Firecrawl's v2 ``json`` format returns; they are authored for
these tests and prove the integration, not Firecrawl's real response.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from ingestion.acquisition import DurableAcquisitionService, RetainedCaptureTransport
from ingestion.acquisition_control import AcquisitionControlLimits, DurableAcquisitionControl
from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import FetchFailureKind, PageKind, SourcePolicyRecord, WatchTarget
from ingestion.extraction_runtime import ExtractionMode, ExtractionRuntimeConfig
from ingestion.firecrawl_backend import FirecrawlBackend
from ingestion.firecrawl_transport import (
    FirecrawlScrapeRequest,
    FirecrawlTransportError,
    JsonExtraction,
    canonical_schema_json,
)
from ingestion.preflight import RobotsRules
from ingestion.storage import FinancialIngestionStore
from ingestion.welcome_extraction import WELCOME_SCHEMA, WelcomeTargetConfig, offer_id_for

START = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
URL = "https://issuer.example/cards/atlas/offers"
CARD = "axis-atlas"
TITLE = "Atlas Welcome Benefit"
OFFER_ID = offer_id_for(CARD, TITLE)

PAGE = (
    "<html><body><main><h2>{title}</h2>"
    "<p>Earn {points} EDGE Miles as a welcome benefit when you spend ₹ {spend} within "
    "30 days of card issuance.</p>"
    "<p>Offer valid till {valid_to}.</p>"
    "<p>Existing Axis Bank credit card holders are not eligible.</p></main></body></html>"
)


def page(
    *, points: str = "2,500", spend: str = "30,000", valid_to: str = "30 November 2026"
) -> str:
    return PAGE.format(title=TITLE, points=points, spend=spend, valid_to=valid_to)


def offer_json(
    *, points: str = "2,500", spend: str = "30,000", valid_to: str | None = "30 November 2026"
) -> dict[str, Any]:
    offer: dict[str, Any] = {
        "title": {"value": TITLE, "quote": TITLE},
        "bonus_points": {"value": points, "quote": f"Earn {points} EDGE Miles"},
        "min_spend_minor": {"value": f"₹ {spend}", "quote": f"spend ₹ {spend}"},
        "spend_window_days": {"value": "30", "quote": "within 30 days of card issuance"},
        "eligibility_exclusions": ["Existing Axis Bank credit card holders are not eligible."],
    }
    if valid_to is not None:
        offer["valid_to"] = {"value": valid_to, "quote": f"Offer valid till {valid_to}"}
    return {"offers": [offer]}


def capture(html: str, extracted: dict[str, Any] | None, *, credits: int = 5) -> dict[str, Any]:
    data: dict[str, Any] = {
        "rawHtml": html,
        "metadata": {
            "url": URL,
            "sourceURL": URL,
            "statusCode": 200,
            "contentType": "text/html; charset=utf-8",
            "cacheState": "miss",
            "provider": {"creditsCost": credits},
        },
    }
    if extracted is not None:
        data["json"] = extracted
    return {"success": True, "data": data}


class CycleTransport:
    """Serves the capture for the current collection cycle to every request in that cycle.

    A welcome-offer cycle makes one plain fetch (the change check) and, only if the page changed,
    one JSON-extraction fetch; both see the same page, as a real source would within seconds.
    """

    def __init__(self, world: World, payloads: list[dict[str, Any]]) -> None:
        self.world = world
        self.payloads = payloads
        self.per_call = False  # serve payloads by call index instead of by cycle
        self.fail_next = 0  # raise a provider failure for this many upcoming calls
        self.calls: list[FirecrawlScrapeRequest] = []

    async def scrape(self, request: FirecrawlScrapeRequest) -> dict[str, Any]:
        self.calls.append(request)
        if self.fail_next > 0:
            self.fail_next -= 1
            raise FirecrawlTransportError(FetchFailureKind.TIMEOUT, "provider timed out")
        position = len(self.calls) - 1 if self.per_call else self.world.cycle
        index = min(max(position, 0), len(self.payloads) - 1)
        payload: dict[str, Any] = json.loads(json.dumps(self.payloads[index]))
        data = payload["data"]
        metadata = data["metadata"]
        metadata.pop("provider", None)
        metadata["creditsUsed"] = request.estimated_credits  # what the real v2 response reports
        if request.json_extraction is None:
            data.pop("json", None)  # a plain fetch carries no structured extraction
        return payload

    @property
    def extraction_calls(self) -> list[FirecrawlScrapeRequest]:
        return [c for c in self.calls if c.json_extraction is not None]


class World:
    """One real store, artifact directory, control and clock, reopenable like a restart."""

    def __init__(
        self,
        tmp_path: Path,
        payloads: list[dict[str, Any]],
        *,
        published: dict[str, Any] | None,
        card: str = CARD,
    ) -> None:
        self.card = card
        self.offer_id = offer_id_for(card, TITLE)
        self.root = tmp_path / "data"
        self.clock = START
        self.cycle = -1
        self.published = published or {}
        self.transport = CycleTransport(self, payloads)
        self.open()
        self.store.put_source_policy(
            SourcePolicyRecord(
                policy_id="issuer-offers",
                name="Issuer offers",
                owner="Synthetic Issuer",
                domain="issuer.example",
                source_url=URL,
                terms_url="https://issuer.example/terms",
                terms_read_on=date(2026, 11, 1),
                automated_access_permitted=True,
                manual_only=False,
                allowed_page_classes=("card_page", "offer_page"),
                minimum_delay_seconds=10,
                reviewed_on=date(2026, 11, 1),
                reviewed_by="alice",
            )
        )
        self.store.put_watch_target(
            WatchTarget(
                target_id="watch:atlas-offers",
                canonical_url=URL,
                source_policy_id="issuer-offers",
                target_fact_ids=(self.offer_id,),
                page_kind=PageKind.OFFER_PAGE,
                check_frequency_days=7,
                preferred_backend="firecrawl",
                manual_only=False,
            )
        )

    def open(self) -> None:
        """(Re)open every durable object from disk, as a new process would."""
        self.store = FinancialIngestionStore(self.root / "ingestion.sqlite", now=lambda: self.clock)
        self.artifacts = ContentAddressedStore(self.root / "artifacts")
        self.control = DurableAcquisitionControl(
            self.store,
            limits=AcquisitionControlLimits(
                per_request_credits=5,
                per_run_credits=20,
                per_month_credits=100,
                pricing_version="test-v1",
                extraction_intent="raw_html+firecrawl_json_v2",
            ),
        )
        self.service = DurableAcquisitionService(
            store=self.store,
            artifacts=self.artifacts,
            control=self.control,
            transport=self.transport,
            extraction_configs_by_target={
                "watch:atlas-offers": ExtractionRuntimeConfig(mode=ExtractionMode.FIRECRAWL_MANAGED)
            },
            welcome_targets={
                "watch:atlas-offers": WelcomeTargetConfig(
                    card_id=self.card,
                    source_url=URL,
                    default_currency="INR",
                    points_currency_id="axis-edge-miles",
                )
            },
            published_welcome_rows=lambda: self.published,
            default_robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
            firecrawl_enabled=True,
            source_spacing=self._space,
            now=lambda: self.clock,
        )

    async def _space(self, seconds: float) -> None:
        self.clock += timedelta(seconds=seconds)  # the pause between two requests to one source

    def run(self, event: str, *, days: int = 8) -> Any:
        self.clock += timedelta(days=days)
        self.cycle += 1
        return self.service.acquire_sync("watch:atlas-offers", client_event_id=event)


def test_json_request_shape_and_cost_follow_the_documented_contract() -> None:
    schema = canonical_schema_json(WELCOME_SCHEMA)
    request = FirecrawlScrapeRequest(
        url=URL,
        timeout_seconds=60,
        max_response_bytes=1_000_000,
        json_extraction=JsonExtraction(schema_json=schema, prompt="extract"),
    )
    payload = request.wire_payload()
    assert payload["formats"] == [
        "rawHtml",
        {"type": "json", "schema": json.loads(schema), "prompt": "extract"},
    ]
    assert request.estimated_credits == 5  # 1 page + 4 for JSON extraction
    html_only = FirecrawlScrapeRequest(url=URL, timeout_seconds=20, max_response_bytes=10)
    assert html_only.estimated_credits == 1 and html_only.wire_payload()["formats"] == ["rawHtml"]


def test_backend_refuses_to_underreserve_or_use_a_short_timeout_for_json(tmp_path: Path) -> None:
    store = ContentAddressedStore(tmp_path / "a")
    policy = SourcePolicyRecord(
        policy_id="p",
        name="p",
        owner="o",
        domain="issuer.example",
        source_url=URL,
        terms_url="https://issuer.example/t",
        terms_read_on=date(2026, 11, 1),
        automated_access_permitted=True,
        manual_only=False,
        allowed_page_classes=("offer_page",),
        minimum_delay_seconds=10,
        reviewed_on=date(2026, 11, 1),
        reviewed_by="alice",
    )
    extraction = JsonExtraction(schema_json=canonical_schema_json(WELCOME_SCHEMA), prompt="x")
    with pytest.raises(ValueError, match="at least 5 credits"):
        FirecrawlBackend(
            artifacts=store,
            policy=policy,
            transport=RetainedCaptureTransport(capture("<p>x</p>", None)),
            estimated_credits=1,
            json_extraction=extraction,
        )


def test_initial_collection_creates_one_evidenced_unverified_insert_proposal(
    tmp_path: Path,
) -> None:
    world = World(tmp_path, [capture(page(), offer_json())], published=None)
    outcome = world.run("evt-1")

    assert outcome.state == "completed", outcome.diagnostic
    assert outcome.extraction_mode == "firecrawl_managed"
    assert outcome.llm_calls == 0  # Firecrawl ran the model; nothing here called one
    assert len(outcome.proposal_ids) == 1
    check, extraction = world.transport.calls  # a plain page fetch, then the JSON extraction
    assert check.json_extraction is None and check.estimated_credits == 1
    assert extraction.json_extraction is not None and extraction.estimated_credits == 5
    assert extraction.timeout_seconds >= 60
    assert outcome.credits_reserved == 6 and len(outcome.request_ids) == 2

    proposal = world.store.get_proposal(outcome.proposal_ids[0])
    assert proposal is not None
    assert (proposal.target_table, proposal.target_id, proposal.intent) == (
        "card_acquisition_offers",
        OFFER_ID,
        "insert",
    )
    row = proposal.proposed_row
    assert row["min_spend_minor"] == 3_000_000 and row["bonus_points"] == 2500
    assert row["spend_window_days"] == 30 and row["valid_to"] == "2026-11-30"
    assert row["currency"] == "INR" and row["bonus_currency_id"] == "axis-edge-miles"
    assert row["expected_approval_days"] is None and row["annual_fee_minor"] is None
    assert row["provenance"]["verified_by"] == "UNVERIFIED"
    assert row["provenance"]["needs_verification"] is True
    snapshot = world.store.get_snapshot(outcome.snapshot_id)
    assert snapshot is not None
    for field in proposal.field_proposals:  # every quote is a verbatim slice of the retained page
        span = field.evidence_spans[0]
        assert (
            snapshot.canonical_markdown[span.normalized_start : span.normalized_end] == span.quote
        )
    assert {f.field_path for f in proposal.field_proposals} == {
        "title",
        "bonus_points",
        "min_spend_minor",
        "spend_window_days",
        "valid_to",
    }
    # Documented credits were reserved, not the HTML-only price.
    status = world.control.status(outcome.request_id)
    assert status is not None and status.estimated_credits == 5


def test_the_same_event_replays_after_a_restart_without_another_scrape(tmp_path: Path) -> None:
    world = World(tmp_path, [capture(page(), offer_json())], published=None)
    first = world.run("evt-1")
    world.open()  # a new process: everything reopens from disk
    replay = world.service.acquire_sync("watch:atlas-offers", client_event_id="evt-1")
    assert replay.state == "completed" and replay.replayed_fetch is True
    assert replay.proposal_ids == first.proposal_ids
    assert replay.credits_reserved == 0  # a replay dispatches and spends nothing
    assert len(world.transport.calls) == 2


def test_an_unchanged_page_makes_no_proposal(tmp_path: Path) -> None:
    world = World(tmp_path, [capture(page(), offer_json())], published=None)
    world.run("evt-1")
    again = world.run("evt-2")
    assert again.state == "unchanged" and again.proposal_ids == ()
    assert len(world.store.list_proposals()) == 1
    # Only the 1-credit check was paid for; no JSON extraction was requested.
    assert again.credits_reserved == 1 and len(world.transport.extraction_calls) == 1
    assert len(world.transport.calls) == 3


def test_changed_terms_on_a_published_offer_become_an_update_proposal(tmp_path: Path) -> None:
    world = World(
        tmp_path,
        [capture(page(), offer_json()), capture(page(spend="40,000"), offer_json(spend="40,000"))],
        published=None,
    )
    first = world.run("evt-1")
    inserted = world.store.get_proposal(first.proposal_ids[0])
    assert inserted is not None
    published = dict(inserted.proposed_row)
    published["provenance"] = {**published["provenance"], "verified_by": "curator-1"}
    world.published = {OFFER_ID: published}  # as if a curator approved and published it

    changed = world.run("evt-2")
    assert changed.state == "completed", changed.diagnostic
    update = world.store.get_proposal(changed.proposal_ids[0])
    assert update is not None and update.intent == "update"
    assert [f.field_path for f in update.field_proposals] == ["min_spend_minor"]
    assert update.field_proposals[0].old_value == 3_000_000
    assert update.proposed_row["min_spend_minor"] == 4_000_000
    assert update.proposed_row["provenance"]["verified_by"] == "curator-1"  # untouched until review
    assert len(world.store.list_proposals()) == 2  # the first proposal survives


def test_a_quote_not_in_the_page_is_dropped_and_the_offer_reported_incomplete(
    tmp_path: Path,
) -> None:
    extracted = offer_json()
    extracted["offers"][0]["valid_to"] = {
        "value": "31 December 2026",
        "quote": "Offer valid till 31 December 2026",  # the page says 30 November
    }
    world = World(tmp_path, [capture(page(), extracted)], published=None)
    outcome = world.run("evt-1")
    assert outcome.proposal_ids == ()
    (incomplete,) = world.store.list_incomplete_extractions()
    assert incomplete["offer_id"] == OFFER_ID and incomplete["missing"] == ["valid_to"]
    assert "not present" in incomplete["rejected"]["valid_to"]


def test_a_value_the_quote_does_not_support_is_rejected(tmp_path: Path) -> None:
    extracted = offer_json()
    extracted["offers"][0]["min_spend_minor"] = {
        "value": "₹ 99,999",  # not what the quote says
        "quote": "spend ₹ 30,000",
    }
    world = World(tmp_path, [capture(page(), extracted)], published=None)
    world.run("evt-1")
    (incomplete,) = world.store.list_incomplete_extractions()
    assert "min_spend_minor" in incomplete["missing"]
    assert "does not support" in incomplete["rejected"]["min_spend_minor"]


def test_missing_provider_extraction_is_reported_without_inventing_a_draft(
    tmp_path: Path,
) -> None:
    world = World(tmp_path, [capture(page(), None)], published=None)
    outcome = world.run("evt-1")
    assert outcome.state == "failed" and outcome.proposal_ids == ()
    assert "no structured extraction" in outcome.diagnostic
    assert world.store.get_snapshot(outcome.snapshot_id) is not None  # the capture is kept
    assert world.store.list_proposals() == []


def test_an_html_only_request_id_cannot_be_reused_for_json_extraction(tmp_path: Path) -> None:
    world = World(tmp_path, [capture(page(), offer_json())], published=None)
    world.run("evt-1")
    html_only = DurableAcquisitionService(
        store=world.store,
        artifacts=world.artifacts,
        control=world.control,
        transport=world.transport,
        default_robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        firecrawl_enabled=True,
        now=lambda: world.clock,
    )
    # The same request id as the JSON extraction request, asked for as a plain fetch.
    outcome = html_only.acquire_sync("watch:atlas-offers", client_event_id="evt-1:extract")
    assert outcome.state == "failed"
    assert "different acquisition inputs" in outcome.diagnostic
    assert len(world.transport.calls) == 2


def test_lifetime_allowance_is_durable_cross_run_and_cannot_be_loosened_by_a_later_start(
    tmp_path: Path,
) -> None:
    def limits(*, cap: int, opening: int) -> AcquisitionControlLimits:
        return AcquisitionControlLimits(
            per_request_credits=5,
            per_run_credits=100,
            per_month_credits=1000,
            pricing_version="test-v1",
            extraction_intent="raw_html+firecrawl_json_v2",
            lifetime_credits=cap,
            lifetime_opening_used=opening,
        )

    payloads = [
        capture(page(spend=amount), offer_json(spend=amount))
        for amount in ("30,000", "40,000", "50,000")
    ]
    world = World(tmp_path, payloads, published=None)
    # 67 credits were used before this ledger existed; the whole allowance is 80.
    world.control = DurableAcquisitionControl(world.store, limits=limits(cap=80, opening=67))
    world.service.control = world.control
    first = world.run("evt-1")  # check 1 + extraction 5: 67 + 6 = 73 <= 80
    assert first.state == "completed"
    status = world.control.lifetime_status()
    assert status is not None and status["used"] == 73 and status["remaining"] == 7

    # A later process that claims a larger cap and a smaller opening balance changes nothing.
    world.control = DurableAcquisitionControl(world.store, limits=limits(cap=10_000, opening=0))
    world.service.control = world.control
    status = world.control.lifetime_status()
    assert status is not None and status["lifetime_cap"] == 80 and status["opening_used"] == 67

    world.published = {}
    second = world.run("evt-2")  # the page changed: 73 + 6 = 79 <= 80
    assert second.state == "completed"
    third = world.run("evt-3")  # changed again: the check fits (80), the extraction (85) does not
    assert third.state == "blocked"
    assert "lifetime credit allowance is exhausted" in third.diagnostic
    assert len(world.transport.extraction_calls) == 2  # nothing was dispatched past the cap

    # The cap can be raised only explicitly, attributed, and never below what is spent.
    with pytest.raises(ValueError, match="below the credits already used"):
        world.control.raise_lifetime_cap(50, operator="owner", note="try")
    world.control.raise_lifetime_cap(100, operator="owner", note="owner authorised 20 more")
    assert world.run("evt-4").state in {"completed", "unchanged"}


def test_boilerplate_changes_do_not_trigger_a_paid_extraction(tmp_path: Path) -> None:
    first = page()
    chrome = first.replace(
        "<main>",
        "<nav>Home | Cards | Support</nav><footer>Copyright 2027 Example Bank</footer><main>",
    )
    world = World(
        tmp_path, [capture(first, offer_json()), capture(chrome, offer_json())], published=None
    )
    world.run("evt-1")
    again = world.run("evt-2")
    assert again.state == "unchanged" and again.credits_reserved == 1
    assert len(world.transport.extraction_calls) == 1
    # ...and a changed term inside a term-bearing line does trigger one.
    world.transport.payloads.append(capture(page(points="3,000"), offer_json(points="3,000")))
    world.published = {}
    third = world.run("evt-3")
    assert third.state == "completed" and len(world.transport.extraction_calls) == 2


def test_a_failed_check_is_not_read_as_the_offer_being_withdrawn(tmp_path: Path) -> None:
    world = World(tmp_path, [capture(page(), offer_json())], published=None)
    first = world.run("evt-1")
    inserted = world.store.get_proposal(first.proposal_ids[0])
    assert inserted is not None
    world.published = {inserted.target_id: dict(inserted.proposed_row)}
    checkpoint = world.store.last_extraction_checkpoint("watch:atlas-offers")

    world.transport.fail_next = 1  # the plain fetch times out
    failed = world.run("evt-2")
    assert failed.state in {"failed", "needs_reconciliation"}
    assert failed.proposal_ids == ()
    assert world.store.last_extraction_checkpoint("watch:atlas-offers") == checkpoint
    assert (
        world.published and len(world.store.list_proposals()) == 1
    )  # nothing was removed or added
    assert len(world.transport.extraction_calls) == 1


def test_extraction_binds_to_the_version_it_actually_read(tmp_path: Path) -> None:
    check_view = page(points="2,500")
    extraction_view = page(points="3,000")  # the page changed between the two requests
    world = World(
        tmp_path,
        [capture(check_view, None), capture(extraction_view, offer_json(points="3,000"))],
        published=None,
    )
    world.transport.per_call = True
    outcome = world.run("evt-1")
    assert outcome.state == "completed", outcome.diagnostic
    proposal = world.store.get_proposal(outcome.proposal_ids[0])
    assert proposal is not None and proposal.proposed_row["bonus_points"] == 3000
    snapshot = world.store.get_snapshot(proposal.lineage_ids[0])
    assert snapshot is not None and "3,000" in snapshot.canonical_markdown
    quote = next(f for f in proposal.field_proposals if f.field_path == "bonus_points")
    span = quote.evidence_spans[0]
    assert snapshot.canonical_markdown[span.normalized_start : span.normalized_end] == span.quote


def test_a_failed_extraction_is_retried_on_the_next_pass_even_if_the_page_is_unchanged(
    tmp_path: Path,
) -> None:
    world = World(tmp_path, [capture(page(), None), capture(page(), offer_json())], published=None)
    first = world.run("evt-1")
    assert first.state == "failed" and first.proposal_ids == ()
    assert world.store.last_extraction_checkpoint("watch:atlas-offers") is None
    second = world.run("evt-2")  # same page text, but nothing was ever extracted from it
    assert second.state == "completed" and len(second.proposal_ids) == 1
    third = world.run("evt-3")
    assert third.state == "unchanged"  # now it has been extracted, so it is not paid for again


def test_one_failing_source_does_not_stop_the_others(tmp_path: Path) -> None:
    world = World(tmp_path, [capture(page(), offer_json())], published=None)

    async def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("unexpected")

    original = world.service.acquire
    calls: list[str] = []

    async def flaky(target_id: str, *, client_event_id: str) -> Any:
        calls.append(target_id)
        if target_id == "watch:broken":
            return await boom()
        return await original(target_id, client_event_id=client_event_id)

    world.service.acquire = flaky  # type: ignore[method-assign]
    world.store.put_watch_target(
        WatchTarget(
            target_id="watch:broken",
            canonical_url="https://issuer.example/cards/broken",
            source_policy_id="issuer-offers",
            target_fact_ids=("x",),
            page_kind=PageKind.OFFER_PAGE,
            check_frequency_days=7,
            preferred_backend="firecrawl",
            manual_only=False,
        )
    )
    world.clock += timedelta(days=8)
    batch = world.service.refresh_due_sync(limit=5, client_event_prefix="batch-1")
    states = {o.target_id: o.state for o in batch.outcomes}
    assert states["watch:broken"] == "failed" and states["watch:atlas-offers"] == "completed"


def test_defects_seen_in_a_real_firecrawl_extraction_are_rejected_not_published(
    tmp_path: Path,
) -> None:
    """Synthetic text that reproduces the *kinds* of mistakes a real extraction made.

    A real Firecrawl response labelled "within 30 days" as the minimum spend (a bare 30 parses as
    a rupee amount), returned a quote that was only the number "37", mixed an annual-fee line into a
    welcome offer, claimed both points and a flat amount, and listed a non-welcome "Annual Benefit".
    """
    html = (
        "<html><body><main><h2>Welcome Benefit</h2>"
        "<p>Enjoy 5000 EDGE Miles as welcome benefit upon first transaction within 30 days of card "
        "issuance. Applicable from 20th April 2024.</p><p>Annual fee ₹5,000 + GST.</p>"
        "<h2>Annual Benefit</h2><p>Earn 2500 EDGE Miles on payment of the annual fee.</p>"
        "<p>Window 37</p></main></body></html>"
    )
    extracted = {
        "offers": [
            {
                "title": {"value": "Welcome Benefit", "quote": "Welcome Benefit"},
                "bonus_points": {
                    "value": "5000",
                    "quote": "5000 EDGE Miles as welcome benefit upon first transaction",
                },
                "bonus_flat_minor": {"value": "₹5,000", "quote": "₹5,000"},
                "min_spend_minor": {"value": "30", "quote": "within 30 days of card issuance"},
                "spend_window_days": {"value": "37", "quote": "37"},
                "valid_from": {"value": "20th April 2024", "quote": "20th April 2024"},
            },
            {
                "title": {"value": "Annual Benefit", "quote": "Annual Benefit"},
                "bonus_points": {
                    "value": "2500",
                    "quote": "2500 EDGE Miles on payment of the annual fee",
                },
            },
        ]
    }
    world = World(tmp_path, [capture(html, extracted)], published=None)
    outcome = world.run("evt-1")
    assert outcome.proposal_ids == ()  # nothing is proposed from this page
    drafts = {d["title"]: d for d in world.store.list_incomplete_extractions()}

    welcome = drafts["Welcome Benefit"]
    assert set(welcome["missing"]) >= {"min_spend_minor", "spend_window_days", "valid_to"}
    assert "30" not in welcome["evidenced"]  # the bare 30 was not accepted as a rupee amount
    assert "min_spend_minor" in welcome["rejected"] and "spend_window_days" in welcome["rejected"]
    assert "bonus_flat_minor" in welcome["rejected"]  # "₹5,000" alone says nothing about a bonus
    assert "min_spend_minor" not in welcome["evidenced"]
    assert "not a welcome offer" in drafts["Annual Benefit"]["reason"]


def test_conflicting_points_and_flat_bonuses_are_not_resolved_by_guessing(tmp_path: Path) -> None:
    extracted = offer_json()
    extracted["offers"][0]["bonus_flat_minor"] = {
        "value": "₹2,000",
        "quote": "welcome gift voucher of ₹2,000",
    }
    html = page().replace("</main>", "<p>Also a welcome gift voucher of ₹2,000.</p></main>")
    world = World(tmp_path, [capture(html, extracted)], published=None)
    outcome = world.run("evt-1")
    assert outcome.proposal_ids == ()
    (draft,) = world.store.list_incomplete_extractions()
    assert "conflicting bonus" in draft["reason"]


def test_reextraction_uses_only_retained_material_and_spends_nothing(tmp_path: Path) -> None:
    extracted = offer_json()
    world = World(tmp_path, [capture(page(), extracted)], published=None)
    first = world.run("evt-1")
    assert len(first.proposal_ids) == 1
    calls_before = len(world.transport.calls)
    again = world.service.reextract_welcome_sync("watch:atlas-offers", client_event_id="re-1")
    assert again.state == "completed" and again.credits_reserved == 0
    assert len(world.transport.calls) == calls_before  # no request was made
    assert len(again.proposal_ids) == 1  # derived again from the same retained extraction
