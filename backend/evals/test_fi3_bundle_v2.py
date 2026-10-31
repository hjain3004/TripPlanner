"""Regressions for the FI3 activation bundle v2 (design section 7.1).

A real HDFC Infinia capture showed that a v1 bundle reported ``applicable: True`` and the
dry-run ``would_update`` for a row it did not change, while decisions D1 (row- vs field-level
provenance) and D2 (manual-capture trust) are still open. The bundle must be internally
consistent at most, never authorization, and must not resolve provenance on its own.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from core.db import SEEDS_DIR
from evals.test_fi2_extraction import NOW
from evals.test_fi3_review_activation import runtime
from ingestion.activation import (
    ActivationBundle,
    ActivationBundleRecord,
    ActivationPlanner,
    canonical_bundle_bytes,
    with_current_provenance,
)
from ingestion.contracts import CuratorRecord
from ingestion.review_rows import SeedRowSource
from ingestion.review_server import build_runtime, create_scripted_demo_proposal
from ingestion.review_types import DecisionRequest

V2 = "tripwise.financial-activation-bundle/v2"
V1 = "tripwise.financial-activation-bundle/v1"


def _approve(service: Any, proposal_id: str, *, event: str = "approve-event-v2-0001") -> None:
    service.decide(
        DecisionRequest(
            proposal_id=proposal_id,
            action="approve",
            reason="verified by named operator",
            expected_version=1,
            client_event_id=event,
            curator_confidence=0.9,
        ),
        curator_id="alice",
    )


def _official(tmp_path: Path) -> tuple[Any, ActivationPlanner, str, ActivationBundle]:
    store, service, planner, proposal_id = runtime(tmp_path)
    _approve(service, proposal_id)
    _record, bundle = planner.build(
        proposal_ids=(proposal_id,), curator_id="alice", client_event_id="bundle-event-v2-0001"
    )
    return store, planner, proposal_id, bundle


def _manual(tmp_path: Path) -> tuple[ActivationPlanner, str, ActivationBundle]:
    store, service, planner = build_runtime(tmp_path, SEEDS_DIR, now=lambda: NOW)
    store.put_curator(CuratorRecord(curator_id="alice", display_name="Alice", created_at=NOW))
    proposal_id = create_scripted_demo_proposal(
        store=store, service=service, seeds_dir=SEEDS_DIR, now=NOW
    )
    _approve(service, proposal_id, event="approve-event-manual-0001")
    _record, bundle = planner.build(
        proposal_ids=(proposal_id,), curator_id="alice", client_event_id="bundle-event-manual-0001"
    )
    return planner, proposal_id, bundle


def _persist(planner: ActivationPlanner, body: dict[str, Any], proposal_id: str, event: str) -> str:
    """Store a hand-shaped bundle body the way ``build`` does, and return its content hash."""
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    digest = hashlib.sha256(raw).hexdigest()
    record = ActivationBundleRecord(
        bundle_sha256=digest,
        artifact=planner.artifacts.put(raw, media_type="application/json"),
        proposal_ids=(proposal_id,),
    ).model_dump_json()
    planner.store.put_activation_bundle(
        record,
        bundle_sha256=digest,
        client_event_id=event,
        request_fingerprint=event,
        created_by="alice",
    )
    return digest


def test_bundle_is_v2_and_never_authorizes_activation(tmp_path: Path) -> None:
    _store, _planner, _pid, bundle = _official(tmp_path)
    assert bundle.schema_version == V2
    assert bundle.activation_authorized is False
    assert bundle.unresolved_decisions == ("D1", "D2")
    assert bundle.dry_run_consistent is True
    # The misleading v1 name is gone from the model and from the hashed bytes.
    assert "applicable" not in bundle.model_dump()
    assert b'"applicable"' not in canonical_bundle_bytes(bundle)


def test_an_official_page_entry_lists_evidence_candidate_and_blocker(tmp_path: Path) -> None:
    _store, _planner, _pid, bundle = _official(tmp_path)
    (entry,) = bundle.entries
    assert entry.evidenced_fields and set(entry.evidenced_fields).isdisjoint(
        entry.unevidenced_fields
    )
    candidate = entry.provenance_candidate
    assert candidate.source_type == "official_page"
    assert candidate.verified_by == "alice"
    assert candidate.last_verified == date(2026, 10, 26).isoformat()
    assert candidate.source_url.startswith("https://")
    assert candidate.confidence == 0.9
    assert candidate.needs_verification is None  # D1 must decide it; FI3 never does
    assert entry.blocked_by == ("D1",)


def test_a_manual_capture_entry_is_also_blocked_by_d2(tmp_path: Path) -> None:
    _planner, _pid, bundle = _manual(tmp_path)
    (entry,) = bundle.entries
    assert entry.provenance_candidate.source_type == "manual_curation"
    assert entry.provenance_candidate.needs_verification is None
    assert entry.blocked_by == ("D1", "D2")
    assert "annual_fee_minor" in entry.evidenced_fields


def test_new_row_provenance_is_the_current_rows_provenance(tmp_path: Path) -> None:
    current = SeedRowSource(SEEDS_DIR).current_row("cards", "hdfc-infinia")
    for bundle in (_official(tmp_path / "a")[3], _manual(tmp_path / "b")[2]):
        (entry,) = bundle.entries
        assert entry.new_row["provenance"] == current["provenance"]
        assert entry.new_row["provenance"]["needs_verification"] is True


def test_a_proposed_provenance_never_replaces_the_current_rows() -> None:
    current = {"id": "x", "fee": 1, "provenance": {"verified_by": "UNVERIFIED"}}
    proposed = {"id": "x", "fee": 2, "provenance": {"verified_by": "someone", "extra": 1}}
    merged = with_current_provenance(proposed, current)
    assert merged == {"id": "x", "fee": 2, "provenance": {"verified_by": "UNVERIFIED"}}
    assert proposed["provenance"]["verified_by"] == "someone"  # input not mutated


def test_a_stored_v1_bundle_dry_runs_as_legacy_and_never_as_consistent(tmp_path: Path) -> None:
    _store, planner, proposal_id, bundle = _official(tmp_path)
    # What the v1 planner persisted: `applicable`, no authorization flag or candidates.
    body: dict[str, Any] = bundle.model_dump(mode="json")
    body["schema_version"] = V1
    body["applicable"] = True
    for key in ("activation_authorized", "unresolved_decisions", "dry_run_consistent"):
        del body[key]
    for entry in body["entries"]:
        for key in ("evidenced_fields", "provenance_candidate", "blocked_by"):
            del entry[key]
    report = planner.dry_run(_persist(planner, body, proposal_id, "legacy-v1-bundle-0001"))
    assert report.legacy_bundle is True
    assert report.bundle_schema == V1
    assert report.dry_run_consistent is False
    assert report.activation_authorized is False
    assert report.unresolved_decisions == ("D1", "D2")
    assert report.seed_files_unchanged is True  # checks still run; only the verdict is withheld


def test_a_v2_bundle_dry_run_is_not_legacy(tmp_path: Path) -> None:
    _store, planner, proposal_id, _bundle = _official(tmp_path)
    record, _ = planner.build(
        proposal_ids=(proposal_id,), curator_id="alice", client_event_id="bundle-event-v2-0001"
    )
    report = planner.dry_run(record.bundle_sha256)
    assert report.legacy_bundle is False and report.bundle_schema == V2
    assert report.activation_authorized is False
    assert report.dry_run_consistent is True


def test_an_entry_with_no_field_changes_is_confirmed_unchanged(tmp_path: Path) -> None:
    _store, planner, proposal_id, _bundle = _official(tmp_path)
    record, bundle = planner.build(
        proposal_ids=(proposal_id,), curator_id="alice", client_event_id="bundle-event-v2-0001"
    )
    assert bundle.entries[0].field_changes == ()
    report = planner.dry_run(record.bundle_sha256)
    assert [e.status for e in report.entries] == ["confirmed_unchanged"]
    assert report.kb_constructs is True and report.dry_run_consistent is True


def test_an_entry_with_a_field_change_is_would_update(tmp_path: Path) -> None:
    """Hand-built v2 bundle: the fixture quotes only the seeded fee, so no extracted proposal
    can change a value here. The status is decided by ``field_changes``, not by the schema."""
    _store, planner, proposal_id, bundle = _official(tmp_path)
    body: dict[str, Any] = bundle.model_dump(mode="json")
    entry = body["entries"][0]
    old_fee = entry["new_row"]["annual_fee_minor"]
    entry["new_row"]["annual_fee_minor"] = old_fee + 100
    entry["field_changes"] = [
        {"field_path": "annual_fee_minor", "old": old_fee, "new": old_fee + 100}
    ]
    report = planner.dry_run(_persist(planner, body, proposal_id, "changed-v2-bundle-0001"))
    assert [e.status for e in report.entries] == ["would_update"]
    assert report.kb_constructs is True and report.dry_run_consistent is True


def test_repeated_dry_runs_are_byte_identical(tmp_path: Path) -> None:
    _store, planner, proposal_id, _bundle = _official(tmp_path)
    record, _ = planner.build(
        proposal_ids=(proposal_id,), curator_id="alice", client_event_id="bundle-event-v2-0001"
    )
    first = planner.dry_run(record.bundle_sha256).model_dump_json(indent=2)
    second = planner.dry_run(record.bundle_sha256).model_dump_json(indent=2)
    assert first == second
