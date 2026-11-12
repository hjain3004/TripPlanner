from __future__ import annotations

import json
import multiprocessing
import os
import signal
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from ingestion.acquisition_control import (
    AcquisitionControlLimits,
    DurableAcquisitionControl,
)
from ingestion.contracts import (
    FetchFailure,
    FetchFailureKind,
    FetchRequest,
    FetchResult,
    PageKind,
    SourcePolicyRecord,
    WatchTarget,
)
from ingestion.storage import (
    AcquisitionLockContentionError,
    FinancialIngestionStore,
    IngestionStoreError,
)

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def policy(*, delay_seconds: int = 10) -> SourcePolicyRecord:
    return SourcePolicyRecord(
        policy_id="issuer-policy",
        name="Issuer official",
        owner="Issuer",
        domain="issuer.example",
        source_url="https://issuer.example/card",
        terms_url="https://issuer.example/terms",
        terms_read_on=date(2026, 11, 1),
        automated_access_permitted=True,
        manual_only=False,
        allowed_page_classes=("card_page",),
        minimum_delay_seconds=delay_seconds,
        reviewed_on=date(2026, 11, 1),
        reviewed_by="curator-1",
    )


def request(
    request_id: str = "request-1",
    *,
    url: str = "https://issuer.example/card",
    run_id: str = "run-1",
    forced_freshness: bool = False,
) -> FetchRequest:
    return FetchRequest(
        request_id=request_id,
        canonical_url=url,
        source_policy_id="issuer-policy",
        evidence_kind="official_page",
        page_class=PageKind.CARD_PAGE,
        max_bytes=1000,
        max_pages=1,
        timeout_seconds=5,
        forced_freshness=forced_freshness,
        run_id=run_id,
    )


def target(target_id: str, *, frequency: int = 1, manual_only: bool = False) -> WatchTarget:
    return WatchTarget(
        target_id=target_id,
        canonical_url=f"https://issuer.example/{target_id}",
        source_policy_id="issuer-policy",
        target_fact_ids=(target_id,),
        page_kind=PageKind.CARD_PAGE,
        check_frequency_days=frequency,
        manual_only=manual_only,
    )


def limits(
    *,
    per_request: int = 3,
    run: int = 5,
    month: int = 10,
    pricing_version: str = "fixture-v1",
    extraction_intent: str = "raw_html",
) -> AcquisitionControlLimits:
    return AcquisitionControlLimits(
        per_request_credits=per_request,
        per_run_credits=run,
        per_month_credits=month,
        pricing_version=pricing_version,
        extraction_intent=extraction_intent,
    )


def control(
    path: Path, *, configured_limits: AcquisitionControlLimits | None = None
) -> DurableAcquisitionControl:
    store = FinancialIngestionStore(path)
    store.put_source_policy(policy())
    return DurableAcquisitionControl(store, limits=configured_limits or limits())


