from __future__ import annotations

import inspect
import socket
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from ingestion.contracts import (
    ChangeProposal,
    DiscoveryCandidate,
    EvidenceSpan,
    FetchAttempt,
    FetchFailure,
    FetchFailureKind,
    FetchRequest,
    FetchResult,
    FieldProposal,
    ImmutableArtifactRef,
    ProposalStatus,
    ReviewDecisionStatus,
    SnapshotBundle,
    SourcePolicyRecord,
    WatchTarget,
)
from ingestion.policy import CuratorPromotion, promote_candidate_to_watch_target
from ingestion.storage import (
    AlreadyDecidedError,
    ConflictingWriteError,
    FinancialIngestionStore,
    IdempotencyConflictError,
    StaleVersionError,
)

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
HASH = "a" * 64


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
        minimum_delay_seconds=10,
        reviewed_on=date(2026, 10, 1),
        reviewed_by="curator-1",
    )


def candidate() -> DiscoveryCandidate:
    return DiscoveryCandidate(
        id="lead-1",
        found_at=date(2026, 10, 8),
        hint_url="https://cardexpert.example/cards",
        hint_source="cardexpert",
        corridor="IN",
        kind="card",
        issuer_guess="HDFC Bank",
        product_guess="Infinia",
        claim_summary="Earn 10x points on travel",
        issuer_url_to_verify="https://www.hdfcbank.com/cards/infinia",
        status="pending",
    )


def decided_candidate() -> DiscoveryCandidate:
    return candidate().model_copy(
        update={"status": "rejected", "decided_by": "curator-1", "decided_at": date(2026, 10, 8)}
    )


def target() -> WatchTarget:
    return WatchTarget(
        target_id="watch-1",
        canonical_url="https://www.hdfcbank.com/cards/infinia",
        source_policy_id="issuer-hdfc",
        target_fact_ids=("hdfc-infinia",),
        page_kind="card_page",
        check_frequency_days=365,
        preferred_backend="manual",
    )


def alternate_target() -> WatchTarget:
    return target().model_copy(update={"canonical_url": "https://www.hdfcbank.com/cards/regalia"})


def fetch_attempt() -> FetchAttempt:
    return FetchAttempt(
        attempt_id="attempt-1",
        request_id="fetch-1",
        backend="manual",
        backend_version="fi0",
        started_at=NOW,
        ended_at=NOW,
        final_url=target().canonical_url,
        response_class="success",
        retry_index=0,
    )


def span() -> EvidenceSpan:
    return EvidenceSpan(
        snapshot_id="snap-1",
        snapshot_hash=HASH,
        quote="Annual fee is INR 12,500",
        normalized_start=0,
        normalized_end=24,
        field_path="annual_fee_minor",
        verification="exact",
    )


