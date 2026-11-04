"""Two operators (processes) staging the same capture at the same moment.

The ingestion store's "immutable" writers read first and insert second; without a write lock,
two first-writers can both see "absent" and the loser dies on the UNIQUE constraint instead of
replaying. These tests use a separate store handle per thread, like separate processes.
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from ingestion.contracts import (
    CuratorRecord,
    PageKind,
    SourcePolicyRecord,
    WatchTarget,
)
from ingestion.storage import FinancialIngestionStore

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
TRIALS = 25
WORKERS = 6


def _policy() -> SourcePolicyRecord:
    return SourcePolicyRecord(
        policy_id="race-policy",
        name="SYNTHETIC",
        owner="fixture",
        domain="example.invalid",
        source_url="https://www.example.invalid/c",
        terms_url="https://www.example.invalid/t",
        terms_read_on=date(2026, 11, 1),
        automated_access_permitted=False,
        manual_only=True,
        allowed_page_classes=("card_page",),
        reviewed_on=date(2026, 11, 1),
        reviewed_by="alice",
    )


def _target() -> WatchTarget:
    return WatchTarget(
        target_id="race-target",
        canonical_url="https://www.example.invalid/c",
        source_policy_id="race-policy",
        target_fact_ids=("hdfc-infinia",),
        page_kind=PageKind.MANUAL_CAPTURE,
        check_frequency_days=365,
        preferred_backend="manual",
        manual_only=True,
    )


def _race(tmp_path: Path, trial: int, work: Any) -> list[BaseException]:
    path = tmp_path / f"race-{trial}.sqlite"
    FinancialIngestionStore(path, now=lambda: NOW)  # create the schema once
    barrier = threading.Barrier(WORKERS)
    errors: list[BaseException] = []

    def run() -> None:
        store = FinancialIngestionStore(path, now=lambda: NOW)
        barrier.wait()
        try:
            work(store)
        except BaseException as error:  # noqa: BLE001 - the test reports whatever escaped
            errors.append(error)

    threads = [threading.Thread(target=run) for _ in range(WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return errors


def test_concurrent_first_writers_of_the_same_policy_and_target_all_succeed(
    tmp_path: Path,
) -> None:
    def work(store: FinancialIngestionStore) -> None:
        store.put_source_policy(_policy())
        store.put_watch_target(_target())

    for trial in range(TRIALS):
        assert _race(tmp_path, trial, work) == [], f"trial {trial}"
        store = FinancialIngestionStore(tmp_path / f"race-{trial}.sqlite")
        assert store.get_source_policy("race-policy") == _policy()
        assert store.get_watch_target("race-target") == _target()
        events = [
            e for e in store.list_audit_events() if e["entity_id"] in {"race-policy", "race-target"}
        ]
        assert len(events) == 2  # one creation event each, however many writers raced


def test_concurrent_registration_of_the_same_curator_is_idempotent(tmp_path: Path) -> None:
    record = CuratorRecord(curator_id="alice", display_name="Alice", created_at=NOW)

    for trial in range(TRIALS):
        errors = _race(tmp_path, trial, lambda store: store.put_curator(record))
        assert errors == [], f"trial {trial}"


# ------------------------------------------------------------------ replay identity


def _snapshot(store: FinancialIngestionStore, *, captured: datetime, text: str = "fee 1") -> Any:
    from ingestion.artifacts import ContentAddressedStore
    from ingestion.contracts import FetchAttempt, SnapshotBundle

    artifacts = ContentAddressedStore(store.path.parent / "artifacts")
    raw = artifacts.put(text.encode(), media_type="text/plain")
    normalized = artifacts.put(text.encode(), media_type="text/plain")
    attempt = FetchAttempt(
        attempt_id=f"attempt-{captured.isoformat()}",
        request_id="r",
        backend="manual",
        backend_version="fi1",
        started_at=captured,
        ended_at=captured,
        final_url="https://www.example.invalid/c",
        response_class="success",
        retry_index=0,
    )
    return SnapshotBundle(
        snapshot_id=f"snapshot:race-target:{normalized.sha256}:{raw.sha256}",
        target_id="race-target",
        captured_at=captured,
        raw_artifact=raw,
        normalized_artifact=normalized,
        raw_sha256=raw.sha256,
        normalized_sha256=normalized.sha256,
        canonical_markdown=text,
        attempts=(attempt,),
    )


def test_a_snapshot_put_again_with_the_same_content_is_a_replay_not_a_conflict(
    tmp_path: Path,
) -> None:
    store = FinancialIngestionStore(tmp_path / "s.sqlite", now=lambda: NOW)
    store.put_source_policy(_policy())
    store.put_watch_target(_target())
    first = store.put_snapshot(_snapshot(store, captured=NOW))
    # later capture of the same bytes: different time and attempt, same content-addressed id
    again = store.put_snapshot(_snapshot(store, captured=NOW + timedelta(minutes=3)))
    assert again == first  # the stored record comes back; history is not rewritten
    assert len([e for e in store.list_audit_events() if e["entity_id"] == first.snapshot_id]) == 1


def test_a_snapshot_whose_content_differs_under_the_same_id_still_conflicts(
    tmp_path: Path,
) -> None:
    import pytest

    store = FinancialIngestionStore(tmp_path / "s.sqlite", now=lambda: NOW)
    store.put_source_policy(_policy())
    store.put_watch_target(_target())
    first = store.put_snapshot(_snapshot(store, captured=NOW))
    from ingestion.storage import ConflictingWriteError

    with pytest.raises(ConflictingWriteError):
        store.put_snapshot(first.model_copy(update={"canonical_markdown": "tampered"}))


def _proposal(created: datetime) -> Any:
    from ingestion.contracts import ChangeProposal, EvidenceSpan, FieldProposal

    snapshot_id = _snapshot_id(created)
    span = EvidenceSpan(
        snapshot_id=snapshot_id,
        snapshot_hash="0" * 64,
        quote="q",
        normalized_start=0,
        normalized_end=1,
        field_path="annual_fee_minor",
        verification="exact",
    )
    return ChangeProposal(
        proposal_id="proposal:x",
        target_table="cards",
        target_id="x",
        proposed_row={"id": "x"},
        field_proposals=(FieldProposal(field_path="annual_fee_minor", evidence_spans=(span,)),),
        change_summary="c",
        extractor_version="v",
        lineage_ids=(snapshot_id,),
        version=1,
        created_at=created,
        updated_at=created,
        intent="insert",
    )


def _snapshot_id(_: datetime) -> str:
    import hashlib

    digest = hashlib.sha256(b"fee 1").hexdigest()
    return f"snapshot:race-target:{digest}:{digest}"


def test_the_request_fingerprint_is_the_identity_of_a_proposal_replay(tmp_path: Path) -> None:
    import pytest

    from ingestion.storage import IdempotencyConflictError

    store = FinancialIngestionStore(tmp_path / "s.sqlite", now=lambda: NOW)
    store.put_source_policy(_policy())
    store.put_watch_target(_target())
    store.put_snapshot(_snapshot(store, captured=NOW))
    first = store.create_proposal_with_fingerprint(
        _proposal(NOW), client_event_id="event-0000000001", request_fingerprint="a" * 64
    )
    # the same request, run later: the payload differs only by created_at, so it is a replay
    later = store.create_proposal_with_fingerprint(
        _proposal(NOW + timedelta(seconds=5)),
        client_event_id="event-0000000001",
        request_fingerprint="a" * 64,
    )
    assert later == first and len(store.list_proposals()) == 1
    # a different request under the same event id is still refused
    with pytest.raises(IdempotencyConflictError):
        store.create_proposal_with_fingerprint(
            _proposal(NOW), client_event_id="event-0000000001", request_fingerprint="b" * 64
        )
