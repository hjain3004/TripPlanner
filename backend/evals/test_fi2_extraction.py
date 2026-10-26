from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from agents.llm import LLMCallError, RecordingLLMClient, ReplayLLMClient, ScriptedLLMClient
from core.models import Card
from gateway.evidence.invariants import check_invariants
from gateway.evidence.store import SqliteEvidenceStore
from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import (
    ImmutableArtifactRef,
    SnapshotBundle,
    SourcePolicyRecord,
    WatchTarget,
)
from ingestion.diff import diff_text
from ingestion.evidence import financial_draft_graph
from ingestion.extraction import FinancialExtractor
from ingestion.parsing import (
    UnresolvedValueError,
    parse_basis_points,
    parse_money_minor,
    parse_ratio,
)
from ingestion.storage import FinancialIngestionStore

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
HASH = "a" * 64
NORMALIZED_HASH = "b" * 64


def policy() -> SourcePolicyRecord:
    return SourcePolicyRecord(
        policy_id="issuer-hdfc",
        name="HDFC official",
        owner="HDFC Bank",
        domain="hdfcbank.com",
        source_url="https://www.hdfcbank.com/cards/infinia",
        terms_url="https://www.hdfcbank.com/terms",
        terms_read_on=date(2026, 10, 1),
        automated_access_permitted=True,
        manual_only=False,
        allowed_page_classes=("card_page", "tnc_pdf"),
        reviewed_on=date(2026, 10, 1),
        reviewed_by="curator-1",
    )


def card() -> Card:
    return Card.model_validate(
        {
            "id": "hdfc-infinia",
            "issuer": "HDFC Bank",
            "network": "visa",
            "country": "IN",
            "name": "Infinia",
            "annual_fee_minor": 1000000,
            "fee_currency": "INR",
            "forex_markup_bp": 200,
            "forex_markup_tax_bp": 1800,
            "base_earn": {"points": 3, "per_amount_minor": 15000, "currency": "INR"},
            "provenance": {
                "source_type": "crawl_draft",
                "last_verified": "2026-10-01",
                "verified_by": "UNVERIFIED",
                "needs_verification": True,
                "confidence": 0.5,
            },
        }
    )


def snapshot(store: FinancialIngestionStore, artifacts: ContentAddressedStore) -> SnapshotBundle:
    store.put_source_policy(policy())
    store.put_watch_target(
        WatchTarget(
            target_id="watch:hdfc",
            canonical_url="https://www.hdfcbank.com/cards/infinia",
            source_policy_id="issuer-hdfc",
            target_fact_ids=("hdfc-infinia",),
            page_kind="card_page",
            check_frequency_days=365,
        )
    )
    raw = artifacts.put(b"<p>Annual fee is INR 12,500.</p>", media_type="text/html")
    normalized = artifacts.put(
        b"Annual fee is INR 12,500.", media_type="text/plain"
    )
    return SnapshotBundle(
        snapshot_id="snapshot:watch:hdfc:1",
        target_id="watch:hdfc",
        captured_at=NOW,
        raw_artifact=raw,
        normalized_artifact=normalized,
        raw_sha256=raw.sha256,
        normalized_sha256=normalized.sha256,
        canonical_markdown="Annual fee is INR 12,500.",
    )


def response(snap: SnapshotBundle, row: dict[str, Any]) -> dict[str, Any]:
    quote = snap.canonical_markdown
    return {
        "target_table": "cards",
        "target_id": "hdfc-infinia",
        "proposed_row": row,
        "fields": [
            {
                "field_path": "annual_fee_minor",
                "proposed_raw_value": "INR 12,500",
                "evidence_spans": [
                    {
                        "snapshot_id": snap.snapshot_id,
                        "snapshot_hash": snap.normalized_sha256,
                        "quote": quote,
                        "normalized_start": 0,
                        "normalized_end": len(quote),
                        "field_path": "annual_fee_minor",
                        "verification": "exact",
                    }
                ],
            }
        ],
        "change_summary": "Issuer page changed the annual fee.",
        "extractor_confidence": 0.8,
    }


