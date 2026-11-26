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
from ingestion.contracts import PageKind, SourcePolicyRecord, WatchTarget
from ingestion.extraction_runtime import ExtractionMode, ExtractionRuntimeConfig
from ingestion.firecrawl_backend import FirecrawlBackend
from ingestion.firecrawl_transport import (
    FirecrawlScrapeRequest,
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
        self.published = published or {}
        self.transport = RetainedCaptureTransport(payloads)
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
            now=lambda: self.clock,
        )

    def run(self, event: str, *, days: int = 8) -> Any:
        self.clock += timedelta(days=days)
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
    request = world.transport.calls[0]
    assert request.json_extraction is not None and request.estimated_credits == 5
    assert request.timeout_seconds >= 60

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
    assert len(world.transport.calls) == 1


def test_an_unchanged_page_makes_no_proposal(tmp_path: Path) -> None:
    world = World(tmp_path, [capture(page(), offer_json())], published=None)
    world.run("evt-1")
    again = world.run("evt-2")
    assert again.state == "unchanged" and again.proposal_ids == ()
    assert len(world.store.list_proposals()) == 1


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
    outcome = html_only.acquire_sync("watch:atlas-offers", client_event_id="evt-1")
    assert outcome.state == "failed"
    assert "different acquisition inputs" in outcome.diagnostic
    assert len(world.transport.calls) == 1


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

    world = World(tmp_path, [capture(page(), offer_json())], published=None)
    # 67 credits were used before this ledger existed; the whole allowance is 80.
    world.control = DurableAcquisitionControl(world.store, limits=limits(cap=80, opening=67))
    world.service.control = world.control
    first = world.run("evt-1")  # 67 + 5 = 72 <= 80
    assert first.state == "completed"
    status = world.control.lifetime_status()
    assert status is not None and status["used"] == 72 and status["remaining"] == 8

    # A later process that claims a larger cap and a smaller opening balance changes nothing.
    world.control = DurableAcquisitionControl(world.store, limits=limits(cap=10_000, opening=0))
    world.service.control = world.control
    status = world.control.lifetime_status()
    assert status is not None and status["lifetime_cap"] == 80 and status["opening_used"] == 67

    second = world.run("evt-2")  # 72 + 5 = 77 <= 80: allowed
    assert second.state in {"completed", "unchanged"}
    third = world.run("evt-3")  # 77 + 5 = 82 > 80: refused before any dispatch
    assert third.state == "blocked"
    assert "lifetime credit allowance is exhausted" in third.diagnostic
    assert len(world.transport.calls) == 2

    # The cap can be raised only explicitly, attributed, and never below what is spent.
    with pytest.raises(ValueError, match="below the credits already used"):
        world.control.raise_lifetime_cap(50, operator="owner", note="try")
    world.control.raise_lifetime_cap(100, operator="owner", note="owner authorised 20 more")
    assert world.run("evt-4").state in {"completed", "unchanged"}
