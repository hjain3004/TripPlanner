from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from core.db import SEEDS_DIR
from evals.test_fi2_extraction import NOW, response, snapshot
from ingestion.activation import ActivationPlanner
from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import CuratorRecord
from ingestion.review import ReviewService, _supported_edit_value
from ingestion.review_rows import SeedRowSource
from ingestion.review_server import LocalOnlyError, resolve_bind_host, resolve_data_dir
from ingestion.review_types import DecisionRequest, ReviewRefusedError
from ingestion.storage import (
    FinancialIngestionStore,
    IdempotencyConflictError,
    StaleVersionError,
)
from ingestion.validation import canonical_row_hash, validate_extraction


def runtime(
    tmp_path: Path,
) -> tuple[FinancialIngestionStore, ReviewService, ActivationPlanner, str]:
    store = FinancialIngestionStore(tmp_path / "ingestion.sqlite", now=lambda: NOW)
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    snap = snapshot(store, artifacts)
    store.put_snapshot(snap)
    rows = SeedRowSource(SEEDS_DIR)
    current = rows.current_row("cards", "hdfc-infinia")
    # The fixture quote matches the seeded value; the workflow still exercises
    # the complete approval/audit/bundle path without inventing evidence.
    changed = dict(current)
    proposal = validate_extraction(
        response=response(snap, changed),
        target_table="cards",
        target_id="hdfc-infinia",
        current_row=current,
        current_row_hash=canonical_row_hash(current),
        snapshot=snap,
        artifacts=artifacts,
        now=NOW,
        extractor_version="fi3-test",
    )
    store.create_proposal_with_fingerprint(
        proposal, client_event_id="proposal-event-fi3", request_fingerprint=""
    )
    store.put_curator(CuratorRecord(curator_id="alice", display_name="Alice", created_at=NOW))
    service = ReviewService(store=store, artifacts=artifacts, rows=rows, now=lambda: NOW)
    return (
        store,
        service,
        ActivationPlanner(store=store, artifacts=artifacts, rows=rows, service=service),
        proposal.proposal_id,
    )


def test_approve_restart_bundle_and_dry_run_are_durable(tmp_path: Path) -> None:
    store, service, planner, proposal_id = runtime(tmp_path)
    request = DecisionRequest(
        proposal_id=proposal_id,
        action="approve",
        reason="verified by named operator",
        expected_version=1,
        client_event_id="approve-event-fi3",
        curator_confidence=0.9,
    )
    decision = service.decide(request, curator_id="alice")
    reopened = FinancialIngestionStore(tmp_path / "ingestion.sqlite", now=lambda: NOW)
    replay = ReviewService(
        store=reopened,
        artifacts=service.artifacts,
        rows=SeedRowSource(SEEDS_DIR),
        now=lambda: NOW,
    ).decide(request, curator_id="alice")
    assert replay.decision_id == decision.decision_id
    assert len(reopened.list_decisions(proposal_id)) == 1
    record, bundle = planner.build(
        proposal_ids=(proposal_id,), curator_id="alice", client_event_id="bundle-event-fi3"
    )
    assert bundle.applicable
    report = planner.dry_run(record.bundle_sha256)
    assert report.applicable and report.kb_constructs
    assert report.entries[0].status == "would_update"


def test_stale_and_conflicting_reuse_fail_closed(tmp_path: Path) -> None:
    _store, service, _planner, proposal_id = runtime(tmp_path)
    request = DecisionRequest(
        proposal_id=proposal_id,
        action="reject",
        reason="not sufficient",
        expected_version=1,
        client_event_id="reject-event-fi3",
    )
    service.decide(request, curator_id="alice")
    with pytest.raises(IdempotencyConflictError):
        service.decide(request.model_copy(update={"reason": "changed reason"}), curator_id="alice")
    with pytest.raises((ReviewRefusedError, StaleVersionError)):
        service.decide(
            DecisionRequest(
                proposal_id=proposal_id,
                action="approve",
                reason="late",
                expected_version=1,
                client_event_id="approve-late-fi3",
                curator_confidence=0.9,
            ),
            curator_id="alice",
        )


def test_local_server_guards_are_explicit(tmp_path: Path) -> None:
    assert resolve_bind_host("localhost") == "127.0.0.1"
    with pytest.raises(LocalOnlyError):
        resolve_bind_host("0.0.0.0")
    with pytest.raises(LocalOnlyError):
        resolve_data_dir(str(tmp_path / "inside"), env={}, repo_root=tmp_path)


def test_schema_three_database_migrates_to_four_without_losing_rows(tmp_path: Path) -> None:
    path = tmp_path / "ingestion.sqlite"
    FinancialIngestionStore(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO source_policies(id, payload) VALUES (?, ?)",
            ("policy:v3-existing", "{}"),
        )
        connection.execute("DROP TABLE curators")
        connection.execute("DROP TABLE activation_bundles")
        connection.execute("PRAGMA user_version = 3")
    FinancialIngestionStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (4,)
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'curators'"
        ).fetchone() == ("curators",)
        assert connection.execute(
            "SELECT payload FROM source_policies WHERE id = 'policy:v3-existing'"
        ).fetchone() == ("{}",)


def test_curator_edit_type_contract_keeps_date_values_supported() -> None:
    # Date values are parsed by FI2 and must remain admissible at the FI3
    # curator boundary rather than being rejected as an unsupported scalar.
    assert _supported_edit_value(date.fromisoformat("2027-12-31"))
    assert not _supported_edit_value(True)