def setup(
    tmp_path: Path,
) -> tuple[FinancialIngestionStore, SnapshotBundle, Card, ContentAddressedStore]:
    store = FinancialIngestionStore(tmp_path / "ingestion.sqlite")
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    snap = snapshot(store, artifacts)
    store.put_snapshot(snap)
    return store, snap, card(), artifacts


def test_deterministic_parsers_reject_ambiguous_values() -> None:
    assert parse_money_minor("₹12,500") == 1_250_000
    assert parse_money_minor("INR 12,50,000") == 125_000_000
    assert parse_money_minor("INR 1 250") == 125_000
    assert parse_money_minor("INR 1,234,567.89") == 123_456_789
    assert parse_basis_points("2.00%") == 200
    assert parse_ratio("1:2") == (1, 2)
    with pytest.raises(UnresolvedValueError):
        parse_basis_points("two percent")
    with pytest.raises(UnresolvedValueError):
        parse_money_minor("12,500 / month")
    with pytest.raises(UnresolvedValueError):
        parse_money_minor("INR 1,2")
    with pytest.raises(UnresolvedValueError):
        parse_money_minor("INR 1 2")
    with pytest.raises(UnresolvedValueError):
        parse_money_minor("INR 1,23,45")


def test_malformed_money_notation_cannot_form_a_proposal(tmp_path: Path) -> None:
    store, snap, current, artifacts = setup(tmp_path)
    row = current.model_dump(mode="json")
    row["annual_fee_minor"] = 1_200
    malformed = response(snap, row)
    malformed["fields"][0]["proposed_raw_value"] = "INR 1,2"
    client = ScriptedLLMClient({"financial_extractor": [malformed]})

    outcome = FinancialExtractor(
        client=client, store=store, artifacts=artifacts, now=lambda: NOW
    ).extract(
        target_table="cards",
        target_id=current.id,
        current_row=current.model_dump(mode="json"),
        current_row_hash=None,
        snapshot=snap,
        diff=diff_text("Annual fee is INR 10,000.", snap.canonical_markdown),
        client_event_id="event-malformed-money",
    )

    assert outcome.status == "invalid_response"
    assert outcome.proposal is None


def test_evidence_quote_must_support_the_proposed_value(tmp_path: Path) -> None:
    store, snap, current, artifacts = setup(tmp_path)
    row = current.model_dump(mode="json")
    row["annual_fee_minor"] = 99_900
    unsupported = response(snap, row)
    unsupported["fields"][0]["proposed_raw_value"] = "INR 999"
    client = ScriptedLLMClient({"financial_extractor": [unsupported]})

    outcome = FinancialExtractor(
        client=client, store=store, artifacts=artifacts, now=lambda: NOW
    ).extract(
        target_table="cards",
        target_id=current.id,
        current_row=current.model_dump(mode="json"),
        current_row_hash=None,
        snapshot=snap,
        diff=diff_text("Annual fee is INR 10,000.", snap.canonical_markdown),
        client_event_id="event-unsupported-quote",
    )

    assert outcome.status == "invalid_response"
    assert outcome.proposal is None


def test_invalid_row_sanity_is_blocking(tmp_path: Path) -> None:
    store, snap, current, artifacts = setup(tmp_path)
    current_row = current.model_dump(mode="json")
    current_row["forex_markup_bp"] = 50_000
    current_row["provenance"]["confidence"] = 2.0
    row = dict(current_row)
    row["annual_fee_minor"] = 1_250_000
    client = ScriptedLLMClient({"financial_extractor": [response(snap, row)]})

    outcome = FinancialExtractor(
        client=client, store=store, artifacts=artifacts, now=lambda: NOW
    ).extract(
        target_table="cards",
        target_id=current.id,
        current_row=current_row,
        current_row_hash=None,
        snapshot=snap,
        diff=diff_text("Annual fee is INR 10,000.", snap.canonical_markdown),
        client_event_id="event-invalid-sanity",
    )

    assert outcome.status == "proposal_pending"
    assert outcome.proposal is not None
    assert {finding.code for finding in outcome.proposal.validation_findings} >= {
        "implausible_forex_markup",
        "invalid_confidence",
    }


