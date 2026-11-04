"""Two operators (processes) staging the same capture at the same moment.

The ingestion store's "immutable" writers read first and insert second; without a write lock,
two first-writers can both see "absent" and the loser dies on the UNIQUE constraint instead of
replaying. These tests use a separate store handle per thread, like separate processes.
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime
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
