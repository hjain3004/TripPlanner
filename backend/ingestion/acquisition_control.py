"""SQLite-backed reservations for bounded financial-document acquisition.

This module is intentionally transport-free.  It reserves before a provider
call, retains that reservation across a crash, and only replays a result that
was durably recorded by ``complete``.  It therefore makes no exactly-once
claim about an upstream paid provider.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit

from ingestion.contracts import FetchRequest, FetchResult, SourcePolicyRecord, WatchTarget
from ingestion.preflight import canonicalize_url
from ingestion.storage import (
    AcquisitionLockContentionError,
    FinancialIngestionStore,
    IngestionStoreError,
)

ClaimState = Literal["dispatch", "replay", "blocked", "pending", "conflict"]
RequestState = Literal["dispatching", "completed", "blocked", "needs_reconciliation"]
OperatorOutcomeKind = Literal[
    "completed_and_replayable",
    "reserved_not_yet_dispatched",
    "possibly_dispatched_ambiguous",
    "blocked_by_budget_or_delay",
    "failed_with_retained_evidence",
]


@dataclass(frozen=True)
class AcquisitionControlLimits:
    """Explicit, finite accounting limits supplied by the operator configuration."""

    per_request_credits: int
    per_run_credits: int
    per_month_credits: int
    pricing_version: str
    extraction_intent: str = "raw_html"

    def __post_init__(self) -> None:
        if min(self.per_request_credits, self.per_run_credits, self.per_month_credits) < 0:
            raise ValueError("acquisition credit limits cannot be negative")
        if not self.pricing_version:
            raise ValueError("acquisition pricing_version is required")
        if not self.extraction_intent:
            raise ValueError("acquisition extraction_intent is required")


@dataclass(frozen=True)
class DurableAcquisitionClaim:
    state: ClaimState
    safe_diagnostic: str
    replay_result: FetchResult | None = None


@dataclass(frozen=True)
class AcquisitionRequestStatus:
    request_id: str
    state: RequestState
    operator_outcome: OperatorOutcomeKind
    safe_diagnostic: str
    reserved_at: datetime
    dispatch_started_at: datetime | None
    completed_at: datetime | None
    estimated_credits: int
    charged_credits: int | None
    pricing_version: str
    replay_result: FetchResult | None


class DurableAcquisitionControl:
    """Durable, cross-process request reservation and replay control.

    ``FinancialIngestionStore`` supplies the database connection and its audit
    allocator.  Every mutation starts ``BEGIN IMMEDIATE`` before evaluating a
    budget or domain slot, so separate Python processes cannot spend the same
    allowance or dispatch against the same domain concurrently.
    """

    def __init__(self, store: FinancialIngestionStore, *, limits: AcquisitionControlLimits) -> None:
        self._store = store
        self._limits = limits

    @staticmethod
    def _month_key(now: datetime) -> str:
        return now.astimezone(UTC).strftime("%Y-%m")

    def _fingerprint(
        self, request: FetchRequest, *, policy_hash: str, estimated_credits: int
    ) -> str:
        request_payload = request.model_dump(mode="json", exclude={"run_id"})
        request_payload["canonical_url"] = canonicalize_url(request.canonical_url)
        payload: dict[str, object] = {
            "request": request_payload,
            "policy_hash": policy_hash,
            "estimated_credits": estimated_credits,
            "freshness_intent": "forced_fresh" if request.forced_freshness else "default_cache",
            "extraction_intent": {
                "evidence_kind": request.evidence_kind,
                "page_class": None if request.page_class is None else request.page_class.value,
                "mode": self._limits.extraction_intent,
            },
            "pricing_config": {
                "pricing_version": self._limits.pricing_version,
                "per_request_credits": self._limits.per_request_credits,
            },
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _domain(request: FetchRequest) -> str:
        domain = (urlsplit(request.canonical_url).hostname or "").lower()
        if not domain:
            raise ValueError("acquisition request has no hostname")
        return domain

    @staticmethod
    def _as_utc(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise IngestionStoreError("stored acquisition timestamp is not timezone-aware")
        return parsed.astimezone(UTC)

    def _policy(self, request: FetchRequest) -> SourcePolicyRecord | None:
        return self._store.get_source_policy(request.source_policy_id)

    def _audit(self, connection: object, *, request_id: str, event_type: str, payload: str) -> None:
        # ``_audit`` is the store's single collision-safe audit allocator. The
        # control tables share its transaction rather than maintaining a second
        # event stream with weaker ordering guarantees.
        self._store._audit(  # noqa: SLF001
            connection,  # type: ignore[arg-type]
            entity_type="acquisition_request",
            entity_id=request_id,
            event_type=event_type,
            payload=payload,
        )

    @staticmethod
    def _operator_outcome(
        *,
        state: str,
        dispatch_started_at: datetime | None,
        replay_result: FetchResult | None,
    ) -> OperatorOutcomeKind:
        if state == "completed":
            if replay_result is not None and replay_result.failure is not None:
                return "failed_with_retained_evidence"
            return "completed_and_replayable"
        if state == "blocked":
            return "blocked_by_budget_or_delay"
        if state == "dispatching" and dispatch_started_at is None:
            return "reserved_not_yet_dispatched"
        return "possibly_dispatched_ambiguous"

    @staticmethod
    def _claim_from_row(row: object) -> DurableAcquisitionClaim:
        values = row  # sqlite Row supports mapping access.
        state = str(values["state"])  # type: ignore[index]
        if state == "completed":
            result_json = values["result_payload"]  # type: ignore[index]
            if result_json is None:
                return DurableAcquisitionClaim(
                    "pending", "completed request has no replayable result"
                )
            result = FetchResult.model_validate_json(result_json)
            diagnostic = (
                "stored failed acquisition result replayed with retained evidence"
                if result.failure is not None
                else "stored acquisition result replayed"
            )
            return DurableAcquisitionClaim("replay", diagnostic, result)
        if state == "blocked":
            return DurableAcquisitionClaim("blocked", str(values["safe_diagnostic"]))  # type: ignore[index]
        if state in {"dispatching", "needs_reconciliation"}:
            return DurableAcquisitionClaim(
                "pending",
                "prior dispatch may have reached the provider; reconciliation is required",
            )
        raise IngestionStoreError(f"unknown acquisition request state: {state}")

    def _usage(self, connection: object, *, column: str, value: str) -> int:
        if column not in {"run_id", "month_key"}:
            raise ValueError("unsupported acquisition usage scope")
        row = connection.execute(  # type: ignore[attr-defined]
            "SELECT COALESCE(SUM(COALESCE(charged_credits, estimated_credits)), 0) "
            f"FROM acquisition_requests WHERE {column} = ? AND state != 'blocked'",
            (value,),
        ).fetchone()
        return int(row[0])

    def _record_blocked(
        self,
        connection: object,
        *,
        request: FetchRequest,
        canonical_url: str,
        fingerprint: str,
        policy_hash: str,
        domain: str,
        month_key: str,
        estimated_credits: int,
        timestamp: str,
        diagnostic: str,
    ) -> DurableAcquisitionClaim:
        connection.execute(  # type: ignore[attr-defined]
            "INSERT INTO acquisition_requests("
            "request_id, fingerprint, policy_hash, canonical_url, domain, run_id, "
            "month_key, state, estimated_credits, charged_credits, pricing_version, "
            "reserved_at, dispatch_started_at, completed_at, result_payload, "
            "safe_diagnostic) VALUES (?, ?, ?, ?, ?, ?, ?, 'blocked', ?, 0, ?, ?, "
            "NULL, ?, NULL, ?)",
            (
                request.request_id,
                fingerprint,
                policy_hash,
                canonical_url,
                domain,
                request.run_id,
                month_key,
                estimated_credits,
                self._limits.pricing_version,
                timestamp,
                timestamp,
                diagnostic,
            ),
        )
        self._audit(
            connection,
            request_id=request.request_id,
            event_type="blocked",
            payload=json.dumps(
                {
                    "diagnostic": diagnostic,
                    "domain": domain,
                    "estimated_credits": estimated_credits,
                },
                sort_keys=True,
            ),
        )
        return DurableAcquisitionClaim("blocked", diagnostic)

    @staticmethod
    def _raise_on_lock_error(error: sqlite3.OperationalError, action: str) -> None:
        if "locked" in str(error).lower() or "busy" in str(error).lower():
            raise AcquisitionLockContentionError(
                f"acquisition {action} failed due to bounded SQLite lock contention"
            ) from error
        raise IngestionStoreError(f"acquisition {action} database failure: {error}") from error

    def claim(
        self, request: FetchRequest, *, policy_hash: str, estimated_credits: int, now: datetime
    ) -> DurableAcquisitionClaim:
        if estimated_credits < 0:
            raise ValueError("estimated acquisition credits cannot be negative")
        if estimated_credits > self._limits.per_request_credits:
            return DurableAcquisitionClaim(
                "blocked", "estimated credits exceed per-request allowance"
            )
        policy = self._policy(request)
        if policy is None:
            return DurableAcquisitionClaim("blocked", "source policy is unavailable")
        if not policy.automated_access_permitted or policy.manual_only:
            return DurableAcquisitionClaim(
                "blocked", "source policy does not permit automated acquisition"
            )

        canonical_url = canonicalize_url(request.canonical_url)
        domain = self._domain(request)
        fingerprint = self._fingerprint(
            request, policy_hash=policy_hash, estimated_credits=estimated_credits
        )
        month_key = self._month_key(now)
        timestamp = now.astimezone(UTC).isoformat()
        try:
            with self._store._connect() as connection:  # noqa: SLF001
                connection.execute("BEGIN IMMEDIATE")
                prior = connection.execute(
                    "SELECT fingerprint, state, result_payload, safe_diagnostic "
                    "FROM acquisition_requests "
                    "WHERE request_id = ?",
                    (request.request_id,),
                ).fetchone()
                if prior is not None:
                    if str(prior["fingerprint"]) != fingerprint:
                        return DurableAcquisitionClaim(
                            "conflict",
                            "request id was already used for different acquisition inputs",
                        )
                    return self._claim_from_row(prior)

                unresolved = connection.execute(
                    "SELECT request_id FROM acquisition_requests "
                    "WHERE canonical_url IN (?, ?) "
                    "AND state IN ('dispatching', 'needs_reconciliation') "
                    "ORDER BY reserved_at DESC, request_id DESC LIMIT 1",
                    (canonical_url, request.canonical_url),
                ).fetchone()
                if unresolved is not None:
                    return DurableAcquisitionClaim(
                        "pending",
                        f"prior dispatch {unresolved['request_id']} may have reached the provider; "
                        "reconciliation is required",
                    )

                run_usage = self._usage(connection, column="run_id", value=request.run_id)
                month_usage = self._usage(connection, column="month_key", value=month_key)
                if run_usage + estimated_credits > self._limits.per_run_credits:
                    return self._record_blocked(
                        connection,
                        request=request,
                        canonical_url=canonical_url,
                        fingerprint=fingerprint,
                        policy_hash=policy_hash,
                        domain=domain,
                        month_key=month_key,
                        estimated_credits=estimated_credits,
                        timestamp=timestamp,
                        diagnostic="run credit allowance is exhausted",
                    )
                if month_usage + estimated_credits > self._limits.per_month_credits:
                    return self._record_blocked(
                        connection,
                        request=request,
                        canonical_url=canonical_url,
                        fingerprint=fingerprint,
                        policy_hash=policy_hash,
                        domain=domain,
                        month_key=month_key,
                        estimated_credits=estimated_credits,
                        timestamp=timestamp,
                        diagnostic="monthly credit allowance is exhausted",
                    )

                slot = connection.execute(
                    "SELECT next_dispatch_at FROM acquisition_domain_reservations WHERE domain = ?",
                    (domain,),
                ).fetchone()
                if slot is not None and self._as_utc(
                    str(slot["next_dispatch_at"])
                ) > now.astimezone(UTC):
                    return self._record_blocked(
                        connection,
                        request=request,
                        canonical_url=canonical_url,
                        fingerprint=fingerprint,
                        policy_hash=policy_hash,
                        domain=domain,
                        month_key=month_key,
                        estimated_credits=estimated_credits,
                        timestamp=timestamp,
                        diagnostic="source-domain minimum delay has not elapsed",
                    )

                next_dispatch = now.astimezone(UTC) + timedelta(
                    seconds=policy.minimum_delay_seconds
                )
                connection.execute(
                    "INSERT INTO acquisition_requests("
                    "request_id, fingerprint, policy_hash, canonical_url, domain, run_id, "
                    "month_key, state, estimated_credits, charged_credits, pricing_version, "
                    "reserved_at, dispatch_started_at, completed_at, result_payload, "
                    "safe_diagnostic) VALUES (?, ?, ?, ?, ?, ?, ?, 'dispatching', ?, NULL, ?, ?, "
                    "NULL, NULL, NULL, ?)",
                    (
                        request.request_id,
                        fingerprint,
                        policy_hash,
                        canonical_url,
                        domain,
                        request.run_id,
                        month_key,
                        estimated_credits,
                        self._limits.pricing_version,
                        timestamp,
                        "dispatch reserved before provider invocation",
                    ),
                )
                connection.execute(
                    "INSERT INTO acquisition_domain_reservations("
                    "domain, next_dispatch_at, request_id) "
                    "VALUES (?, ?, ?) ON CONFLICT(domain) DO UPDATE SET "
                    "next_dispatch_at = excluded.next_dispatch_at, "
                    "request_id = excluded.request_id",
                    (domain, next_dispatch.isoformat(), request.request_id),
                )
                self._audit(
                    connection,
                    request_id=request.request_id,
                    event_type="reserved",
                    payload=json.dumps(
                        {
                            "domain": domain,
                            "estimated_credits": estimated_credits,
                            "pricing_version": self._limits.pricing_version,
                        },
                        sort_keys=True,
                    ),
                )
        except sqlite3.OperationalError as error:
            self._raise_on_lock_error(error, "claim")
        return DurableAcquisitionClaim("dispatch", "dispatch reserved")

    def mark_dispatch_started(self, request_id: str, *, now: datetime) -> None:
        """Record that network dispatch is beginning so pre-dispatch crash vs in-flight is clear."""
        timestamp = now.astimezone(UTC).isoformat()
        try:
            with self._store._connect() as connection:  # noqa: SLF001
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT state, dispatch_started_at FROM acquisition_requests "
                    "WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if row is None:
                    raise IngestionStoreError("cannot start dispatch for an unreserved request")
                if str(row["state"]) != "dispatching":
                    raise IngestionStoreError(
                        f"cannot start dispatch for request in state {row['state']}"
                    )
                if row["dispatch_started_at"] is not None:
                    return
                connection.execute(
                    "UPDATE acquisition_requests SET dispatch_started_at = ?, "
                    "safe_diagnostic = ? WHERE request_id = ?",
                    (
                        timestamp,
                        "provider dispatch initiated; outcome is uncertain until completion",
                        request_id,
                    ),
                )
                self._audit(
                    connection,
                    request_id=request_id,
                    event_type="dispatch_started",
                    payload=json.dumps({"started_at": timestamp}, sort_keys=True),
                )
        except sqlite3.OperationalError as error:
            self._raise_on_lock_error(error, "dispatch_start")

    def complete(
        self, request_id: str, *, result: FetchResult, charged_credits: int | None, now: datetime
    ) -> None:
        if charged_credits is not None and charged_credits < 0:
            raise ValueError("charged acquisition credits cannot be negative")
        if result.request_id != request_id:
            raise ValueError("completion result request_id does not match reservation")
        # Optional URL validators deliberately reject a JSON null; omit absent
        # optionals so the exact stored result can be schema-validated on replay.
        payload = result.model_dump_json(exclude_none=True)
        timestamp = now.astimezone(UTC).isoformat()
        try:
            with self._store._connect() as connection:  # noqa: SLF001
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT state, result_payload, charged_credits, estimated_credits "
                    "FROM acquisition_requests WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if row is None:
                    raise IngestionStoreError("cannot complete an unreserved acquisition request")

                # A timeout or transport failure where provider charges are unknown or a request
                # failed after dispatch must never refund its credit reservation just because
                # content did not reach the next stage, nor may a 0-credit report zero out a
                # paid reservation.
                estimated = int(row["estimated_credits"])
                effective_charged = (
                    estimated
                    if charged_credits is None or charged_credits <= 0
                    else max(charged_credits, estimated)
                )

                if str(row["state"]) == "completed":
                    if (
                        str(row["result_payload"]) == payload
                        and row["charged_credits"] == effective_charged
                    ):
                        return
                    raise IngestionStoreError("conflicting acquisition completion")

                diagnostic = (
                    f"provider failure retained ({result.failure.kind.value}): "
                    f"{result.failure.diagnostic}"
                    if result.failure is not None
                    else "provider completion retained"
                )
                connection.execute(
                    "UPDATE acquisition_requests SET state = 'completed', result_payload = ?, "
                    "charged_credits = ?, completed_at = ?, safe_diagnostic = ? "
                    "WHERE request_id = ?",
                    (payload, effective_charged, timestamp, diagnostic, request_id),
                )
                self._audit(
                    connection,
                    request_id=request_id,
                    event_type="completed",
                    payload=json.dumps(
                        {
                            "charged_credits": effective_charged,
                            "failed": result.failure is not None,
                        },
                        sort_keys=True,
                    ),
                )
        except sqlite3.OperationalError as error:
            self._raise_on_lock_error(error, "complete")

    def mark_uncertain(
        self, request_id: str, *, diagnostic: str, now: datetime
    ) -> AcquisitionRequestStatus:
        """Explicitly mark a reserved/in-flight request as uncertain (`needs_reconciliation`).

        Credits and domain reservation remain spent; no automatic retry is authorized.
        """
        timestamp = now.astimezone(UTC).isoformat()
        safe_text = diagnostic.strip()[:500] or (
            "dispatch was interrupted; reconcile provider outcome before retrying"
        )
        try:
            with self._store._connect() as connection:  # noqa: SLF001
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT state FROM acquisition_requests WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if row is None:
                    raise IngestionStoreError("cannot mark an unreserved acquisition request")
                current_state = str(row["state"])
                if current_state == "completed":
                    raise IngestionStoreError(
                        "cannot mark a completed acquisition request as uncertain"
                    )
                if current_state != "needs_reconciliation":
                    connection.execute(
                        "UPDATE acquisition_requests SET state = 'needs_reconciliation', "
                        "safe_diagnostic = ? WHERE request_id = ?",
                        (safe_text, request_id),
                    )
                    self._audit(
                        connection,
                        request_id=request_id,
                        event_type="needs_reconciliation",
                        payload=json.dumps(
                            {"diagnostic": safe_text, "marked_at": timestamp}, sort_keys=True
                        ),
                    )
        except sqlite3.OperationalError as error:
            self._raise_on_lock_error(error, "mark_uncertain")
        status = self.status(request_id)
        if status is None:
            raise IngestionStoreError("acquisition request disappeared after update")
        return status

    def reconcile(
        self,
        request_id: str,
        *,
        result: FetchResult,
        charged_credits: int | None,
        curator_id: str,
        reason: str,
        now: datetime,
    ) -> AcquisitionRequestStatus:
        """Narrow, audited operator reconciliation of an uncertain or reserved request.

        Records the verified outcome (completed capture or retained failure evidence) without
        authorizing a new paid dispatch or releasing spent reservations.
        """
        if not curator_id.strip():
            raise ValueError("reconciliation requires a curator_id")
        if not reason.strip():
            raise ValueError("reconciliation requires a non-empty reason")
        if charged_credits is not None and charged_credits < 0:
            raise ValueError("charged acquisition credits cannot be negative")
        if result.request_id != request_id:
            raise ValueError("reconciled result request_id does not match reservation")
        payload = result.model_dump_json(exclude_none=True)
        timestamp = now.astimezone(UTC).isoformat()
        try:
            with self._store._connect() as connection:  # noqa: SLF001
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT state, result_payload, charged_credits, estimated_credits "
                    "FROM acquisition_requests WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if row is None:
                    raise IngestionStoreError("cannot reconcile an unreserved acquisition request")
                estimated = int(row["estimated_credits"])
                effective_charged = (
                    estimated
                    if charged_credits is None or charged_credits <= 0
                    else max(charged_credits, estimated)
                )
                if str(row["state"]) == "completed":
                    if (
                        str(row["result_payload"]) == payload
                        and row["charged_credits"] == effective_charged
                    ):
                        status = self.status(request_id)
                        assert status is not None
                        return status
                    raise IngestionStoreError("conflicting acquisition reconciliation")
                diagnostic = (
                    f"reconciled by {curator_id.strip()}: "
                    f"{'retained failure' if result.failure is not None else 'completed'} "
                    f"({reason.strip()[:200]})"
                )
                connection.execute(
                    "UPDATE acquisition_requests SET state = 'completed', result_payload = ?, "
                    "charged_credits = ?, completed_at = ?, safe_diagnostic = ? "
                    "WHERE request_id = ?",
                    (payload, effective_charged, timestamp, diagnostic, request_id),
                )
                self._audit(
                    connection,
                    request_id=request_id,
                    event_type="reconciled",
                    payload=json.dumps(
                        {
                            "charged_credits": effective_charged,
                            "curator_id": curator_id.strip(),
                            "failed": result.failure is not None,
                            "reconciled_at": timestamp,
                            "reason": reason.strip(),
                        },
                        sort_keys=True,
                    ),
                )
        except sqlite3.OperationalError as error:
            self._raise_on_lock_error(error, "reconcile")
        status = self.status(request_id)
        if status is None:
            raise IngestionStoreError("acquisition request disappeared after reconciliation")
        return status

    def status(self, request_id: str) -> AcquisitionRequestStatus | None:
        try:
            with self._store._connect() as connection:  # noqa: SLF001
                row = connection.execute(
                    "SELECT request_id, state, safe_diagnostic, reserved_at, "
                    "dispatch_started_at, completed_at, estimated_credits, charged_credits, "
                    "pricing_version, result_payload FROM acquisition_requests "
                    "WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
        except sqlite3.OperationalError as error:
            self._raise_on_lock_error(error, "status")
        if row is None:
            return None
        state = str(row["state"])
        if state not in {"dispatching", "completed", "blocked", "needs_reconciliation"}:
            raise IngestionStoreError(f"unknown acquisition request state: {state}")
        result_json = row["result_payload"]
        replay_result = (
            None if result_json is None else FetchResult.model_validate_json(result_json)
        )
        dispatch_started_at = (
            None
            if row["dispatch_started_at"] is None
            else self._as_utc(str(row["dispatch_started_at"]))
        )
        operator_outcome = self._operator_outcome(
            state=state,
            dispatch_started_at=dispatch_started_at,
            replay_result=replay_result,
        )
        return AcquisitionRequestStatus(
            request_id=str(row["request_id"]),
            state=state,  # type: ignore[arg-type]
            operator_outcome=operator_outcome,
            safe_diagnostic=str(row["safe_diagnostic"]),
            reserved_at=self._as_utc(str(row["reserved_at"])),
            dispatch_started_at=dispatch_started_at,
            completed_at=(
                None if row["completed_at"] is None else self._as_utc(str(row["completed_at"]))
            ),
            estimated_credits=int(row["estimated_credits"]),
            charged_credits=(
                None if row["charged_credits"] is None else int(row["charged_credits"])
            ),
            pricing_version=str(row["pricing_version"]),
            replay_result=replay_result,
        )

    def unresolved_for_url(self, canonical_url: str) -> AcquisitionRequestStatus | None:
        """Return the latest in-flight or reconciliation-required status for ``canonical_url``."""
        normalized_url = canonicalize_url(canonical_url)
        try:
            with self._store._connect() as connection:  # noqa: SLF001
                row = connection.execute(
                    "SELECT request_id FROM acquisition_requests "
                    "WHERE canonical_url IN (?, ?) "
                    "AND state IN ('dispatching', 'needs_reconciliation') "
                    "ORDER BY reserved_at DESC, request_id DESC LIMIT 1",
                    (normalized_url, canonical_url),
                ).fetchone()
        except sqlite3.OperationalError as error:
            self._raise_on_lock_error(error, "unresolved_for_url")
        if row is None:
            return None
        return self.status(str(row["request_id"]))

    def recover_interrupted(self, *, now: datetime, include_unstarted: bool = True) -> list[str]:
        """Mark outstanding dispatches for explicit operator reconciliation.

        This never releases the associated credit reservation or makes a
        request dispatchable again. The transport may have received the call.
        When ``include_unstarted`` is False, requests that were reserved but
        provably never entered ``mark_dispatch_started`` remain in their
        ``reserved_not_yet_dispatched`` state until explicitly reconciled or
        included.
        """
        timestamp = now.astimezone(UTC).isoformat()
        try:
            with self._store._connect() as connection:  # noqa: SLF001
                connection.execute("BEGIN IMMEDIATE")
                query = (
                    "SELECT request_id, dispatch_started_at FROM acquisition_requests "
                    "WHERE state = 'dispatching' "
                )
                if not include_unstarted:
                    query += "AND dispatch_started_at IS NOT NULL "
                query += "ORDER BY reserved_at, request_id"
                rows = connection.execute(query).fetchall()
                request_ids = [str(row["request_id"]) for row in rows]
                for row in rows:
                    request_id = str(row["request_id"])
                    started = row["dispatch_started_at"] is not None
                    diagnostic = (
                        "dispatch was interrupted after network start; "
                        "reconcile provider outcome before retrying"
                        if started
                        else (
                            "reservation was interrupted before completion; "
                            "reconcile before retrying"
                        )
                    )
                    connection.execute(
                        "UPDATE acquisition_requests SET state = 'needs_reconciliation', "
                        "safe_diagnostic = ? WHERE request_id = ?",
                        (diagnostic, request_id),
                    )
                    self._audit(
                        connection,
                        request_id=request_id,
                        event_type="needs_reconciliation",
                        payload=json.dumps(
                            {"dispatch_started": started, "marked_at": timestamp},
                            sort_keys=True,
                        ),
                    )
        except sqlite3.OperationalError as error:
            self._raise_on_lock_error(error, "recover_interrupted")
        return request_ids

    def due_targets(
        self, targets: Sequence[WatchTarget], *, now: datetime, limit: int
    ) -> list[str]:
        if limit < 0:
            raise ValueError("due target limit cannot be negative")
        if limit == 0:
            return []
        eligible: list[tuple[datetime, str]] = []
        try:
            with self._store._connect() as connection:  # noqa: SLF001
                for target in targets:
                    if target.status != "active" or target.manual_only:
                        continue
                    # Only successful completed acquisitions advance the target's watch
                    # schedule; failed captures with retained evidence remain due.
                    normalized_url = canonicalize_url(target.canonical_url)
                    rows = connection.execute(
                        "SELECT completed_at, result_payload FROM acquisition_requests "
                        "WHERE canonical_url IN (?, ?) AND state = 'completed' "
                        "ORDER BY completed_at DESC, request_id DESC",
                        (normalized_url, target.canonical_url),
                    ).fetchall()
                    last_success_at: datetime | None = None
                    for row in rows:
                        payload = row["result_payload"]
                        if payload is not None:
                            parsed = FetchResult.model_validate_json(payload)
                            if parsed.failure is not None:
                                continue
                        if row["completed_at"] is not None:
                            last_success_at = self._as_utc(str(row["completed_at"]))
                            break
                    if last_success_at is None:
                        due_at = datetime.min.replace(tzinfo=UTC)
                    else:
                        due_at = last_success_at + timedelta(days=target.check_frequency_days)
                    if due_at <= now.astimezone(UTC):
                        eligible.append((due_at, target.target_id))
        except sqlite3.OperationalError as error:
            self._raise_on_lock_error(error, "due_targets")
        eligible.sort(key=lambda item: (item[0], item[1]))
        return [target_id for _, target_id in eligible[:limit]]