def test_duplicate_extraction_replays_without_another_model_call(tmp_path: Path) -> None:
    store, snap, current, artifacts = setup(tmp_path)
    row = current.model_dump(mode="json")
    row["annual_fee_minor"] = 1_250_000
    client = ScriptedLLMClient({"financial_extractor": [response(snap, row)]})
    kwargs = dict(
        target_table="cards",
        target_id=current.id,
        current_row=current.model_dump(mode="json"),
        current_row_hash=None,
        snapshot=snap,
        diff=diff_text("Annual fee is INR 10,000.", snap.canonical_markdown),
        client_event_id="event-duplicate",
    )

    first = FinancialExtractor(
        client=client, store=store, artifacts=artifacts, now=lambda: NOW
    ).extract(**kwargs)
    second = FinancialExtractor(
        client=ScriptedLLMClient({}), store=store, artifacts=artifacts, now=lambda: NOW
    ).extract(**kwargs)

    assert first.status == "proposal_pending"
    assert first.calls == 1
    assert second.status == "proposal_pending"
    assert second.calls == 0
    assert second.proposal == first.proposal
    assert client.invocations["financial_extractor"] == 1


def test_changed_snapshot_makes_one_call_and_persists_a_typed_proposal(tmp_path: Path) -> None:
    store, snap, current, artifacts = setup(tmp_path)
    row = current.model_dump(mode="json")
    row["annual_fee_minor"] = 1_250_000
    client = ScriptedLLMClient({"financial_extractor": [response(snap, row)]})
    outcome = FinancialExtractor(
        client=client, store=store, artifacts=artifacts, now=lambda: NOW
    ).extract(
        target_table="cards",
        target_id=current.id,
        current_row=current.model_dump(mode="json"),
        current_row_hash=None,
        snapshot=snap,
        diff=diff_text("Annual fee is INR 10,000.", snap.canonical_markdown),
        client_event_id="event-1",
    )
    assert outcome.status == "proposal_pending"
    assert outcome.calls == 1
    assert client.invocations["financial_extractor"] == 1
    assert outcome.proposal is not None
    assert outcome.proposal.proposed_row["annual_fee_minor"] == 1_250_000
    assert store.get_proposal(outcome.proposal.proposal_id) == outcome.proposal


def test_unchanged_snapshot_makes_zero_calls(tmp_path: Path) -> None:
    store, snap, current, artifacts = setup(tmp_path)
    client = ScriptedLLMClient({})
    outcome = FinancialExtractor(client=client, store=store, artifacts=artifacts).extract(
        target_table="cards",
        target_id=current.id,
        current_row=current.model_dump(mode="json"),
        current_row_hash=None,
        snapshot=snap,
        diff=diff_text(snap.canonical_markdown, snap.canonical_markdown),
        client_event_id="event-unchanged",
    )
    assert outcome.status == "unchanged"
    assert outcome.calls == 0
    assert client.invocations == {}


def test_invalid_evidence_and_arbitrary_field_fail_without_retry(tmp_path: Path) -> None:
    store, snap, current, artifacts = setup(tmp_path)
    row = current.model_dump(mode="json")
    row["annual_fee_minor"] = 1_250_000
    bad = response(snap, row)
    bad["fields"][0]["evidence_spans"][0]["snapshot_hash"] = HASH
    client = ScriptedLLMClient({"financial_extractor": [bad]})
    outcome = FinancialExtractor(client=client, store=store, artifacts=artifacts).extract(
        target_table="cards",
        target_id=current.id,
        current_row=current.model_dump(mode="json"),
        current_row_hash=None,
        snapshot=snap,
        diff=diff_text("old", snap.canonical_markdown),
        client_event_id="event-bad",
    )
    assert outcome.status == "invalid_response"
    assert outcome.calls == 1
    assert client.invocations["financial_extractor"] == 1


