"""Controlled, offline retained-capture demonstration for Firecrawl ingestion.

This is intentionally not an operator acquisition command.  It proves the D
owner boundary after a provider result has been retained: immutable snapshot,
FI2 extraction, pending proposal, restart and idempotent replay.  The document
is project-controlled synthetic content; no Firecrawl or model request occurs.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from core.models import Card
from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import (
    FetchAttempt,
    FetchResult,
    PageKind,
    SourcePolicyRecord,
    WatchTarget,
)
from ingestion.extraction_runtime import (
    ExtractionMode,
    ExtractionRuntimeConfig,
    FinancialExtractionRuntime,
)
from ingestion.snapshots import SnapshotService
from ingestion.storage import FinancialIngestionStore

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
TARGET_ID = "watch:controlled-firecrawl-card"
CARD_ID = "controlled-firecrawl-card"


def _card() -> Card:
    return Card.model_validate(
        {
            "id": CARD_ID,
            "issuer": "Controlled Example Bank",
            "network": "visa",
            "country": "IN",
            "name": "Controlled Firecrawl Card",
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


def _result(artifacts: ContentAddressedStore, text: str, request_id: str) -> FetchResult:
    raw = artifacts.put(f"<p>{text}</p>".encode(), media_type="text/html")
    normalized = artifacts.put(text.encode(), media_type="text/plain")
    return FetchResult(
        request_id=request_id,
        final_url="https://issuer.example/controlled-card",
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
        final_url="https://issuer.example/controlled-card",
        response_class="success",
        retry_index=0,
    )


def run_demo(data_dir: Path) -> dict[str, Any]:
    """Run the deterministic retained-capture portion of the operator workflow."""

    store = FinancialIngestionStore(data_dir / "ingestion.sqlite", now=lambda: NOW)
    artifacts = ContentAddressedStore(data_dir / "artifacts")
    policy = SourcePolicyRecord(
        policy_id="controlled-example-policy",
        name="Controlled demonstration policy",
        owner="TripWise test fixture",
        domain="issuer.example",
        source_url="https://issuer.example/controlled-card",
        terms_url="https://issuer.example/terms",
        terms_read_on=date(2026, 11, 1),
        automated_access_permitted=True,
        manual_only=False,
        allowed_page_classes=("card_page",),
        reviewed_on=date(2026, 11, 1),
        reviewed_by="demo-curator",
    )
    store.put_source_policy(policy)
    store.put_watch_target(
        WatchTarget(
            target_id=TARGET_ID,
            canonical_url="https://issuer.example/controlled-card",
            source_policy_id=policy.policy_id,
            target_fact_ids=(CARD_ID,),
            page_kind=PageKind.CARD_PAGE,
            check_frequency_days=30,
            preferred_backend="firecrawl",
        )
    )
    snapshots = SnapshotService(store=store, artifacts=artifacts, now=lambda: NOW)
    before = snapshots.capture(
        target_id=TARGET_ID,
        result=_result(artifacts, "Annual fee is INR 10,000.", "demo-before"),
        attempt=_attempt("demo-before"),
    )
    after = snapshots.capture(
        target_id=TARGET_ID,
        result=_result(artifacts, "Annual fee is INR 12,500.", "demo-after"),
        attempt=_attempt("demo-after"),
    )
    assert before is not None and after is not None
    row = _card().model_dump(mode="json")
    proposal_row = dict(row)
    proposal_row["annual_fee_minor"] = 1_250_000
    response = {
        "target_table": "cards",
        "target_id": CARD_ID,
        "proposed_row": proposal_row,
        "fields": [
            {
                "field_path": "annual_fee_minor",
                "proposed_raw_value": "INR 12,500",
                "evidence_spans": [
                    {
                        "snapshot_id": after.snapshot_id,
                        "snapshot_hash": after.normalized_sha256,
                        "quote": after.canonical_markdown,
                        "normalized_start": 0,
                        "normalized_end": len(after.canonical_markdown),
                        "field_path": "annual_fee_minor",
                        "verification": "exact",
                    }
                ],
            }
        ],
        "change_summary": "Controlled document changed the annual fee.",
        "extractor_confidence": 0.8,
    }
    config = ExtractionRuntimeConfig(
        mode=ExtractionMode.SCRIPTED_REPLAY,
        responses=(response,),
        extractor_version="firecrawl-controlled-demo-v1",
    )
    first = FinancialExtractionRuntime(
        config=config, store=store, artifacts=artifacts, now=lambda: NOW
    ).extract_snapshot(
        target_table="cards",
        target_id=CARD_ID,
        current_row=row,
        current_row_hash=None,
        snapshot=after,
        previous_snapshot=before,
        client_event_id="controlled-firecrawl-demo-v1",
    )
    reopened = FinancialIngestionStore(data_dir / "ingestion.sqlite", now=lambda: NOW)
    replay = FinancialExtractionRuntime(
        config=config, store=reopened, artifacts=artifacts, now=lambda: NOW
    ).extract_snapshot(
        target_table="cards",
        target_id=CARD_ID,
        current_row=row,
        current_row_hash=None,
        snapshot=after,
        previous_snapshot=before,
        client_event_id="controlled-firecrawl-demo-v1",
    )
    return {
        "mode": "controlled retained-capture replay (not live Firecrawl or issuer evidence)",
        "snapshot_id": after.snapshot_id,
        "snapshot_sha256": after.normalized_sha256,
        "changed": first.diff.changed,
        "first_status": first.outcome.status,
        "first_calls": first.outcome.calls,
        "proposal_id": (
            None if first.outcome.proposal is None else first.outcome.proposal.proposal_id
        ),
        "reopen_status": replay.outcome.status,
        "reopen_calls": replay.outcome.calls,
        "review_queue_status": (
            None if replay.outcome.proposal is None else replay.outcome.proposal.status.value
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_demo(args.data_dir), sort_keys=True))


if __name__ == "__main__":
    main()