def proposal() -> ChangeProposal:
    field = FieldProposal(
        field_path="annual_fee_minor",
        old_value=1000000,
        proposed_raw_value="12500",
        parsed_value=1250000,
        evidence_spans=(span(),),
    )
    return ChangeProposal(
        proposal_id="proposal-1",
        target_table="cards",
        target_id="hdfc-infinia",
        current_row_hash=HASH,
        proposed_row={"annual_fee_minor": 1250000, "fee_currency": "INR"},
        field_proposals=(field,),
        change_summary="Updated annual fee from issuer page",
        extractor_version="none-fi0",
        validation_findings=(),
        lineage_ids=("snap-1",),
        status=ProposalStatus.PENDING,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def snapshot() -> SnapshotBundle:
    return SnapshotBundle(
        snapshot_id="snap-1",
        target_id="watch-1",
        captured_at=NOW,
        raw_artifact=ImmutableArtifactRef(sha256=HASH, size_bytes=1, media_type="text/html"),
        normalized_artifact=ImmutableArtifactRef(
            sha256="b" * 64, size_bytes=1, media_type="text/plain"
        ),
        raw_sha256=HASH,
        normalized_sha256="b" * 64,
        canonical_markdown=span().quote,
    )


def test_financial_discovery_candidate_has_no_provenance_or_source_type() -> None:
    assert "provenance" not in DiscoveryCandidate.model_fields
    assert "source_type" not in DiscoveryCandidate.model_fields


def test_candidate_promotion_carries_only_curated_issuer_url() -> None:
    promoted = promote_candidate_to_watch_target(
        candidate(),
        CuratorPromotion(curator_id="curator-1", decided_at=NOW, source_policy_id="issuer-hdfc"),
    )
    assert promoted.canonical_url == candidate().issuer_url_to_verify
    assert "claim_summary" not in promoted.model_dump()
    assert "hint_url" not in promoted.model_dump()


def test_proposal_has_no_candidate_constructor_or_aggregator_fields() -> None:
    assert "candidate" not in inspect.signature(ChangeProposal).parameters
    assert "claim_summary" not in proposal().model_dump()
    assert "hint_url" not in proposal().model_dump()


def test_contract_round_trips_and_rejects_unsafe_values() -> None:
    for obj in [policy(), candidate(), target(), span(), proposal()]:
        assert obj.__class__.model_validate_json(obj.model_dump_json()) == obj
    with pytest.raises(ValidationError):
        SourcePolicyRecord.model_validate({**policy().model_dump(), "source_url": "file:///tmp/x"})
    with pytest.raises(ValidationError):
        ImmutableArtifactRef(sha256="not-a-hash", size_bytes=1, media_type="text/plain")
    with pytest.raises(ValidationError):
        EvidenceSpan(**{**span().model_dump(), "quote": "", "normalized_end": 0})


def test_pdf_span_requires_consistent_page_data() -> None:
    with pytest.raises(ValidationError):
        EvidenceSpan(**{**span().model_dump(), "artifact_kind": "pdf", "page_number": None})
    with pytest.raises(ValidationError):
        EvidenceSpan(**{**span().model_dump(), "artifact_kind": "html", "page_number": 2})


def test_fetch_contract_rejects_unsafe_final_urls_and_timestamp_ordering() -> None:
    with pytest.raises(ValidationError):
        FetchResult(request_id="fetch-1", final_url="file:///tmp/secret")
    with pytest.raises(ValidationError):
        FetchResult(request_id="fetch-1", final_url="https://user:pass@example.com/page")
    with pytest.raises(ValidationError):
        FetchAttempt(
            attempt_id="attempt-1",
            request_id="fetch-1",
            backend="manual",
            backend_version="fi0",
            started_at=NOW,
            ended_at=NOW - timedelta(seconds=1),
            response_class="success",
            retry_index=0,
        )


def test_fetch_contract_has_typed_failure_and_no_proposed_row() -> None:
    request = FetchRequest(
        request_id="fetch-1",
        canonical_url=target().canonical_url,
        source_policy_id="issuer-hdfc",
        evidence_kind="official_page",
        max_bytes=1000,
        max_pages=1,
        timeout_seconds=30,
        run_id="run-1",
    )
    result = FetchResult(
        request_id=request.request_id,
        final_url=request.canonical_url,
        content_type="text/html",
        raw_artifact=None,
        normalized_text="",
        failure=FetchFailure(kind=FetchFailureKind.TIMEOUT, diagnostic="bounded"),
    )
    assert "proposed_row" not in FetchResult.model_fields
    assert result.failure is not None


def test_sqlite_reopen_preserves_payloads_and_audit_history(tmp_path: Path) -> None:
    db = tmp_path / "ingestion.sqlite"
    store = FinancialIngestionStore(db, now=lambda: NOW)
    store.put_source_policy(policy())
    store.put_watch_target(target())
    store.put_snapshot(snapshot())
    first = store.create_proposal(proposal(), client_event_id="event-1")
    assert store.create_proposal(proposal(), client_event_id="event-1") == first
    reopened = FinancialIngestionStore(db, now=lambda: NOW)
    assert reopened.get_proposal("proposal-1") == proposal()
    decision = reopened.decide_proposal(
        "proposal-1",
        reviewer_id="curator-1",
        status=ReviewDecisionStatus.REJECTED,
        reason="Needs issuer evidence",
        expected_version=1,
        client_event_id="decision-event-1",
    )
    assert decision.status is ReviewDecisionStatus.REJECTED
    assert reopened.list_decisions("proposal-1")[0] == decision
    audit = reopened.list_audit_events(entity_id="proposal-1")
    assert [event["event_type"] for event in audit] == ["created", "decision"]


def test_immutable_ingestion_writes_are_idempotent_but_conflicts_are_typed(
    tmp_path: Path,
) -> None:
    store = FinancialIngestionStore(tmp_path / "ingestion.sqlite", now=lambda: NOW)
    store.put_source_policy(policy())
    store.put_discovery_candidate(candidate())
    store.put_watch_target(target())
    store.put_fetch_attempt(fetch_attempt())
    store.put_snapshot(snapshot())
    assert store.put_source_policy(policy()) == policy()
    assert store.put_discovery_candidate(candidate()) == candidate()
    assert store.put_watch_target(target()) == target()
    assert store.put_fetch_attempt(fetch_attempt()) == fetch_attempt()
    assert store.put_snapshot(snapshot()) == snapshot()
    audit_before = store.list_audit_events()
    with pytest.raises(ConflictingWriteError):
        store.put_source_policy(policy().model_copy(update={"name": "changed"}))
    with pytest.raises(ConflictingWriteError):
        store.put_discovery_candidate(decided_candidate())
    with pytest.raises(ConflictingWriteError):
        store.put_watch_target(alternate_target())
    with pytest.raises(ConflictingWriteError):
        store.put_fetch_attempt(fetch_attempt().model_copy(update={"retry_index": 1}))
    with pytest.raises(ConflictingWriteError):
        store.put_snapshot(snapshot().model_copy(update={"canonical_markdown": "changed"}))
    assert store.list_audit_events() == audit_before


def test_decision_idempotency_uses_request_fingerprint_not_generated_fields(tmp_path: Path) -> None:
    db = tmp_path / "ingestion.sqlite"
    store = FinancialIngestionStore(db, now=lambda: NOW)
    store.put_source_policy(policy())
    store.put_watch_target(target())
    store.put_snapshot(snapshot())
    store.create_proposal(proposal(), client_event_id="proposal-event")
    first = store.decide_proposal(
        "proposal-1",
        reviewer_id="curator-1",
        status=ReviewDecisionStatus.REJECTED,
        reason="Needs issuer evidence",
        expected_version=1,
        client_event_id="decision-event",
    )
    reopened = FinancialIngestionStore(db, now=lambda: NOW.replace(second=1))
    assert (
        reopened.decide_proposal(
            "proposal-1",
            reviewer_id="curator-1",
            status=ReviewDecisionStatus.REJECTED,
            reason="Needs issuer evidence",
            expected_version=1,
            client_event_id="decision-event",
        )
        == first
    )
    variants = [
        {"proposal_id": "other", "reviewer_id": "curator-1"},
        {"proposal_id": "proposal-1", "reviewer_id": "other"},
        {"proposal_id": "proposal-1", "status": ReviewDecisionStatus.APPROVED},
        {"proposal_id": "proposal-1", "reason": "different"},
        {"proposal_id": "proposal-1", "expected_version": 9},
        {"proposal_id": "proposal-1", "edits": {"annual_fee_minor": 1}},
    ]
    for variant in variants:
        with pytest.raises(IdempotencyConflictError):
            reopened.decide_proposal(
                variant.get("proposal_id", "proposal-1"),
                reviewer_id=variant.get("reviewer_id", "curator-1"),
                status=variant.get("status", ReviewDecisionStatus.REJECTED),
                reason=variant.get("reason", "Needs issuer evidence"),
                expected_version=variant.get("expected_version", 1),
                edits=variant.get("edits"),
                client_event_id="decision-event",
            )


def test_two_connections_only_one_reviewer_can_decide(tmp_path: Path) -> None:
    db = tmp_path / "ingestion.sqlite"
    setup = FinancialIngestionStore(db, now=lambda: NOW)
    setup.put_source_policy(policy())
    setup.put_watch_target(target())
    setup.put_snapshot(snapshot())
    setup.create_proposal(proposal(), client_event_id="proposal-event")
    barrier = threading.Barrier(2)
    outcomes: list[object] = []

    def decide(reviewer: str, status: ReviewDecisionStatus) -> None:
        store = FinancialIngestionStore(db, now=lambda: NOW)
        barrier.wait()
        try:
            outcomes.append(
                store.decide_proposal(
                    "proposal-1",
                    reviewer_id=reviewer,
                    status=status,
                    reason=reviewer,
                    expected_version=1,
                    client_event_id=f"decision-{reviewer}",
                )
            )
        except Exception as error:
            outcomes.append(error)

    threads = [
        threading.Thread(target=decide, args=("a", ReviewDecisionStatus.APPROVED)),
        threading.Thread(target=decide, args=("b", ReviewDecisionStatus.REJECTED)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(isinstance(outcome, Exception) for outcome in outcomes) == 1
    assert sum(not isinstance(outcome, Exception) for outcome in outcomes) == 1
    assert all(
        not isinstance(outcome, Exception)
        or isinstance(outcome, (AlreadyDecidedError, StaleVersionError))
        for outcome in outcomes
    )
    reopened = FinancialIngestionStore(db, now=lambda: NOW)
    assert len(reopened.list_decisions("proposal-1")) == 1
    assert reopened.get_proposal("proposal-1").version == 2
    assert len(reopened.list_audit_events(entity_id="proposal-1")) == 2


def test_reverify_tasks_validate_references_and_are_idempotent(tmp_path: Path) -> None:
    from ingestion.contracts import ReverifyTask

    db = tmp_path / "ingestion.sqlite"
    store = FinancialIngestionStore(db, now=lambda: NOW)
    store.put_source_policy(policy())
    store.put_watch_target(target())
    store.put_snapshot(snapshot())
    task = ReverifyTask(
        task_id="task-1",
        target_id="watch-1",
        reason="stale",
        priority="normal",
        prior_evidence_ids=("snap-1",),
        created_at=NOW,
        due_at=NOW,
    )
    assert store.put_reverify_task(task, client_event_id="task-event") == task
    assert store.put_reverify_task(task, client_event_id="task-event") == task
    with pytest.raises(IdempotencyConflictError):
        store.put_reverify_task(
            task.model_copy(update={"reason": "changed"}), client_event_id="task-event"
        )
    with pytest.raises(ValueError):
        store.put_reverify_task(
            task.model_copy(update={"prior_evidence_ids": ("missing",)}), client_event_id="task-2"
        )
    with pytest.raises(ValidationError):
        ReverifyTask(**{**task.model_dump(), "due_at": NOW - timedelta(seconds=1)})


def test_package_boundaries_and_fi0_are_offline_only() -> None:
    from ast import Import, ImportFrom, parse, walk
    from pathlib import Path as FilePath

    root = FilePath(__file__).parents[1]
    forbidden = {"ingestion"}
    for package in ("core", "agents", "api"):
        for source in (root / package).rglob("*.py"):
            tree = parse(source.read_text())
            for node in walk(tree):
                if isinstance(node, Import):
                    assert all(alias.name.split(".")[0] not in forbidden for alias in node.names)
                if isinstance(node, ImportFrom):
                    assert (node.module or "").split(".")[0] not in forbidden
    for source in (root / "ingestion").glob("*.py"):
        tree = parse(source.read_text())
        imported = [
            alias.name.split(".")[0]
            for node in walk(tree)
            if isinstance(node, Import)
            for alias in node.names
        ]
        imported.extend(
            (node.module or "").split(".")[0] for node in walk(tree) if isinstance(node, ImportFrom)
        )
        assert not set(imported).intersection(
            {"requests", "httpx", "crawl4ai", "firecrawl", "playwright"}
        )


def test_stale_and_duplicate_decisions_fail_closed(tmp_path: Path) -> None:
    store = FinancialIngestionStore(tmp_path / "ingestion.sqlite", now=lambda: NOW)
    store.put_source_policy(policy())
    store.put_watch_target(target())
    store.put_snapshot(snapshot())
    store.create_proposal(proposal(), client_event_id="event-1")
    with pytest.raises(StaleVersionError):
        store.decide_proposal(
            "proposal-1",
            reviewer_id="c",
            status=ReviewDecisionStatus.APPROVED,
            reason="ok",
            expected_version=7,
            client_event_id="d-1",
        )
    store.decide_proposal(
        "proposal-1",
        reviewer_id="c",
        status=ReviewDecisionStatus.APPROVED,
        reason="ok",
        expected_version=1,
        client_event_id="d-1",
    )
    with pytest.raises(AlreadyDecidedError):
        store.decide_proposal(
            "proposal-1",
            reviewer_id="other",
            status=ReviewDecisionStatus.REJECTED,
            reason="no",
            expected_version=2,
            client_event_id="d-2",
        )


def test_missing_references_are_rejected(tmp_path: Path) -> None:
    store = FinancialIngestionStore(tmp_path / "ingestion.sqlite")
    with pytest.raises(ValueError):
        store.put_watch_target(target())
    with pytest.raises(ValueError):
        store.create_proposal(proposal(), client_event_id="event-1")


def test_schema_creation_is_idempotent_and_network_is_not_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("FI0 must not use the network")

    monkeypatch.setattr(socket.socket, "connect", fail)
    db = tmp_path / "ingestion.sqlite"
    FinancialIngestionStore(db)
    FinancialIngestionStore(db)


def test_draft_evidence_uses_financial_reference_identity() -> None:
    from gateway.evidence.identity import ReferenceFactIdentity
    from gateway.evidence.nodes import Claim, ClaimKind, FreshnessState

    identity = ReferenceFactIdentity(
        kind="reference_fact", namespace="financial_draft", entity_id="proposal-1", field="fee"
    )
    claim = Claim(
        claim_id="claim-1",
        run_id="run-1",
        adapter_id="financial-ingestion-fi0",
        kind=ClaimKind.REFERENCE_FACT,
        identity=identity,
        payload={"value": 1250000},
        source_id="source-1",
        is_inference=False,
        status=FreshnessState.VERIFY_REQUIRED,
        confidence=0.0,
        needs_verification=True,
    )
    assert claim.identity.namespace == "financial_draft"
    assert claim.status is FreshnessState.VERIFY_REQUIRED
    assert claim.needs_verification is True
