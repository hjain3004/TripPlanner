"""Offline acceptance for retained Firecrawl-shaped evidence and FI2 extraction."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from core.models import Card
from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import (
    FetchAttempt,
    FetchResult,
    PageKind,
    SnapshotBundle,
    SourcePolicyRecord,
    WatchTarget,
)
from ingestion.extraction_runtime import (
    ExtractionMode,
    ExtractionRuntimeConfig,
    ExtractionRuntimeError,
    FinancialExtractionRuntime,
)
from ingestion.snapshots import SnapshotService
from ingestion.storage import FinancialIngestionStore

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def _policy() -> SourcePolicyRecord:
    return SourcePolicyRecord(
        policy_id="issuer-example",
        name="Controlled issuer fixture",
        owner="Example Bank",
        domain="issuer.example",
        source_url="https://issuer.example/card",
        terms_url="https://issuer.example/terms",
        terms_read_on=date(2026, 11, 1),
        automated_access_permitted=True,
        manual_only=False,
        allowed_page_classes=("card_page",),
        reviewed_on=date(2026, 11, 1),
        reviewed_by="test-curator",
    )


def _card() -> Card:
    return Card.model_validate(
        {
            "id": "example-card",
            "issuer": "Example Bank",
            "network": "visa",
            "country": "IN",
            "name": "Example Card",
            "annual_fee_minor": 1_000_000,
            "fee_currency": "INR",
            "forex_markup_bp": 200,
            "forex_markup_tax_bp": 1800,
            "base_earn": {"points": 3, "per_amount_minor": 15000, "currency": "INR"},
            "provenance": {
                "source_type": "crawl_draft",
                "last_verified": "2026-11-01",
                "verified_by": "UNVERIFIED",
                "needs_verification": True,
                "confidence": 0.5,
            },
        }
    )


def _fetch_result(artifacts: ContentAddressedStore, text: str, request_id: str) -> FetchResult:
    # A retained controlled capture shaped like the Firecrawl boundary, not a live issuer claim.
    raw = artifacts.put(f"<p>{text}</p>".encode(), media_type="text/html")
    normalized = artifacts.put(text.encode(), media_type="text/plain")
    return FetchResult(
        request_id=request_id,
        final_url="https://issuer.example/card",
        content_type="text/html",
        raw_artifact=raw,
        normalized_artifact=normalized,
        normalized_text=text,
        engine="firecrawl-controlled-replay",
        engine_version="fixture-v1",
        duration_ms=1,
    )


def _attempt(request_id: str) -> FetchAttempt:
    return FetchAttempt(
        attempt_id=f"attempt:{request_id}",
        request_id=request_id,
        backend="firecrawl",
        backend_version="fixture-v1",
        started_at=NOW,
        ended_at=NOW,
        final_url="https://issuer.example/card",
        response_class="success",
        retry_index=0,
    )


def _response(
    snapshot_id: str,
    snapshot_hash: str,
    quote: str,
    row: dict[str, object],
) -> dict[str, object]:
    return {
        "target_table": "cards",
        "target_id": "example-card",
        "proposed_row": row,
        "fields": [
            {
                "field_path": "annual_fee_minor",
                "proposed_raw_value": "INR 12,500",
                "evidence_spans": [
                    {
                        "snapshot_id": snapshot_id,
                        "snapshot_hash": snapshot_hash,
                        "quote": quote,
                        "normalized_start": 0,
                        "normalized_end": len(quote),
                        "field_path": "annual_fee_minor",
                        "verification": "exact",
                    }
                ],
            }
        ],
        "change_summary": "Controlled document changes the annual fee.",
        "extractor_confidence": 0.8,
    }


def _setup(
    tmp_path: Path,
) -> tuple[FinancialIngestionStore, ContentAddressedStore, SnapshotBundle, SnapshotBundle]:
    store = FinancialIngestionStore(tmp_path / "ingestion.sqlite", now=lambda: NOW)
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    store.put_source_policy(_policy())
    store.put_watch_target(
        WatchTarget(
            target_id="watch:example-card",
            canonical_url="https://issuer.example/card",
            source_policy_id="issuer-example",
            target_fact_ids=("example-card",),
            page_kind=PageKind.CARD_PAGE,
            check_frequency_days=30,
            preferred_backend="firecrawl",
        )
    )
    snapshots = SnapshotService(store=store, artifacts=artifacts, now=lambda: NOW)
    original = snapshots.capture(
        target_id="watch:example-card",
        result=_fetch_result(artifacts, "Annual fee is INR 10,000.", "old"),
        attempt=_attempt("old"),
    )
    changed = snapshots.capture(
        target_id="watch:example-card",
        result=_fetch_result(artifacts, "Annual fee is INR 12,500.", "new"),
        attempt=_attempt("new"),
    )
    assert original is not None and changed is not None
    return store, artifacts, original, changed


def test_retained_firecrawl_capture_becomes_pending_proposal_and_replays_after_reopen(
    tmp_path: Path,
) -> None:
    store, artifacts, original, changed = _setup(tmp_path)
    row = _card().model_dump(mode="json")
    proposed = dict(row)
    proposed["annual_fee_minor"] = 1_250_000
    runtime = FinancialExtractionRuntime(
        config=ExtractionRuntimeConfig(
            mode=ExtractionMode.SCRIPTED_REPLAY,
            responses=(
                _response(
                    changed.snapshot_id,
                    changed.normalized_sha256,
                    changed.canonical_markdown,
                    proposed,
                ),
            ),
        ),
        store=store,
        artifacts=artifacts,
        now=lambda: NOW,
    )

    first = runtime.extract_snapshot(
        target_table="cards",
        target_id="example-card",
        current_row=row,
        current_row_hash=None,
        snapshot=changed,
        previous_snapshot=original,
        client_event_id="controlled-firecrawl-event",
    )

    assert first.mode is ExtractionMode.SCRIPTED_REPLAY
    assert first.diff.changed
    assert first.outcome.status == "proposal_pending"
    assert first.outcome.calls == 1
    assert first.outcome.proposal is not None
    assert first.outcome.proposal.lineage_ids == (changed.snapshot_id,)

    reopened = FinancialIngestionStore(tmp_path / "ingestion.sqlite", now=lambda: NOW)
    replay = FinancialExtractionRuntime(
        config=ExtractionRuntimeConfig(
            mode=ExtractionMode.SCRIPTED_REPLAY,
            responses=(
                _response(
                    changed.snapshot_id,
                    changed.normalized_sha256,
                    changed.canonical_markdown,
                    proposed,
                ),
            ),
        ),
        store=reopened,
        artifacts=artifacts,
        now=lambda: NOW,
    ).extract_snapshot(
        target_table="cards",
        target_id="example-card",
        current_row=row,
        current_row_hash=None,
        snapshot=changed,
        previous_snapshot=original,
        client_event_id="controlled-firecrawl-event",
    )
    assert replay.outcome.status == "proposal_pending"
    assert replay.outcome.calls == 0
    assert replay.outcome.proposal == first.outcome.proposal


def test_unchanged_capture_and_disabled_mode_make_zero_model_calls(tmp_path: Path) -> None:
    store, artifacts, original, _changed = _setup(tmp_path)
    row = _card().model_dump(mode="json")
    unchanged = FinancialExtractionRuntime(
        config=ExtractionRuntimeConfig(
            mode=ExtractionMode.SCRIPTED_REPLAY,
            responses=({"not": "used"},),
        ),
        store=store,
        artifacts=artifacts,
        now=lambda: NOW,
    ).extract_snapshot(
        target_table="cards",
        target_id="example-card",
        current_row=row,
        current_row_hash=None,
        snapshot=original,
        previous_snapshot=original,
        client_event_id="unchanged-event",
    )
    assert unchanged.outcome.status == "unchanged"
    assert unchanged.outcome.calls == 0

    disabled = FinancialExtractionRuntime(
        config=ExtractionRuntimeConfig(mode=ExtractionMode.DISABLED),
        store=store,
        artifacts=artifacts,
        now=lambda: NOW,
    ).extract_snapshot(
        target_table="cards",
        target_id="example-card",
        current_row=row,
        current_row_hash=None,
        snapshot=original,
        previous_snapshot=None,
        client_event_id="disabled-event",
    )
    assert disabled.outcome.status == "extraction_failed"
    assert disabled.outcome.calls == 0
    assert disabled.outcome.diagnostic == "financial extraction is explicitly disabled"


def test_invalid_script_has_one_semantic_invocation_and_no_fallback(tmp_path: Path) -> None:
    store, artifacts, original, changed = _setup(tmp_path)
    row = _card().model_dump(mode="json")
    outcome = FinancialExtractionRuntime(
        config=ExtractionRuntimeConfig(
            mode=ExtractionMode.SCRIPTED_REPLAY,
            responses=({"malformed": True}, {"would": "be a hidden retry"}),
        ),
        store=store,
        artifacts=artifacts,
        now=lambda: NOW,
    ).extract_snapshot(
        target_table="cards",
        target_id="example-card",
        current_row=row,
        current_row_hash=None,
        snapshot=changed,
        previous_snapshot=original,
        client_event_id="invalid-event",
    )
    assert outcome.outcome.status == "invalid_response"
    assert outcome.outcome.calls == 1
    assert outcome.outcome.proposal is None


def test_mode_configurations_cannot_hide_a_live_or_ambiguous_client() -> None:
    with pytest.raises(ExtractionRuntimeError, match="explicit scripted response"):
        ExtractionRuntimeConfig(mode=ExtractionMode.SCRIPTED_REPLAY)
    with pytest.raises(ExtractionRuntimeError, match="requires an injected client"):
        ExtractionRuntimeConfig(mode=ExtractionMode.AUTHORIZED_CLIENT)


def test_real_pdf_document_parsed_through_isolated_worker_produces_verified_evidence(
    tmp_path: Path,
) -> None:
    from evals.test_pdf_real_library_compatibility import build_pdf
    from ingestion.canonical import canonicalize_content
    from ingestion.contracts import EvidenceSpan
    from ingestion.evidence import verify_evidence_span

    store = FinancialIngestionStore(tmp_path / "ingestion.sqlite", now=lambda: NOW)
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    policy = SourcePolicyRecord(
        policy_id="issuer-pdf-policy",
        name="PDF demonstration policy",
        owner="TripWise test fixture",
        domain="issuer.example",
        source_url="https://issuer.example/terms.pdf",
        terms_url="https://issuer.example/terms",
        terms_read_on=date(2026, 11, 1),
        automated_access_permitted=True,
        manual_only=False,
        allowed_page_classes=("tnc_pdf",),
        reviewed_on=date(2026, 11, 1),
        reviewed_by="test-curator",
    )
    store.put_source_policy(policy)
    store.put_watch_target(
        WatchTarget(
            target_id="watch:example-pdf",
            canonical_url="https://issuer.example/terms.pdf",
            source_policy_id=policy.policy_id,
            target_fact_ids=("example-card",),
            page_kind=PageKind.TNC_PDF,
            check_frequency_days=30,
            preferred_backend="firecrawl",
        )
    )

    pdf_bytes = build_pdf(
        [
            ["Axis Bank ATLAS Terms and Conditions", "Section 1: General Product Information"],
            ["Section 2: Charges and Fees", "Forex markup fee of 350 basis points applies."],
        ]
    )
    canonical_text = canonicalize_content(
        pdf_bytes, media_type="application/pdf", max_chars=100000, max_pages=10
    )
    raw_art = artifacts.put(pdf_bytes, media_type="application/pdf")
    norm_art = artifacts.put(canonical_text.encode("utf-8"), media_type="text/plain")

    snapshots = SnapshotService(store=store, artifacts=artifacts, now=lambda: NOW)
    snapshot = snapshots.capture(
        target_id="watch:example-pdf",
        result=FetchResult(
            request_id="req-pdf-test",
            final_url="https://issuer.example/terms.pdf",
            content_type="application/pdf",
            raw_artifact=raw_art,
            normalized_artifact=norm_art,
            normalized_text=canonical_text,
            engine="firecrawl-controlled-replay",
            engine_version="fixture-v1",
            duration_ms=1,
        ),
        attempt=_attempt("req-pdf-test"),
    )
    assert snapshot is not None

    quote = "Forex markup fee of 350 basis points applies."
    quote_start = canonical_text.find(quote)
    assert quote_start != -1

    span = EvidenceSpan(
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.normalized_sha256,
        quote=quote,
        normalized_start=quote_start,
        normalized_end=quote_start + len(quote),
        field_path="forex_markup_bp",
        verification="exact",
        artifact_kind="pdf",
        page_number=2,
    )
    # verify_evidence_span exercises the real isolated worker subprocess
    verify_evidence_span(span, snapshot=snapshot, artifacts=artifacts)


def test_curator_authored_extraction_mode_labels_outcome_and_proposal(tmp_path: Path) -> None:
    store, artifacts, original, changed = _setup(tmp_path)
    row = _card().model_dump(mode="json")
    proposed = dict(row)
    proposed["annual_fee_minor"] = 1_250_000

    runtime = FinancialExtractionRuntime(
        config=ExtractionRuntimeConfig(
            mode=ExtractionMode.CURATOR_AUTHORED,
            responses=(
                _response(
                    changed.snapshot_id,
                    changed.normalized_sha256,
                    changed.canonical_markdown,
                    proposed,
                ),
            ),
            extractor_version="curator-authored-v1",
        ),
        store=store,
        artifacts=artifacts,
        now=lambda: NOW,
    )

    outcome = runtime.extract_snapshot(
        target_table="cards",
        target_id="example-card",
        current_row=row,
        current_row_hash=None,
        snapshot=changed,
        previous_snapshot=original,
        client_event_id="curator-authored-event-1",
    )
    assert outcome.mode is ExtractionMode.CURATOR_AUTHORED
    assert outcome.outcome.status == "proposal_pending"
    assert outcome.outcome.proposal is not None
    assert outcome.outcome.proposal.extractor_version == "curator-authored-v1"


def test_one_attempt_client_blocks_multiple_calls_and_non_extractor_nodes() -> None:
    from agents.llm import LLMCallError, ScriptedLLMClient
    from ingestion.extraction_runtime import _OneAttemptClient

    scripted = ScriptedLLMClient({"financial_extractor": [{"foo": "bar"}]})
    client = _OneAttemptClient(scripted)

    # 1. Non-extractor node is rejected immediately
    with pytest.raises(LLMCallError, match="permits only financial_extractor"):
        client.complete_json(node="explainer", system="", user="", schema=dict)

    # 2. First semantic call succeeds
    res = client.complete_json(node="financial_extractor", system="", user="", schema=dict)
    assert res == {"foo": "bar"}

    # 3. Second call is blocked fail-closed
    with pytest.raises(LLMCallError, match="allows one semantic invocation"):
        client.complete_json(node="financial_extractor", system="", user="", schema=dict)