def test_validation_rejects_mismatched_field_span_and_unlisted_changes(tmp_path: Path) -> None:
    store, snap, current, artifacts = setup(tmp_path)
    row = current.model_dump(mode="json")
    row["annual_fee_minor"] = 1_250_000
    bad_span = response(snap, row)
    bad_span["fields"][0]["evidence_spans"][0]["field_path"] = "name"
    client = ScriptedLLMClient({"financial_extractor": [bad_span]})
    first = FinancialExtractor(client=client, store=store, artifacts=artifacts).extract(
        target_table="cards",
        target_id=current.id,
        current_row=current.model_dump(mode="json"),
        current_row_hash=None,
        snapshot=snap,
        diff=diff_text("old", snap.canonical_markdown),
        client_event_id="event-span-field",
    )
    assert first.status == "invalid_response"

    row["name"] = "Different identity"
    client = ScriptedLLMClient({"financial_extractor": [response(snap, row)]})
    second = FinancialExtractor(client=client, store=store, artifacts=artifacts).extract(
        target_table="cards",
        target_id=current.id,
        current_row=current.model_dump(mode="json"),
        current_row_hash=None,
        snapshot=snap,
        diff=diff_text("old", snap.canonical_markdown),
        client_event_id="event-unlisted",
    )
    assert second.status == "invalid_response"


def test_validation_rejects_target_identity_drift_and_pdf_downgrade(tmp_path: Path) -> None:
    store, snap, current, artifacts = setup(tmp_path)
    row = current.model_dump(mode="json")
    row["id"] = "another-card"
    client = ScriptedLLMClient({"financial_extractor": [response(snap, row)]})
    identity = FinancialExtractor(client=client, store=store, artifacts=artifacts).extract(
        target_table="cards",
        target_id=current.id,
        current_row=current.model_dump(mode="json"),
        current_row_hash=None,
        snapshot=snap,
        diff=diff_text("old", snap.canonical_markdown),
        client_event_id="event-identity",
    )
    assert identity.status == "invalid_response"

    pdf_snapshot = snap.model_copy(
        update={
            "raw_artifact": snap.raw_artifact.model_copy(
                update={"media_type": "application/pdf"}
            )
        }
    )
    row = current.model_dump(mode="json")
    row["annual_fee_minor"] = 1_250_000
    client = ScriptedLLMClient({"financial_extractor": [response(pdf_snapshot, row)]})
    pdf = FinancialExtractor(client=client, store=store, artifacts=artifacts).extract(
        target_table="cards",
        target_id=current.id,
        current_row=current.model_dump(mode="json"),
        current_row_hash=None,
        snapshot=pdf_snapshot,
        diff=diff_text("old", pdf_snapshot.canonical_markdown),
        client_event_id="event-pdf-kind",
    )
    assert pdf.status == "invalid_response"


def test_manual_capture_cannot_change_provenance(tmp_path: Path) -> None:
    store, snap, current, artifacts = setup(tmp_path)
    row = current.model_dump(mode="json")
    row["provenance"]["needs_verification"] = False
    payload = response(snap, row)
    payload["fields"][0]["field_path"] = "provenance.needs_verification"
    payload["fields"][0]["proposed_raw_value"] = False
    payload["fields"][0]["evidence_spans"][0]["field_path"] = "provenance.needs_verification"
    scripts: dict[str, list[object]] = {"financial_extractor": [payload]}
    client = ScriptedLLMClient(scripts)
    outcome = FinancialExtractor(client=client, store=store, artifacts=artifacts).extract(
        target_table="cards",
        target_id=current.id,
        current_row=current.model_dump(mode="json"),
        current_row_hash=None,
        snapshot=snap,
        diff=diff_text("old", snap.canonical_markdown),
        client_event_id="event-manual-provenance",
        manual_capture=True,
    )
    assert outcome.status == "invalid_response"


def test_transport_failure_is_one_call_and_not_repaired(tmp_path: Path) -> None:
    store, snap, current, artifacts = setup(tmp_path)
    client = ScriptedLLMClient({"financial_extractor": [LLMCallError("offline") ]})
    outcome = FinancialExtractor(client=client, store=store, artifacts=artifacts).extract(
        target_table="cards",
        target_id=current.id,
        current_row=current.model_dump(mode="json"),
        current_row_hash=None,
        snapshot=snap,
        diff=diff_text("old", snap.canonical_markdown),
        client_event_id="event-transport",
    )
    assert outcome.status == "extraction_failed"
    assert outcome.calls == 1
    assert client.invocations["financial_extractor"] == 1


