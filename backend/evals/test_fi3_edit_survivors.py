"""Regressions for ``ReviewService.apply_edits`` dropping un-edited FI2 field proposals.

``apply_edits`` built the extraction response from the curator's ``set`` edits only. The
edited row still carried every other proposed value, so validation either saw no fields at
all (a raw pydantic error) or refused the row for "changing a field without a field proposal".
The response must be the surviving FI2 proposals (not reverted, not overridden, each with its
original evidence) plus the curator's ``set`` edits.

The proposal here changes two seed fields on ``hdfc-infinia``: the annual fee to INR 15,000
and the forex markup to 3.5%, both quoted. The snapshot also says "Joining fee INR 14,000."
for the curator to cite.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.db import SEEDS_DIR
from evals.test_fi2_extraction import NOW, policy
from ingestion.activation import ActivationBundle, ActivationPlanner
from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import CuratorRecord, SnapshotBundle, WatchTarget
from ingestion.review import ReviewService
from ingestion.review_rows import SeedRowSource
from ingestion.review_types import (
    CuratorFieldEdit,
    DecisionRequest,
    FindingCode,
    ReviewRefusedError,
)
from ingestion.storage import FinancialIngestionStore
from ingestion.validation import canonical_row_hash, validate_extraction

FEE_QUOTE = "Annual fee is INR 15,000."
FOREX_QUOTE = "Forex markup is 3.5%."
JOINING_QUOTE = "Joining fee INR 14,000."
TEXT = f"{FEE_QUOTE} {FOREX_QUOTE} {JOINING_QUOTE}"
SNAPSHOT_ID = "snapshot:watch:hdfc:1"


def _span(snap: SnapshotBundle, field_path: str, quote: str) -> dict[str, Any]:
    start = TEXT.index(quote)
    return {
        "snapshot_id": snap.snapshot_id,
        "snapshot_hash": snap.normalized_sha256,
        "quote": quote,
        "normalized_start": start,
        "normalized_end": start + len(quote),
        "field_path": field_path,
        "verification": "exact",
    }


def build(tmp_path: Path) -> tuple[ReviewService, ActivationPlanner, str, SnapshotBundle]:
    store = FinancialIngestionStore(tmp_path / "ingestion.sqlite", now=lambda: NOW)
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
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
    raw = artifacts.put(TEXT.encode(), media_type="text/html")
    normalized = artifacts.put(TEXT.encode(), media_type="text/plain")
    snap = SnapshotBundle(
        snapshot_id=SNAPSHOT_ID,
        target_id="watch:hdfc",
        captured_at=NOW,
        raw_artifact=raw,
        normalized_artifact=normalized,
        raw_sha256=raw.sha256,
        normalized_sha256=normalized.sha256,
        canonical_markdown=TEXT,
    )
    store.put_snapshot(snap)
    rows = SeedRowSource(SEEDS_DIR)
    current = rows.current_row("cards", "hdfc-infinia")
    proposed = dict(current)
    proposed["annual_fee_minor"] = 1_500_000
    proposed["forex_markup_bp"] = 350
    proposal = validate_extraction(
        response={
            "target_table": "cards",
            "target_id": "hdfc-infinia",
            "proposed_row": proposed,
            "fields": [
                {
                    "field_path": "annual_fee_minor",
                    "proposed_raw_value": "INR 15,000",
                    "evidence_spans": [_span(snap, "annual_fee_minor", FEE_QUOTE)],
                },
                {
                    "field_path": "forex_markup_bp",
                    "proposed_raw_value": "3.5%",
                    "evidence_spans": [_span(snap, "forex_markup_bp", FOREX_QUOTE)],
                },
            ],
            "change_summary": "Synthetic: fee and forex markup changed.",
            "extractor_confidence": 0.8,
        },
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
        proposal, client_event_id="proposal-event-two-fields", request_fingerprint=""
    )
    store.put_curator(CuratorRecord(curator_id="alice", display_name="Alice", created_at=NOW))
    service = ReviewService(store=store, artifacts=artifacts, rows=rows, now=lambda: NOW)
    planner = ActivationPlanner(store=store, artifacts=artifacts, rows=rows, service=service)
    return service, planner, proposal.proposal_id, snap


REVERT_FOREX = CuratorFieldEdit(field_path="forex_markup_bp", action="revert")
REVERT_FEE = CuratorFieldEdit(field_path="annual_fee_minor", action="revert")


def _set_fee_to_joining_fee(snap: SnapshotBundle) -> CuratorFieldEdit:
    return CuratorFieldEdit(
        field_path="annual_fee_minor",
        action="set",
        proposed_raw_value="INR 14,000",
        quote=JOINING_QUOTE,
        snapshot_id=snap.snapshot_id,
    )


def _decide(service: ReviewService, proposal_id: str, *edits: CuratorFieldEdit) -> Any:
    return service.decide(
        DecisionRequest(
            proposal_id=proposal_id,
            action="edit",
            reason="curator edit over survivors",
            expected_version=1,
            client_event_id="edit-event-survivors-0001",
            curator_confidence=0.9,
            edits=edits,
        ),
        curator_id="alice",
    )


def _paths(proposal: Any) -> list[str]:
    return [field.field_path for field in proposal.field_proposals]


# (a) revert one field: the other proposal survives ------------------------------------------


def test_reverting_only_the_markup_keeps_the_fee_change_and_the_current_markup(
    tmp_path: Path,
) -> None:
    service, _planner, pid, _snap = build(tmp_path)
    decision = _decide(service, pid, REVERT_FOREX)
    assert decision.status.value == "edited"
    row, validated = service.apply_edits(service.context(pid), (REVERT_FOREX,))
    current = SeedRowSource(SEEDS_DIR).current_row("cards", "hdfc-infinia")
    assert row["annual_fee_minor"] == 1_500_000
    assert row["forex_markup_bp"] == current["forex_markup_bp"] == 200
    assert _paths(validated) == ["annual_fee_minor"]
    (span,) = validated.field_proposals[0].evidence_spans
    assert span.quote == FEE_QUOTE  # the surviving proposal keeps its original evidence


# (b) set one field: the other proposal survives ---------------------------------------------


def test_setting_the_fee_keeps_the_markup_change_with_its_original_evidence(
    tmp_path: Path,
) -> None:
    service, _planner, pid, snap = build(tmp_path)
    edit = _set_fee_to_joining_fee(snap)
    decision = _decide(service, pid, edit)
    assert decision.status.value == "edited"
    row, validated = service.apply_edits(service.context(pid), (edit,))
    assert row["annual_fee_minor"] == 1_400_000
    assert row["forex_markup_bp"] == 350
    by_path = {f.field_path: f for f in validated.field_proposals}
    assert set(by_path) == {"annual_fee_minor", "forex_markup_bp"}
    assert by_path["annual_fee_minor"].evidence_spans[0].quote == JOINING_QUOTE  # the edit wins
    assert by_path["forex_markup_bp"].evidence_spans[0].quote == FOREX_QUOTE  # survivor, unchanged


# (c) nothing left to approve ------------------------------------------------------------------


def test_reverting_every_changed_field_is_a_clean_refusal(tmp_path: Path) -> None:
    service, _planner, pid, _snap = build(tmp_path)
    with pytest.raises(ReviewRefusedError) as refused:
        _decide(service, pid, REVERT_FEE, REVERT_FOREX)
    codes = {finding.code for finding in refused.value.findings}
    assert codes & {FindingCode.NO_EFFECTIVE_EDIT, FindingCode.INVALID_EDIT}
    # Nothing was recorded for a refused edit.
    assert service.store.list_decisions(pid) == []


def test_any_unexpected_failure_in_the_edit_path_surfaces_as_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _planner, pid, _snap = build(tmp_path)

    def explode(**_: Any) -> Any:
        raise RuntimeError("unexpected")

    monkeypatch.setattr("ingestion.review.validate_extraction", explode)
    with pytest.raises(ReviewRefusedError):
        service.apply_edits(service.context(pid), (REVERT_FOREX,))


# Activation: evidenced_fields for edited decisions -----------------------------------------


def _entry(planner: ActivationPlanner, pid: str, event: str) -> Any:
    _record, bundle = planner.build(proposal_ids=(pid,), curator_id="alice", client_event_id=event)
    assert isinstance(bundle, ActivationBundle) and not bundle.refused
    (entry,) = bundle.entries
    return entry


def test_a_reverted_field_is_unevidenced_in_the_bundle(tmp_path: Path) -> None:
    service, planner, pid, _snap = build(tmp_path)
    _decide(service, pid, REVERT_FOREX)
    entry = _entry(planner, pid, "bundle-event-revert-0001")
    assert entry.evidenced_fields == ("annual_fee_minor",)
    assert "forex_markup_bp" in entry.unevidenced_fields
    assert "forex_markup_bp" not in entry.evidenced_fields
    assert entry.new_row["forex_markup_bp"] == 200
    assert [c.field_path for c in entry.field_changes] == ["annual_fee_minor"]


def test_surviving_proposal_fields_plus_set_edits_are_evidenced_in_the_bundle(
    tmp_path: Path,
) -> None:
    service, planner, pid, snap = build(tmp_path)
    _decide(service, pid, _set_fee_to_joining_fee(snap))
    entry = _entry(planner, pid, "bundle-event-set-0001")
    assert entry.evidenced_fields == ("annual_fee_minor", "forex_markup_bp")
    assert not set(entry.evidenced_fields) & set(entry.unevidenced_fields)
    assert entry.new_row["annual_fee_minor"] == 1_400_000
    assert entry.new_row["forex_markup_bp"] == 350


def test_an_approved_decision_still_evidences_every_proposed_field(tmp_path: Path) -> None:
    service, planner, pid, _snap = build(tmp_path)
    service.decide(
        DecisionRequest(
            proposal_id=pid,
            action="approve",
            reason="approve both quoted changes",
            expected_version=1,
            client_event_id="approve-event-survivors-01",
            curator_confidence=0.9,
        ),
        curator_id="alice",
    )
    entry = _entry(planner, pid, "bundle-event-approve-0001")
    assert entry.evidenced_fields == ("annual_fee_minor", "forex_markup_bp")