class DeterministicProviderDouble:
    """Offline provider double that appends every invoked dispatch to a shared log file."""

    def __init__(self, dispatch_log_path: Path) -> None:
        self._log_path = dispatch_log_path

    def invoke(self, req: FetchRequest, *, fail: bool = False) -> FetchResult:
        with self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "request_id": req.request_id,
                        "url": req.canonical_url,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
            handle.flush()
        if fail:
            return FetchResult(
                request_id=req.request_id,
                failure=FetchFailure(
                    kind=FetchFailureKind.TIMEOUT,
                    diagnostic="deterministic provider timeout after dispatch",
                    retryable=True,
                ),
            )
        return FetchResult(
            request_id=req.request_id,
            final_url=req.canonical_url,
            content_type="text/html",
            normalized_text=f"captured:{req.request_id}",
            engine="deterministic-double",
            engine_version="v1",
            duration_ms=5,
        )

    def dispatches(self) -> list[dict[str, object]]:
        if not self._log_path.exists():
            return []
        return [
            json.loads(line)
            for line in self._log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def _claim_and_dispatch_in_process(
    db_path: str,
    log_path: str,
    request_id: str,
    url: str,
    run_Limit: int,
    output: multiprocessing.Queue[tuple[str, str]],
) -> None:
    controller = control(Path(db_path), configured_limits=limits(run=run_Limit, month=10))
    provider = DeterministicProviderDouble(Path(log_path))
    req = request(request_id, url=url)
    claim = controller.claim(req, policy_hash="policy-a", estimated_credits=1, now=NOW)
    if claim.state == "dispatch":
        controller.mark_dispatch_started(request_id, now=NOW)
        res = provider.invoke(req)
        controller.complete(request_id, result=res, charged_credits=1, now=NOW)
    output.put((request_id, claim.state))


def _crash_after_dispatch_worker(
    db_path: str,
    log_path: str,
    request_id: str,
    mark_started: bool,
    ready_event: object,
) -> None:
    controller = control(Path(db_path))
    provider = DeterministicProviderDouble(Path(log_path))
    req = request(request_id)
    claim = controller.claim(req, policy_hash="policy-a", estimated_credits=2, now=NOW)
    assert claim.state == "dispatch"
    if mark_started:
        controller.mark_dispatch_started(request_id, now=NOW)
        provider.invoke(req)
    ready_event.set()  # type: ignore[attr-defined]
    while True:
        time.sleep(0.05)


def test_claim_reserves_before_dispatch_and_replays_completed_result(tmp_path: Path) -> None:
    controller = control(tmp_path / "ingestion.sqlite")
    initial = controller.claim(request(), policy_hash="policy-a", estimated_credits=1, now=NOW)
    assert initial.state == "dispatch"

    reserved_status = controller.status("request-1")
    assert reserved_status is not None
    assert reserved_status.operator_outcome == "reserved_not_yet_dispatched"

    controller.mark_dispatch_started("request-1", now=NOW)
    in_flight_status = controller.status("request-1")
    assert in_flight_status is not None
    assert in_flight_status.operator_outcome == "possibly_dispatched_ambiguous"

    controller.complete(
        "request-1",
        result=FetchResult(request_id="request-1", normalized_text="captured"),
        charged_credits=1,
        now=NOW + timedelta(seconds=1),
    )
    replay = controller.claim(request(), policy_hash="policy-a", estimated_credits=1, now=NOW)
    assert replay.state == "replay"
    assert replay.replay_result is not None
    assert replay.replay_result.normalized_text == "captured"

    completed_status = controller.status("request-1")
    assert completed_status is not None
    assert completed_status.operator_outcome == "completed_and_replayable"
    assert completed_status.pricing_version == "fixture-v1"


def test_canonical_fingerprint_binds_inputs_policy_freshness_extraction_and_pricing(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "ingestion.sqlite"
    controller = control(db_path)
    assert (
        controller.claim(request(), policy_hash="policy-a", estimated_credits=1, now=NOW).state
        == "dispatch"
    )
    # Different policy hash conflicts on same key
    assert (
        controller.claim(request(), policy_hash="policy-b", estimated_credits=1, now=NOW).state
        == "conflict"
    )
    # Different freshness intent conflicts on same key
    assert (
        controller.claim(
            request(forced_freshness=True), policy_hash="policy-a", estimated_credits=1, now=NOW
        ).state
        == "conflict"
    )
    # Different pricing configuration conflicts on same key
    reopened_diff_pricing = control(
        db_path, configured_limits=limits(pricing_version="fixture-v2")
    )
    assert (
        reopened_diff_pricing.claim(
            request(), policy_hash="policy-a", estimated_credits=1, now=NOW
        ).state
        == "conflict"
    )
    # Different extraction intent conflicts on same key
    reopened_diff_extraction = control(
        db_path, configured_limits=limits(extraction_intent="pdf_bytes")
    )
    assert (
        reopened_diff_extraction.claim(
            request(), policy_hash="policy-a", estimated_credits=1, now=NOW
        ).state
        == "conflict"
    )
    # Completion is idempotent for identical payload/credits and rejects conflicting completion
    result = FetchResult(request_id="request-1", normalized_text="ok")
    controller.complete("request-1", result=result, charged_credits=1, now=NOW)
    controller.complete("request-1", result=result, charged_credits=1, now=NOW)
    with pytest.raises(IngestionStoreError, match="conflicting acquisition completion"):
        controller.complete("request-1", result=result, charged_credits=2, now=NOW)


def test_failed_dispatch_retains_evidence_and_never_refunds_reserved_credits(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "ingestion.sqlite"
    controller = control(db_path, configured_limits=limits(run=2, month=2))
    provider = DeterministicProviderDouble(tmp_path / "dispatch.log")

    req1 = request("request-fail", url="https://issuer.example/card")
    assert (
        controller.claim(req1, policy_hash="policy-a", estimated_credits=2, now=NOW).state
        == "dispatch"
    )
    failed_result = provider.invoke(req1, fail=True)
    # Even if caller passes charged_credits=0 on a failed result, reservation is retained.
    controller.complete("request-fail", result=failed_result, charged_credits=0, now=NOW)

    status = controller.status("request-fail")
    assert status is not None
    assert status.operator_outcome == "failed_with_retained_evidence"
    assert status.charged_credits == 2
    assert status.replay_result is not None and status.replay_result.failure is not None

    # Re-claiming the failed request replays the retained failure without a new provider call.
    replay = controller.claim(req1, policy_hash="policy-a", estimated_credits=2, now=NOW)
    assert replay.state == "replay"
    assert replay.replay_result is not None and replay.replay_result.failure is not None
    assert len(provider.dispatches()) == 1

    # Because the 2 reserved credits were not refunded, a second request in the run is blocked.
    req2 = request("request-next", url="https://other.example/card")
    blocked = controller.claim(
        req2, policy_hash="policy-a", estimated_credits=1, now=NOW + timedelta(seconds=30)
    )
    assert blocked.state == "blocked"
    assert "allowance is exhausted" in blocked.safe_diagnostic
    blocked_status = controller.status("request-next")
    assert blocked_status is not None
    assert blocked_status.operator_outcome == "blocked_by_budget_or_delay"
    assert blocked_status.charged_credits == 0


def test_domain_delay_and_budget_reservations_are_durable(tmp_path: Path) -> None:
    controller = control(
        tmp_path / "ingestion.sqlite", configured_limits=limits(run=1, month=1)
    )
    assert (
        controller.claim(request(), policy_hash="policy-a", estimated_credits=1, now=NOW).state
        == "dispatch"
    )
    assert (
        controller.claim(
            request("request-2", url="https://another.example/card"),
            policy_hash="policy-a",
            estimated_credits=1,
            now=NOW,
        ).state
        == "blocked"
    )
    # Reopen proves the reservation remains charged even before completion.
    reopened = control(tmp_path / "ingestion.sqlite", configured_limits=limits(run=1, month=1))
    assert (
        reopened.claim(
            request("request-3", url="https://another.example/second", run_id="run-2"),
            policy_hash="policy-a",
            estimated_credits=1,
            now=NOW,
        ).state
        == "blocked"
    )


def test_two_processes_enforce_atomic_domain_delay_and_budget_with_provider_double(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "ingestion.sqlite"
    log_path = tmp_path / "dispatch.log"
    control(db_path)
    context = multiprocessing.get_context("spawn")
    output: multiprocessing.Queue[tuple[str, str]] = context.Queue()

    first = context.Process(
        target=_claim_and_dispatch_in_process,
        args=(str(db_path), str(log_path), "request-a", "https://issuer.example/card", 5, output),
    )
    second = context.Process(
        target=_claim_and_dispatch_in_process,
        args=(str(db_path), str(log_path), "request-b", "https://issuer.example/card", 5, output),
    )
    first.start()
    second.start()
    first.join(timeout=15)
    second.join(timeout=15)
    assert first.exitcode == 0 and second.exitcode == 0
    outcomes = dict([output.get(timeout=2), output.get(timeout=2)])
    # The losing process can observe either completed work (and therefore the
    # domain-delay block) or the winner's durably marked in-flight dispatch.
    # The latter must remain pending for reconciliation rather than being
    # reported as safely undispatched.  In both schedules only one request may
    # reach the provider.
    assert outcomes["request-a"] == "dispatch" or outcomes["request-b"] == "dispatch"
    assert set(outcomes.values()) in ({"dispatch", "blocked"}, {"dispatch", "pending"})

    # Only the single winning process invoked the deterministic provider double.
    dispatches = DeterministicProviderDouble(log_path).dispatches()
    assert len(dispatches) == 1

    # Also verify cross-domain budget cap across two concurrent processes when run limit = 1.
    db_budget = tmp_path / "budget.sqlite"
    log_budget = tmp_path / "budget_dispatch.log"
    store = FinancialIngestionStore(db_budget)
    store.put_source_policy(policy())
    out_budget: multiprocessing.Queue[tuple[str, str]] = context.Queue()
    p1 = context.Process(
        target=_claim_and_dispatch_in_process,
        args=(
            str(db_budget),
            str(log_budget),
            "req-1",
            "https://one.issuer.example/card",
            1,
            out_budget,
        ),
    )
    p2 = context.Process(
        target=_claim_and_dispatch_in_process,
        args=(
            str(db_budget),
            str(log_budget),
            "req-2",
            "https://two.issuer.example/card",
            1,
            out_budget,
        ),
    )
    p1.start()
    p2.start()
    p1.join(timeout=15)
    p2.join(timeout=15)
    assert p1.exitcode == 0 and p2.exitcode == 0
    budget_outcomes = dict([out_budget.get(timeout=2), out_budget.get(timeout=2)])
    assert sorted(budget_outcomes.values()) == ["blocked", "dispatch"]
    assert len(DeterministicProviderDouble(log_budget).dispatches()) == 1


def test_kill_and_restart_controlled_process_preserves_reservation_and_blocks_redispatch(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "ingestion.sqlite"
    log_path = tmp_path / "dispatch.log"
    control(db_path, configured_limits=limits(run=2, month=2))
    context = multiprocessing.get_context("spawn")
    ready = context.Event()

    worker = context.Process(
        target=_crash_after_dispatch_worker,
        args=(str(db_path), str(log_path), "request-crash", True, ready),
    )
    worker.start()
    assert ready.wait(timeout=10), "worker did not reach post-dispatch state"
    assert worker.pid is not None
    os.kill(worker.pid, signal.SIGKILL)
    worker.join(timeout=10)
    assert worker.exitcode is not None and worker.exitcode != 0

    provider = DeterministicProviderDouble(log_path)
    assert len(provider.dispatches()) == 1

    # Reopen in a new controller instance after the process was killed.
    reopened = control(db_path, configured_limits=limits(run=2, month=2))
    pre_recovery_status = reopened.status("request-crash")
    assert pre_recovery_status is not None
    assert pre_recovery_status.operator_outcome == "possibly_dispatched_ambiguous"

    # Re-claiming the same request returns pending, never dispatching a second time.
    retry_claim = reopened.claim(
        request("request-crash"), policy_hash="policy-a", estimated_credits=2, now=NOW
    )
    assert retry_claim.state == "pending"
    assert len(provider.dispatches()) == 1

    # The 2 credits remain reserved, blocking any new request on the 2-credit run/month budget.
    new_claim = reopened.claim(
        request("request-after-crash", url="https://other.issuer.example/card"),
        policy_hash="policy-a",
        estimated_credits=1,
        now=NOW + timedelta(seconds=30),
    )
    assert new_claim.state == "blocked"

    # Operator runs narrow recovery to transition interrupted work to needs_reconciliation.
    recovered = reopened.recover_interrupted(now=NOW + timedelta(minutes=1))
    assert recovered == ["request-crash"]
    post_recovery_status = reopened.status("request-crash")
    assert post_recovery_status is not None
    assert post_recovery_status.state == "needs_reconciliation"
    assert post_recovery_status.operator_outcome == "possibly_dispatched_ambiguous"

    # Narrow audited reconciliation records retained failure evidence without new spend.
    reconciled_status = reopened.reconcile(
        "request-crash",
        result=FetchResult(
            request_id="request-crash",
            failure=FetchFailure(
                kind=FetchFailureKind.TIMEOUT,
                diagnostic="worker killed during provider dispatch; reconciled by operator",
            ),
        ),
        charged_credits=2,
        curator_id="curator-1",
        reason="confirmed provider log shows single scrape; retaining timeout failure",
        now=NOW + timedelta(minutes=2),
    )
    assert reconciled_status.state == "completed"
    assert reconciled_status.operator_outcome == "failed_with_retained_evidence"
    assert reconciled_status.charged_credits == 2
    assert len(provider.dispatches()) == 1


def test_sqlite_lock_contention_raises_typed_bounded_error(tmp_path: Path) -> None:
    db_path = tmp_path / "locked.sqlite"
    store = FinancialIngestionStore(db_path)
    store.put_source_policy(policy())

    # Open an exclusive transaction in another connection and keep it open.
    blocker = sqlite3.connect(db_path, timeout=0.1)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        # Use a short timeout on the store connection so contention fails fast.
        def fast_connect() -> sqlite3.Connection:
            conn = sqlite3.connect(db_path, timeout=0.05)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            return conn

        store._connect = fast_connect  # type: ignore[method-assign]
        controller = DurableAcquisitionControl(store, limits=limits())
        with pytest.raises(AcquisitionLockContentionError, match="bounded SQLite lock contention"):
            controller.claim(request(), policy_hash="policy-a", estimated_credits=1, now=NOW)
    finally:
        blocker.rollback()
        blocker.close()


def test_due_targets_are_stable_and_advance_only_on_successful_completions(
    tmp_path: Path,
) -> None:
    controller = control(tmp_path / "ingestion.sqlite")
    targets = [target("z"), target("a"), target("manual", manual_only=True)]
    assert controller.due_targets(targets, now=NOW, limit=10) == ["a", "z"]

    # A completed request that failed does NOT mark the target as fresh.
    failed_request = request("request-a-fail", url="https://issuer.example/a", run_id="run-a")
    assert (
        controller.claim(failed_request, policy_hash="policy-a", estimated_credits=1, now=NOW).state
        == "dispatch"
    )
    controller.complete(
        "request-a-fail",
        result=FetchResult(
            request_id="request-a-fail",
            failure=FetchFailure(kind=FetchFailureKind.TIMEOUT, diagnostic="timed out"),
        ),
        charged_credits=1,
        now=NOW,
    )
    assert controller.due_targets(targets, now=NOW, limit=10) == ["a", "z"]

    # A successful completion advances the target schedule by check_frequency_days.
    completed_request = request(
        "request-z", url="https://issuer.example/z", run_id="run-z"
    )
    assert (
        controller.claim(
            completed_request,
            policy_hash="policy-a",
            estimated_credits=1,
            now=NOW + timedelta(seconds=15),
        ).state
        == "dispatch"
    )
    controller.complete(
        "request-z",
        result=FetchResult(request_id="request-z", normalized_text="fresh content"),
        charged_credits=1,
        now=NOW + timedelta(seconds=15),
    )
    assert controller.due_targets(targets, now=NOW + timedelta(seconds=15), limit=1) == ["a"]
    assert controller.due_targets(
        targets, now=NOW + timedelta(days=1, seconds=15), limit=10
    ) == ["a", "z"]


def test_existing_v4_database_migrates_before_its_first_reservation(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 4")
    controller = control(path)
    assert (
        controller.claim(request(), policy_hash="policy-a", estimated_credits=1, now=NOW).state
        == "dispatch"
    )
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert connection.execute(
            "SELECT state FROM acquisition_requests WHERE request_id = 'request-1'"
        ).fetchone()[0] == "dispatching"