def test_recording_and_replay_reuse_the_same_single_attempt(tmp_path: Path) -> None:
    store, snap, current, artifacts = setup(tmp_path)
    row = current.model_dump(mode="json")
    row["annual_fee_minor"] = 1_250_000
    scripts: dict[str, list[object]] = {"financial_extractor": [response(snap, row)]}
    recorder = RecordingLLMClient(
        ScriptedLLMClient(scripts), recordings_dir=tmp_path / "recorded"
    )
    first = FinancialExtractor(
        client=recorder, store=store, artifacts=artifacts, now=lambda: NOW
    ).extract(
        target_table="cards",
        target_id=current.id,
        current_row=current.model_dump(mode="json"),
        current_row_hash=None,
        snapshot=snap,
        diff=diff_text("old", snap.canonical_markdown),
        client_event_id="event-record",
    )
    assert first.status == "proposal_pending"
    replay = ReplayLLMClient(recordings_dir=tmp_path / "recorded")
    second = FinancialExtractor(
        client=replay, store=store, artifacts=artifacts, now=lambda: NOW
    ).extract(
        target_table="cards",
        target_id=current.id,
        current_row=current.model_dump(mode="json"),
        current_row_hash=None,
        snapshot=snap,
        diff=diff_text("old", snap.canonical_markdown),
        client_event_id="event-replay",
    )
    assert second.status == "proposal_pending"
    assert replay.calls_replayed == 1


def test_draft_evidence_graph_is_verify_required_and_preserves_lineage() -> None:
    graph = financial_draft_graph(
        run_id="run-fi2",
        snapshot=SnapshotBundle(
            snapshot_id="snap-graph",
            target_id="watch:hdfc",
            captured_at=NOW,
            raw_artifact=ImmutableArtifactRef(sha256=HASH, size_bytes=1, media_type="text/html"),
            normalized_artifact=ImmutableArtifactRef(
                sha256=NORMALIZED_HASH, size_bytes=1, media_type="text/plain"
            ),
            raw_sha256=HASH,
            normalized_sha256=NORMALIZED_HASH,
            canonical_markdown="fee",
        ),
        fields=["annual_fee_minor"],
    )
    assert not check_invariants(graph)
    claim = next(iter(graph.claims.values()))
    assert claim.status == "verify_required"
    assert claim.needs_verification is True
    assert claim.identity.kind == "reference_fact"
    assert graph.model_dump_json() == financial_draft_graph(
        run_id="run-fi2",
        snapshot=SnapshotBundle(
            snapshot_id="snap-graph",
            target_id="watch:hdfc",
            captured_at=NOW,
            raw_artifact=ImmutableArtifactRef(
                sha256=HASH, size_bytes=1, media_type="text/html"
            ),
            normalized_artifact=ImmutableArtifactRef(
                sha256=NORMALIZED_HASH, size_bytes=1, media_type="text/plain"
            ),
            raw_sha256=HASH,
            normalized_sha256=NORMALIZED_HASH,
            canonical_markdown="fee",
        ),
        fields=["annual_fee_minor"],
    ).model_dump_json()


def test_draft_graph_round_trips_through_the_existing_evidence_store(tmp_path: Path) -> None:
    graph = financial_draft_graph(
        run_id="run-fi2-store",
        snapshot=SnapshotBundle(
            snapshot_id="snap-store",
            target_id="watch:hdfc",
            captured_at=NOW,
            raw_artifact=ImmutableArtifactRef(sha256=HASH, size_bytes=1, media_type="text/html"),
            normalized_artifact=ImmutableArtifactRef(
                sha256=NORMALIZED_HASH, size_bytes=1, media_type="text/plain"
            ),
            raw_sha256=HASH,
            normalized_sha256=NORMALIZED_HASH,
            canonical_markdown="fee",
        ),
        fields=["annual_fee_minor"],
    )
    evidence_store = SqliteEvidenceStore(tmp_path / "evidence.sqlite")
    evidence_store.save(graph)
    loaded = evidence_store.load("run-fi2-store")
    assert not check_invariants(loaded)
    assert list(loaded.claims) == list(graph.claims)
