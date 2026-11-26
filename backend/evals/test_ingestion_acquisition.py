"""End-to-end tests for concrete Firecrawl acquisition, refresh-due, and CLI orchestration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from core.db import SEEDS_DIR
from ingestion.acquisition import (
    DurableAcquisitionService,
    RetainedCaptureTransport,
)
from ingestion.acquisition_control import (
    AcquisitionControlLimits,
    DurableAcquisitionControl,
)
from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import (
    FetchRequest,
    PageKind,
    ProposalStatus,
    ReviewDecisionStatus,
    SourcePolicyRecord,
    WatchTarget,
)
from ingestion.extraction_runtime import (
    ExtractionMode,
    ExtractionRuntimeConfig,
)
from ingestion.firecrawl_transport import FirecrawlScrapeRequest
from ingestion.preflight import RobotsRules
from ingestion.review import ReviewService
from ingestion.review_queue import build_review_queue
from ingestion.review_rows import SeedRowSource
from ingestion.storage import FinancialIngestionStore

BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def _policy(
    policy_id: str = "issuer-auto-policy",
    *,
    domain: str = "issuer.example",
    delay_seconds: int = 10,
    automated: bool = True,
    manual_only: bool = False,
) -> SourcePolicyRecord:
    return SourcePolicyRecord(
        policy_id=policy_id,
        name=f"Policy {policy_id}",
        owner="Synthetic Issuer",
        domain=domain,
        source_url=f"https://{domain}/cards/infinia",
        terms_url=f"https://{domain}/terms",
        terms_read_on=date(2026, 11, 1),
        automated_access_permitted=automated,
        manual_only=manual_only,
        allowed_page_classes=("card_page", "offer_page"),
        minimum_delay_seconds=delay_seconds,
        reviewed_on=date(2026, 11, 1),
        reviewed_by="alice",
    )


def _target(
    target_id: str = "watch:hdfc-infinia-auto",
    *,
    policy_id: str = "issuer-auto-policy",
    domain: str = "issuer.example",
    fact_id: str = "hdfc-infinia",
    frequency_days: int = 30,
) -> WatchTarget:
    return WatchTarget(
        target_id=target_id,
        canonical_url=f"https://{domain}/cards/{target_id.replace(':', '-')}",
        source_policy_id=policy_id,
        target_fact_ids=(fact_id,),
        page_kind=PageKind.CARD_PAGE,
        check_frequency_days=frequency_days,
        preferred_backend="firecrawl",
        manual_only=False,
    )


def _firecrawl_envelope(url: str, html: str, *, credits_cost: int = 1) -> dict[str, Any]:
    return {
        "success": True,
        "data": {
            "rawHtml": html,
            "metadata": {
                "url": url,
                "sourceURL": url,
                "statusCode": 200,
                "contentType": "text/html; charset=utf-8",
                "cacheState": "miss",
                "cachedAt": "2026-11-07T12:00:00Z",
                "provider": {"creditsCost": credits_cost},
            },
        },
    }


def _scripted_card_response(
    *,
    card_id: str,
    annual_fee_minor: int,
    raw_fee: str,
    quote: str,
) -> dict[str, Any]:
    current = SeedRowSource(SEEDS_DIR).current_row("cards", card_id)
    proposed = dict(current)
    proposed["annual_fee_minor"] = annual_fee_minor
    return {
        "target_table": "cards",
        "target_id": card_id,
        "proposed_row": proposed,
        "fields": [
            {
                "field_path": "annual_fee_minor",
                "proposed_raw_value": raw_fee,
                "evidence_spans": [
                    {
                        "snapshot_id": "__SNAPSHOT_ID__",
                        "snapshot_hash": "__SNAPSHOT_HASH__",
                        "quote": quote,
                        "field_path": "annual_fee_minor",
                        "verification": "exact",
                    }
                ],
            }
        ],
        "change_summary": f"Updated annual fee to {raw_fee} from retained Firecrawl capture.",
        "extractor_confidence": 0.9,
    }


def _cli(args: list[str], **env: str) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if k not in {"TRIPWISE_ENV", "TRIPWISE_DATA_DIR"}}
    return subprocess.run(
        [sys.executable, "-m", "ingestion.review_server", *args],
        cwd=BACKEND,
        env={**clean, **env},
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_acquire_orchestrates_control_snapshot_provenance_extraction_and_review_queue(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "data" / "ingestion.sqlite"
    artifacts_dir = tmp_path / "data" / "artifacts"
    store = FinancialIngestionStore(db_path, now=lambda: NOW)
    artifacts = ContentAddressedStore(artifacts_dir)

    pol = _policy()
    tgt = _target()
    store.put_source_policy(pol)
    store.put_watch_target(tgt)

    quote = "The annual membership fee is INR 15,000 plus applicable taxes."
    html = f"<html><body><main><h1>Card Terms</h1><p>{quote}</p></main></body></html>"
    transport = RetainedCaptureTransport(_firecrawl_envelope(tgt.canonical_url, html))
    control = DurableAcquisitionControl(
        store,
        limits=AcquisitionControlLimits(
            per_request_credits=1,
            per_run_credits=5,
            per_month_credits=10,
            pricing_version="test-v1",
        ),
    )
    ext_config = ExtractionRuntimeConfig(
        mode=ExtractionMode.SCRIPTED_REPLAY,
        responses=(
            _scripted_card_response(
                card_id="hdfc-infinia",
                annual_fee_minor=1_500_000,
                raw_fee="INR 15,000",
                quote=quote,
            ),
        ),
    )
    service = DurableAcquisitionService(
        store=store,
        artifacts=artifacts,
        control=control,
        transport=transport,
        extraction_config=ext_config,
        seeds_dir=SEEDS_DIR,
        default_robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        firecrawl_enabled=True,
        now=lambda: NOW,
    )

    outcome = service.acquire_sync(tgt.target_id, client_event_id="evt-acquire-001")
    assert outcome.state == "completed"
    assert outcome.snapshot_id is not None
    assert len(outcome.proposal_ids) == 1
    assert outcome.llm_calls == 1
    assert outcome.replayed_fetch is False
    assert outcome.evidence_fidelity == "provider_rendered_html"
    assert outcome.provider_envelope_sha256 is not None
    assert len(transport.calls) == 1

    # Verify provider envelope provenance is stored and never claims rawHtml is original HTTP bytes.
    snapshot = store.get_snapshot(outcome.snapshot_id)
    assert snapshot is not None
    assert snapshot.evidence_fidelity == "provider_rendered_html"
    assert snapshot.provider_envelope_artifact is not None
    envelope = json.loads(artifacts.read(snapshot.provider_envelope_artifact).decode("utf-8"))
    assert envelope["schema"] == "tripwise.firecrawl-provider-envelope/v1"
    assert envelope["evidence_fidelity"] == "provider_rendered_html"
    assert envelope["is_original_issuer_http_bytes"] is False
    assert envelope["complete_redirect_chain_available"] is False
    assert envelope["raw_html_sha256"] == snapshot.raw_sha256
    assert envelope["normalized_sha256"] == snapshot.normalized_sha256

    # Verify proposal is in the real review queue awaiting human curator review.
    review_service = ReviewService(
        store=store,
        artifacts=artifacts,
        rows=SeedRowSource(SEEDS_DIR),
        now=lambda: NOW,
    )
    queue_items = build_review_queue(
        store=store,
        service=review_service,
        as_of=NOW,
        statuses=(ProposalStatus.PENDING,),
    )
    assert [item.proposal_id for item in queue_items] == list(outcome.proposal_ids)

    # Re-running the identical event replays both fetch and extraction with 0 provider/model calls.
    replay = service.acquire_sync(tgt.target_id, client_event_id="evt-acquire-001")
    assert replay.state == "completed"
    assert replay.snapshot_id == outcome.snapshot_id
    assert replay.proposal_ids == outcome.proposal_ids
    assert replay.llm_calls == 0
    assert replay.replayed_fetch is True
    assert len(transport.calls) == 1


def test_persisted_fetch_survives_extraction_failure_and_resumes_without_rescrape(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "data" / "ingestion.sqlite"
    artifacts_dir = tmp_path / "data" / "artifacts"
    store = FinancialIngestionStore(db_path, now=lambda: NOW)
    artifacts = ContentAddressedStore(artifacts_dir)

    pol = _policy()
    tgt = _target()
    store.put_source_policy(pol)
    store.put_watch_target(tgt)

    quote = "The annual membership fee is INR 15,000 plus applicable taxes."
    html = f"<html><body><main><p>{quote}</p></main></body></html>"
    transport = RetainedCaptureTransport(_firecrawl_envelope(tgt.canonical_url, html))
    control = DurableAcquisitionControl(
        store,
        limits=AcquisitionControlLimits(
            per_request_credits=1,
            per_run_credits=5,
            per_month_credits=10,
            pricing_version="test-v1",
        ),
    )

    # First run: extraction fails validation (quote not present in snapshot).
    bad_response = _scripted_card_response(
        card_id="hdfc-infinia",
        annual_fee_minor=1_500_000,
        raw_fee="INR 15,000",
        quote="Nonexistent quote that fails deterministic evidence verification.",
    )
    failing_service = DurableAcquisitionService(
        store=store,
        artifacts=artifacts,
        control=control,
        transport=transport,
        extraction_config=ExtractionRuntimeConfig(
            mode=ExtractionMode.SCRIPTED_REPLAY,
            responses=(bad_response,),
        ),
        seeds_dir=SEEDS_DIR,
        default_robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        firecrawl_enabled=True,
        now=lambda: NOW,
    )
    failed_outcome = failing_service.acquire_sync(
        tgt.target_id, client_event_id="evt-extract-retry"
    )
    assert failed_outcome.state == "failed"
    assert failed_outcome.snapshot_id is not None
    assert failed_outcome.proposal_ids == ()
    assert len(transport.calls) == 1

    # Simulate process restart: reopen SQLite and artifacts, and inject a transport that
    # raises if called, proving the second run never scrapes again.
    class _ForbiddenTransport:
        async def scrape(self, request: FirecrawlScrapeRequest) -> dict[str, Any]:
            raise AssertionError(f"unexpected rescrape for {request.url}")

    reopened_store = FinancialIngestionStore(db_path, now=lambda: NOW + timedelta(minutes=1))
    reopened_artifacts = ContentAddressedStore(artifacts_dir)
    reopened_control = DurableAcquisitionControl(
        reopened_store,
        limits=AcquisitionControlLimits(
            per_request_credits=1,
            per_run_credits=5,
            per_month_credits=10,
            pricing_version="test-v1",
        ),
    )
    good_response = _scripted_card_response(
        card_id="hdfc-infinia",
        annual_fee_minor=1_500_000,
        raw_fee="INR 15,000",
        quote=quote,
    )
    resumed_service = DurableAcquisitionService(
        store=reopened_store,
        artifacts=reopened_artifacts,
        control=reopened_control,
        transport=_ForbiddenTransport(),
        extraction_config=ExtractionRuntimeConfig(
            mode=ExtractionMode.SCRIPTED_REPLAY,
            responses=(good_response,),
        ),
        seeds_dir=SEEDS_DIR,
        default_robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        firecrawl_enabled=True,
        now=lambda: NOW + timedelta(minutes=1),
    )
    resumed_outcome = resumed_service.acquire_sync(
        tgt.target_id, client_event_id="evt-extract-retry"
    )
    assert resumed_outcome.state == "completed"
    assert resumed_outcome.replayed_fetch is True
    assert resumed_outcome.snapshot_id == failed_outcome.snapshot_id
    assert len(resumed_outcome.proposal_ids) == 1


def test_refresh_due_enforces_order_skips_unchanged_preserves_history_and_blocks_ambiguous(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "data" / "ingestion.sqlite"
    artifacts_dir = tmp_path / "data" / "artifacts"
    store = FinancialIngestionStore(db_path, now=lambda: NOW)
    artifacts = ContentAddressedStore(artifacts_dir)

    pol_a = _policy("policy-a", domain="a.issuer.example", delay_seconds=10)
    pol_b = _policy("policy-b", domain="b.issuer.example", delay_seconds=10)
    store.put_source_policy(pol_a)
    store.put_source_policy(pol_b)

    tgt_b = _target(
        "watch:b-card", policy_id="policy-b", domain="b.issuer.example", frequency_days=30
    )
    tgt_a = _target(
        "watch:a-card", policy_id="policy-a", domain="a.issuer.example", frequency_days=7
    )
    store.put_watch_target(tgt_b)
    store.put_watch_target(tgt_a)

    quote_v1 = "Annual fee is INR 15,000."
    quote_v2 = "Annual fee is INR 16,000."
    html_v1 = f"<html><body><main><p>{quote_v1}</p></main></body></html>"
    html_v2 = f"<html><body><main><p>{quote_v2}</p></main></body></html>"

    transports = {
        tgt_a.target_id: RetainedCaptureTransport(
            [
                _firecrawl_envelope(tgt_a.canonical_url, html_v1),
                _firecrawl_envelope(tgt_a.canonical_url, html_v1),  # 2nd run: unchanged
                _firecrawl_envelope(tgt_a.canonical_url, html_v2),  # 3rd run: changed
            ]
        ),
        tgt_b.target_id: RetainedCaptureTransport(
            _firecrawl_envelope(tgt_b.canonical_url, html_v1)
        ),
    }

    control = DurableAcquisitionControl(
        store,
        limits=AcquisitionControlLimits(
            per_request_credits=1,
            per_run_credits=10,
            per_month_credits=20,
            pricing_version="test-v1",
        ),
    )

    resp_v1 = _scripted_card_response(
        card_id="hdfc-infinia",
        annual_fee_minor=1_500_000,
        raw_fee="INR 15,000",
        quote=quote_v1,
    )
    resp_v2 = _scripted_card_response(
        card_id="hdfc-infinia",
        annual_fee_minor=1_600_000,
        raw_fee="INR 16,000",
        quote=quote_v2,
    )

    # Batch 1 at NOW: stable order selects watch:a-card then watch:b-card.
    service_1 = DurableAcquisitionService(
        store=store,
        artifacts=artifacts,
        control=control,
        transport=lambda target, _policy: transports[target.target_id],
        extraction_config=ExtractionRuntimeConfig(
            mode=ExtractionMode.SCRIPTED_REPLAY,
            responses=(resp_v1,),
        ),
        seeds_dir=SEEDS_DIR,
        default_robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        firecrawl_enabled=True,
        run_id="refresh-1",
        now=lambda: NOW,
    )
    batch_1 = service_1.refresh_due_sync(limit=10, client_event_prefix="refresh-1")
    assert batch_1.selected_target_ids == ("watch:a-card", "watch:b-card")
    assert [item.state for item in batch_1.outcomes] == ["completed", "completed"]
    v1_snapshot_a = batch_1.outcomes[0].snapshot_id
    v1_proposal_a = batch_1.outcomes[0].proposal_ids[0]

    # Record a curator decision on v1_proposal_a to verify history preservation on later changes.
    decision = store.decide_proposal(
        v1_proposal_a,
        reviewer_id="alice",
        status=ReviewDecisionStatus.REJECTED,
        reason="Holding v1 while checking v2 disclosure.",
        expected_version=1,
        client_event_id="decide-v1-a",
    )
    assert decision.status is ReviewDecisionStatus.REJECTED

    # Batch 2 at NOW + 8 days: both due again; watch:a-card is unchanged -> 0 LLM calls.
    t2 = NOW + timedelta(days=8)
    service_2 = DurableAcquisitionService(
        store=store,
        artifacts=artifacts,
        control=control,
        transport=lambda target, _policy: transports[target.target_id],
        extraction_config=ExtractionRuntimeConfig(
            mode=ExtractionMode.SCRIPTED_REPLAY,
            responses=(resp_v1,),
        ),
        seeds_dir=SEEDS_DIR,
        default_robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        firecrawl_enabled=True,
        run_id="refresh-2",
        now=lambda: t2,
    )
    batch_2 = service_2.refresh_due_sync(limit=1, client_event_prefix="refresh-2")
    assert batch_2.selected_target_ids == ("watch:a-card",)
    assert batch_2.outcomes[0].state == "unchanged"
    assert batch_2.outcomes[0].llm_calls == 0
    assert batch_2.outcomes[0].proposal_ids == ()

    # Batch 3 at NOW + 16 days: watch:a-card returns changed v2 content -> new snapshot & proposal,
    # while preserving v1 snapshot and v1 decision.
    t3 = NOW + timedelta(days=16)
    service_3 = DurableAcquisitionService(
        store=store,
        artifacts=artifacts,
        control=control,
        transport=lambda target, _policy: transports[target.target_id],
        extraction_config=ExtractionRuntimeConfig(
            mode=ExtractionMode.SCRIPTED_REPLAY,
            responses=(resp_v2,),
        ),
        seeds_dir=SEEDS_DIR,
        default_robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        firecrawl_enabled=True,
        run_id="refresh-3",
        now=lambda: t3,
    )
    batch_3 = service_3.refresh_due_sync(limit=1, client_event_prefix="refresh-3")
    assert batch_3.selected_target_ids == ("watch:a-card",)
    assert batch_3.outcomes[0].state == "completed"
    assert batch_3.outcomes[0].llm_calls == 1
    v2_snapshot_a = batch_3.outcomes[0].snapshot_id
    v2_proposal_a = batch_3.outcomes[0].proposal_ids[0]
    assert v2_snapshot_a != v1_snapshot_a
    assert v2_proposal_a != v1_proposal_a
    assert store.get_snapshot(v1_snapshot_a or "") is not None
    assert len(store.list_decisions(v1_proposal_a)) == 1

    # Simulate an interrupted/ambiguous dispatch on watch:b-card and verify refresh-due
    # never automatically retries it once watch:b-card becomes due at day 31.
    t4 = NOW + timedelta(days=31)
    interrupted_req = FetchRequest(
        request_id="acq:watch:b-card:interrupted",
        canonical_url=tgt_b.canonical_url,
        source_policy_id=pol_b.policy_id,
        evidence_kind="official_page",
        page_class=PageKind.CARD_PAGE,
        max_bytes=2_000_000,
        max_pages=5,
        timeout_seconds=20,
        forced_freshness=False,
        run_id="refresh-interrupted",
    )
    claim = control.claim(
        interrupted_req,
        policy_hash="hash-b",
        estimated_credits=1,
        now=t4,
    )
    assert claim.state == "dispatch"
    control.mark_dispatch_started(interrupted_req.request_id, now=t4)
    control.recover_interrupted(now=t4 + timedelta(seconds=5))

    b_calls_before = len(transports[tgt_b.target_id].calls)
    t5 = t4 + timedelta(minutes=5)
    service_4 = DurableAcquisitionService(
        store=store,
        artifacts=artifacts,
        control=control,
        transport=lambda target, _policy: transports[target.target_id],
        extraction_config=ExtractionRuntimeConfig(mode=ExtractionMode.DISABLED),
        seeds_dir=SEEDS_DIR,
        default_robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        firecrawl_enabled=True,
        run_id="refresh-4",
        now=lambda: t5,
    )
    batch_4 = service_4.refresh_due_sync(limit=2, client_event_prefix="refresh-4")
    assert batch_4.selected_target_ids == ("watch:a-card", "watch:b-card")
    assert batch_4.outcomes[1].target_id == "watch:b-card"
    assert batch_4.outcomes[1].state == "needs_reconciliation"
    assert batch_4.outcomes[1].operator_outcome == "possibly_dispatched_ambiguous"
    assert len(transports[tgt_b.target_id].calls) == b_calls_before


def test_cli_acquire_review_queue_inspect_and_refresh_due_across_processes(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "cli_data"
    inputs = tmp_path / "inputs"
    inputs.mkdir()

    policy_yaml = inputs / "policy.yaml"
    policy_yaml.write_text(
        "- policy_id: synth-auto-issuer\n"
        "  name: Synthetic Automated Issuer\n"
        "  owner: fixture\n"
        "  domain: issuer.example\n"
        "  source_url: https://issuer.example/cards/infinia\n"
        "  terms_url: https://issuer.example/terms\n"
        "  terms_read_on: 2026-11-01\n"
        "  automated_access_permitted: true\n"
        "  manual_only: false\n"
        "  allowed_page_classes: [card_page, offer_page]\n"
        "  minimum_delay_seconds: 10\n"
        "  reviewed_on: 2026-11-01\n"
        "  reviewed_by: alice\n",
        encoding="utf-8",
    )
    watchlist_yaml = inputs / "watchlist.yaml"
    watchlist_yaml.write_text(
        "- target_id: watch-infinia-auto\n"
        "  url: https://issuer.example/cards/infinia\n"
        "  kind: card_page\n"
        "  target: [hdfc-infinia]\n"
        "  source_policy_id: synth-auto-issuer\n"
        "  check_frequency_days: 30\n"
        "  backend: firecrawl\n"
        "  manual_only: false\n",
        encoding="utf-8",
    )
    quote = "The annual membership fee is INR 15,000 per year."
    capture_json = inputs / "retained_firecrawl.json"
    capture_json.write_text(
        json.dumps(
            _firecrawl_envelope(
                "https://issuer.example/cards/infinia",
                f"<html><body><main><p>{quote}</p></main></body></html>",
            )
        ),
        encoding="utf-8",
    )
    extraction_json = inputs / "scripted_extraction.json"
    extraction_json.write_text(
        json.dumps(
            _scripted_card_response(
                card_id="hdfc-infinia",
                annual_fee_minor=1_500_000,
                raw_fee="INR 15,000",
                quote=quote,
            )
        ),
        encoding="utf-8",
    )

    # 1. check-config with --allow-firecrawl in Process 1
    chk = _cli(
        [
            "check-config",
            "--source-policies",
            str(policy_yaml),
            "--watchlist",
            str(watchlist_yaml),
            "--allow-firecrawl",
        ]
    )
    assert chk.returncode == 0, chk.stderr

    # 2. acquire in Process 2
    acq = _cli(
        [
            "acquire",
            "--data-dir",
            str(data_dir),
            "--source-policy",
            str(policy_yaml),
            "--watch-target",
            str(watchlist_yaml),
            "--retained-capture",
            str(capture_json),
            "--extraction-mode",
            "scripted_replay",
            "--scripted-extraction",
            str(extraction_json),
            "--client-event-id",
            "cli-acquire-0001",
        ]
    )
    assert acq.returncode == 0, acq.stderr
    acq_out = json.loads(acq.stdout)
    assert acq_out["state"] == "completed"
    assert acq_out["evidence_fidelity"] == "provider_rendered_html"
    assert acq_out["provider_envelope_sha256"] is not None
    assert acq_out["llm_calls"] == 1
    proposal_id = acq_out["proposal_ids"][0]

    # 3. review-queue in Process 3
    queue = _cli(["review-queue", "--data-dir", str(data_dir), "--format", "json"])
    assert queue.returncode == 0, queue.stderr
    queue_items = json.loads(queue.stdout)
    assert [item["proposal_id"] for item in queue_items] == [proposal_id]

    # 4. inspect in Process 4
    inspected = _cli(["inspect", "--data-dir", str(data_dir), "--proposal-id", proposal_id])
    assert inspected.returncode == 0, inspected.stderr
    inspected_out = json.loads(inspected.stdout)
    assert all(e["verified"] for e in inspected_out["evidence"])

    # 5. Replay same acquire event in Process 5 WITHOUT --retained-capture (proving SQLite replay)
    replay = _cli(
        [
            "acquire",
            "--data-dir",
            str(data_dir),
            "--target-id",
            "watch-infinia-auto",
            "--extraction-mode",
            "scripted_replay",
            "--scripted-extraction",
            str(extraction_json),
            "--client-event-id",
            "cli-acquire-0001",
        ]
    )
    assert replay.returncode == 0, replay.stderr
    replay_out = json.loads(replay.stdout)
    assert replay_out["state"] == "completed"
    assert replay_out["replayed_fetch"] is True
    assert replay_out["llm_calls"] == 0
    assert replay_out["proposal_ids"] == [proposal_id]

    # 6. Immediate second acquire on the same domain with a new client-event-id is blocked
    # by the 10-second source-domain minimum delay across processes.
    delayed = _cli(
        [
            "acquire",
            "--data-dir",
            str(data_dir),
            "--target-id",
            "watch-infinia-auto",
            "--retained-capture",
            str(capture_json),
            "--extraction-mode",
            "scripted_replay",
            "--scripted-extraction",
            str(extraction_json),
            "--client-event-id",
            "cli-acquire-0002",
        ]
    )
    assert delayed.returncode == 2
    delayed_out = json.loads(delayed.stdout)
    assert delayed_out["state"] == "blocked"
    assert delayed_out["operator_outcome"] == "blocked_by_budget_or_delay"
    assert "minimum delay" in delayed_out["diagnostic"]

    # 7. refresh-due in Process 7 (target is no longer due after successful completion)
    refresh = _cli(
        [
            "refresh-due",
            "--data-dir",
            str(data_dir),
            "--limit",
            "5",
            "--client-event-prefix",
            "cli-refresh-0001",
        ]
    )
    assert refresh.returncode == 0, refresh.stderr
    refresh_out = json.loads(refresh.stdout)
    assert refresh_out["selected_target_ids"] == []


def test_review_regressions_replay_after_newer_snapshot_conflict_and_credit_floor(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "data" / "ingestion.sqlite"
    artifacts_dir = tmp_path / "data" / "artifacts"
    store = FinancialIngestionStore(db_path, now=lambda: NOW)
    artifacts = ContentAddressedStore(artifacts_dir)

    pol = _policy(delay_seconds=10)
    tgt = _target()
    store.put_source_policy(pol)
    store.put_watch_target(tgt)

    quote_v1 = "Annual membership fee is INR 15,000."
    quote_v2 = "Annual membership fee is INR 16,000."
    html_v1 = f"<html><body><main><p>{quote_v1}</p></main></body></html>"
    html_v2 = f"<html><body><main><p>{quote_v2}</p></main></body></html>"

    # 1. Pre-claim blocked calls (e.g. firecrawl_enabled=False) at different timestamps
    # do not collide in fetch_attempts and do not block a subsequent enabled run.
    control = DurableAcquisitionControl(
        store,
        limits=AcquisitionControlLimits(
            per_request_credits=1,
            per_run_credits=5,
            per_month_credits=10,
            pricing_version="test-v1",
        ),
    )
    disabled_1 = DurableAcquisitionService(
        store=store,
        artifacts=artifacts,
        control=control,
        transport=RetainedCaptureTransport(_firecrawl_envelope(tgt.canonical_url, html_v1)),
        extraction_config=ExtractionRuntimeConfig(mode=ExtractionMode.DISABLED),
        seeds_dir=SEEDS_DIR,
        default_robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        firecrawl_enabled=False,
        now=lambda: NOW,
    ).acquire_sync(tgt.target_id, client_event_id="evt-v1")
    assert disabled_1.state == "blocked"

    disabled_2 = DurableAcquisitionService(
        store=store,
        artifacts=artifacts,
        control=control,
        transport=RetainedCaptureTransport(_firecrawl_envelope(tgt.canonical_url, html_v1)),
        extraction_config=ExtractionRuntimeConfig(mode=ExtractionMode.DISABLED),
        seeds_dir=SEEDS_DIR,
        default_robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        firecrawl_enabled=False,
        now=lambda: NOW + timedelta(seconds=5),
    ).acquire_sync(tgt.target_id, client_event_id="evt-v1")
    assert disabled_2.state == "blocked"

    # 2. Enabled run with credits_cost=0 in provider metadata still settles estimated_credits=1.
    resp_v1 = _scripted_card_response(
        card_id="hdfc-infinia",
        annual_fee_minor=1_500_000,
        raw_fee="INR 15,000",
        quote=quote_v1,
    )
    resp_v2 = _scripted_card_response(
        card_id="hdfc-infinia",
        annual_fee_minor=1_600_000,
        raw_fee="INR 16,000",
        quote=quote_v2,
    )
    service_v1 = DurableAcquisitionService(
        store=store,
        artifacts=artifacts,
        control=control,
        transport=RetainedCaptureTransport(
            _firecrawl_envelope(tgt.canonical_url, html_v1, credits_cost=0)
        ),
        extraction_config=ExtractionRuntimeConfig(
            mode=ExtractionMode.SCRIPTED_REPLAY,
            responses=(resp_v1,),
        ),
        seeds_dir=SEEDS_DIR,
        default_robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        firecrawl_enabled=True,
        run_id="run-a",
        now=lambda: NOW + timedelta(seconds=10),
    )
    out_v1 = service_v1.acquire_sync(tgt.target_id, client_event_id="evt-v1")
    assert out_v1.state == "completed"
    status_v1 = control.status(out_v1.request_id)
    assert status_v1 is not None and status_v1.charged_credits == 1

    # 3. Conflicting replay (same client_event_id, different forced_freshness) returns
    # a typed failed record without raising ConflictingWriteError.
    conflict_out = DurableAcquisitionService(
        store=store,
        artifacts=artifacts,
        control=control,
        transport=RetainedCaptureTransport(_firecrawl_envelope(tgt.canonical_url, html_v1)),
        extraction_config=ExtractionRuntimeConfig(mode=ExtractionMode.DISABLED),
        seeds_dir=SEEDS_DIR,
        default_robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        firecrawl_enabled=True,
        forced_freshness=True,
        run_id="run-a",
        now=lambda: NOW + timedelta(seconds=30),
    ).acquire_sync(tgt.target_id, client_event_id="evt-v1")
    assert conflict_out.state == "failed"
    assert conflict_out.replayed_fetch is False
    assert "already used for different acquisition inputs" in (conflict_out.diagnostic or "")

    # 4. Capture a newer snapshot (v2), then replay evt-v1 under a different run_id ("run-b")
    # and verify evt-v1 still replays its original snapshot and proposal cleanly.
    out_v2 = DurableAcquisitionService(
        store=store,
        artifacts=artifacts,
        control=control,
        transport=RetainedCaptureTransport(_firecrawl_envelope(tgt.canonical_url, html_v2)),
        extraction_config=ExtractionRuntimeConfig(
            mode=ExtractionMode.SCRIPTED_REPLAY,
            responses=(resp_v2,),
        ),
        seeds_dir=SEEDS_DIR,
        default_robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        firecrawl_enabled=True,
        run_id="run-b",
        now=lambda: NOW + timedelta(seconds=40),
    ).acquire_sync(tgt.target_id, client_event_id="evt-v2")
    assert out_v2.state == "completed"
    assert out_v2.snapshot_id != out_v1.snapshot_id

    replay_v1 = DurableAcquisitionService(
        store=store,
        artifacts=artifacts,
        control=control,
        transport=RetainedCaptureTransport(_firecrawl_envelope(tgt.canonical_url, html_v1)),
        extraction_config=ExtractionRuntimeConfig(
            mode=ExtractionMode.SCRIPTED_REPLAY,
            responses=(resp_v1,),
        ),
        seeds_dir=SEEDS_DIR,
        default_robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        firecrawl_enabled=True,
        run_id="run-c",
        now=lambda: NOW + timedelta(seconds=50),
    ).acquire_sync(tgt.target_id, client_event_id="evt-v1")
    assert replay_v1.state == "completed"
    assert replay_v1.replayed_fetch is True
    assert replay_v1.snapshot_id == out_v1.snapshot_id
    assert replay_v1.proposal_ids == out_v1.proposal_ids
    assert replay_v1.llm_calls == 0

    # 5. Unresolved dispatch on a URL takes precedence over domain-delay blocking in claim().
    in_flight_req = FetchRequest(
        request_id="acq:in-flight",
        canonical_url=tgt.canonical_url,
        source_policy_id=pol.policy_id,
        evidence_kind="official_page",
        page_class=PageKind.CARD_PAGE,
        max_bytes=2_000_000,
        max_pages=5,
        timeout_seconds=20,
        forced_freshness=False,
        run_id="run-d",
    )
    claim_in_flight = control.claim(
        in_flight_req,
        policy_hash="hash-1",
        estimated_credits=1,
        now=NOW + timedelta(seconds=60),
    )
    assert claim_in_flight.state == "dispatch"
    follow_up_req = in_flight_req.model_copy(update={"request_id": "acq:follow-up"})
    claim_follow_up = control.claim(
        follow_up_req,
        policy_hash="hash-1",
        estimated_credits=1,
        now=NOW + timedelta(seconds=61),
    )
    assert claim_follow_up.state == "pending"
    assert control.status("acq:follow-up") is None

