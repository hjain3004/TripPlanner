"""Acquisition orchestration and durable control protocols for financial ingestion."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import (
    FetchAttempt,
    FetchFailureKind,
    FetchRequest,
    FetchResult,
    PageKind,
    SnapshotBundle,
    SourcePolicyRecord,
    WatchTarget,
)
from ingestion.diff import diff_text
from ingestion.extraction_runtime import (
    ExtractionMode,
    ExtractionRuntimeConfig,
    FinancialExtractionRuntime,
)
from ingestion.firecrawl_transport import (
    FirecrawlScrapeRequest,
    FirecrawlTransport,
)
from ingestion.preflight import RobotsRules, SourcePreflight
from ingestion.review_rows import SUPPORTED_TABLES, SeedRowError, SeedRowSource
from ingestion.snapshots import SnapshotService
from ingestion.storage import FinancialIngestionStore
from ingestion.validation import canonical_row_hash

if TYPE_CHECKING:
    from ingestion.acquisition_control import DurableAcquisitionControl

AcquisitionClaimState = Literal["dispatch", "replay", "blocked", "pending", "conflict"]
AcquisitionOutcomeState = Literal[
    "completed",
    "unchanged",
    "blocked",
    "failed",
    "needs_reconciliation",
]


class AcquisitionClaim(Protocol):
    """Result of reserving a single acquisition request before dispatch."""

    @property
    def state(self) -> AcquisitionClaimState: ...

    @property
    def safe_diagnostic(self) -> str: ...

    @property
    def replay_result(self) -> FetchResult | None: ...


class AcquisitionControl(Protocol):
    """Durable pre-dispatch control for source rate limits, credits, and replay."""

    def claim(
        self,
        request: FetchRequest,
        *,
        policy_hash: str,
        estimated_credits: int,
        now: datetime,
    ) -> AcquisitionClaim: ...

    def mark_dispatch_started(self, request_id: str, *, now: datetime) -> None: ...

    def complete(
        self,
        request_id: str,
        *,
        result: FetchResult,
        charged_credits: int | None,
        now: datetime,
    ) -> None: ...

    def due_targets(
        self,
        targets: Sequence[WatchTarget],
        *,
        now: datetime,
        limit: int,
    ) -> list[str]: ...


class AcquisitionOutcome(Protocol):
    """Outcome of acquiring and optionally extracting one watch target."""

    @property
    def state(self) -> AcquisitionOutcomeState: ...

    @property
    def snapshot_id(self) -> str | None: ...

    @property
    def proposal_ids(self) -> tuple[str, ...]: ...


class AcquisitionService(Protocol):
    """End-to-end acquisition from approved watch target to review queue."""

    async def acquire(
        self,
        target_id: str,
        *,
        client_event_id: str,
    ) -> AcquisitionOutcome: ...


class RetainedCaptureTransport:
    """Offline Firecrawl transport that serves a retained provider envelope or HTML file.

    Used by operator acceptance workflows and CLI replay runs before live provider
    activation is authorized. Every invocation is recorded in ``calls`` so callers
    can verify whether a provider call was made or replayed from durable control.
    """

    def __init__(
        self,
        payloads: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    ) -> None:
        if isinstance(payloads, Mapping):
            self._payloads: list[Mapping[str, Any]] = [dict(payloads)]
        else:
            self._payloads = [dict(item) for item in payloads]
        if not self._payloads:
            raise ValueError("RetainedCaptureTransport requires at least one retained payload")
        self.calls: list[FirecrawlScrapeRequest] = []

    @classmethod
    def from_file(
        cls,
        path: Path,
        *,
        canonical_url: str,
        status_code: int = 200,
        content_type: str = "text/html",
        credits_cost: int = 1,
        cache_state: str = "retained_capture",
    ) -> RetainedCaptureTransport:
        raw_text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            loaded = json.loads(raw_text)
            if isinstance(loaded, list):
                return cls(loaded)
            if isinstance(loaded, dict):
                return cls(loaded)
            raise ValueError("retained JSON capture must be a mapping or list of mappings")
        return cls(
            {
                "success": True,
                "data": {
                    "rawHtml": raw_text,
                    "metadata": {
                        "url": canonical_url,
                        "sourceURL": canonical_url,
                        "statusCode": status_code,
                        "contentType": content_type,
                        "cacheState": cache_state,
                        "provider": {"creditsCost": credits_cost},
                    },
                },
            }
        )

    async def scrape(self, request: FirecrawlScrapeRequest) -> dict[str, Any]:
        index = min(len(self.calls), len(self._payloads) - 1)
        self.calls.append(request)
        return copy.deepcopy(dict(self._payloads[index]))


@dataclass(frozen=True)
class AcquisitionResultRecord:
    """Concrete operator-readable outcome of acquiring one watch target."""

    state: AcquisitionOutcomeState
    snapshot_id: str | None
    proposal_ids: tuple[str, ...]
    target_id: str = ""
    request_id: str = ""
    client_event_id: str = ""
    operator_outcome: str = ""
    extraction_mode: str = "disabled"
    extraction_status: str = "not_run"
    llm_calls: int = 0
    replayed_fetch: bool = False
    provider_envelope_sha256: str | None = None
    raw_sha256: str | None = None
    normalized_sha256: str | None = None
    evidence_fidelity: str | None = None
    diagnostic: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "target_id": self.target_id,
            "request_id": self.request_id,
            "client_event_id": self.client_event_id,
            "operator_outcome": self.operator_outcome,
            "snapshot_id": self.snapshot_id,
            "proposal_ids": list(self.proposal_ids),
            "extraction_mode": self.extraction_mode,
            "extraction_status": self.extraction_status,
            "llm_calls": self.llm_calls,
            "replayed_fetch": self.replayed_fetch,
            "provider_envelope_sha256": self.provider_envelope_sha256,
            "raw_sha256": self.raw_sha256,
            "normalized_sha256": self.normalized_sha256,
            "evidence_fidelity": self.evidence_fidelity,
            "diagnostic": self.diagnostic,
        }


@dataclass(frozen=True)
class RefreshDueBatchResult:
    """Bounded ``refresh-due`` execution result across due watch targets."""

    limit: int
    selected_target_ids: tuple[str, ...]
    outcomes: tuple[AcquisitionResultRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "completed",
            "limit": self.limit,
            "selected_target_ids": list(self.selected_target_ids),
            "outcomes": [outcome.to_dict() for outcome in self.outcomes],
            "counts": {
                "selected": len(self.selected_target_ids),
                "completed": sum(1 for item in self.outcomes if item.state == "completed"),
                "unchanged": sum(1 for item in self.outcomes if item.state == "unchanged"),
                "blocked": sum(1 for item in self.outcomes if item.state == "blocked"),
                "failed": sum(1 for item in self.outcomes if item.state == "failed"),
                "needs_reconciliation": sum(
                    1 for item in self.outcomes if item.state == "needs_reconciliation"
                ),
                "llm_calls": sum(item.llm_calls for item in self.outcomes),
            },
        }


def _bind_scripted_response(raw_response: object, snapshot: SnapshotBundle) -> object:
    """Fill placeholder snapshot identity or quote offsets in a scripted dict response.

    If a response already supplies explicit non-placeholder ``snapshot_id``,
    ``snapshot_hash``, and offsets, they are preserved verbatim so validation
    can still reject mismatched lineage or bad offsets.
    """
    if not isinstance(raw_response, Mapping):
        return raw_response
    copied: dict[str, Any] = copy.deepcopy(dict(raw_response))
    fields = copied.get("fields")
    if not isinstance(fields, list):
        return copied
    for field in fields:
        if not isinstance(field, dict):
            continue
        spans = field.get("evidence_spans")
        if not isinstance(spans, list):
            continue
        for span in spans:
            if not isinstance(span, dict):
                continue
            if span.get("snapshot_id") in {None, "", "__SNAPSHOT_ID__"}:
                span["snapshot_id"] = snapshot.snapshot_id
            if span.get("snapshot_hash") in {None, "", "__SNAPSHOT_HASH__"}:
                span["snapshot_hash"] = snapshot.normalized_sha256
            quote = span.get("quote")
            if (
                isinstance(quote, str)
                and quote
                and (span.get("normalized_start") is None or span.get("normalized_end") is None)
            ):
                start = snapshot.canonical_markdown.find(quote)
                if start >= 0:
                    span["normalized_start"] = start
                    span["normalized_end"] = start + len(quote)
    return copied


def _resolve_target_row(
    fact_id: str,
    *,
    seeds: SeedRowSource | None,
    custom_rows: Mapping[str, tuple[str, dict[str, Any]]] | None,
) -> tuple[str, dict[str, Any], str]:
    if custom_rows is not None and fact_id in custom_rows:
        table_name, row = custom_rows[fact_id]
        row_copy = copy.deepcopy(row)
        return table_name, row_copy, canonical_row_hash(row_copy)
    if seeds is None:
        raise SeedRowError("current_row_missing", f"no seed source configured for {fact_id}")
    for table_name in SUPPORTED_TABLES:
        try:
            row = seeds.current_row(table_name, fact_id)
            return table_name, row, canonical_row_hash(row)
        except SeedRowError as error:
            if error.code == "current_row_missing":
                continue
            raise
    raise SeedRowError("current_row_missing", f"missing target row across seed tables: {fact_id}")


class DurableAcquisitionService:
    """Concrete orchestration from approved watch target to snapshot, diff, and proposal queue."""

    def __init__(
        self,
        *,
        store: FinancialIngestionStore,
        artifacts: ContentAddressedStore,
        control: DurableAcquisitionControl,
        transport: FirecrawlTransport
        | Callable[[WatchTarget, SourcePolicyRecord], FirecrawlTransport],
        extraction_config: ExtractionRuntimeConfig | None = None,
        extraction_configs_by_target: Mapping[str, ExtractionRuntimeConfig] | None = None,
        seeds_dir: Path | None = None,
        custom_rows: Mapping[str, tuple[str, dict[str, Any]]] | None = None,
        robots_by_domain: Mapping[str, RobotsRules] | None = None,
        default_robots: RobotsRules | None = None,
        preflight: SourcePreflight | None = None,
        firecrawl_enabled: bool = False,
        estimated_credits: int = 1,
        max_bytes: int = 2_000_000,
        max_pages: int = 5,
        timeout_seconds: int = 20,
        forced_freshness: bool = False,
        run_id: str = "firecrawl-acquire",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.artifacts = artifacts
        self.control = control
        self._transport = transport
        self.extraction_config = extraction_config or ExtractionRuntimeConfig(
            mode=ExtractionMode.DISABLED
        )
        self.extraction_configs_by_target = dict(extraction_configs_by_target or {})
        self.seeds = None if seeds_dir is None else SeedRowSource(seeds_dir)
        self.custom_rows = dict(custom_rows or {})
        self.robots_by_domain = {k.lower(): v for k, v in (robots_by_domain or {}).items()}
        self.default_robots = default_robots
        self.preflight = preflight or SourcePreflight()
        self.firecrawl_enabled = firecrawl_enabled
        self.estimated_credits = estimated_credits
        self.max_bytes = max_bytes
        self.max_pages = max_pages
        self.timeout_seconds = timeout_seconds
        self.forced_freshness = forced_freshness
        self.run_id = run_id
        self.now = now or (lambda: datetime.now(UTC))

    @staticmethod
    def request_id_for(target_id: str, *, client_event_id: str) -> str:
        digest = hashlib.sha256(f"{target_id}:{client_event_id}".encode()).hexdigest()[:16]
        return f"acq:{target_id}:{digest}"

    def _resolve_transport(
        self, target: WatchTarget, policy: SourcePolicyRecord
    ) -> FirecrawlTransport:
        if callable(self._transport):
            return self._transport(target, policy)
        return self._transport

    def _resolve_robots(self, policy: SourcePolicyRecord) -> RobotsRules | None:
        domain_rules = self.robots_by_domain.get(policy.domain.lower())
        if domain_rules is not None:
            return domain_rules
        return self.default_robots

    def _resolve_extraction_config(self, target_id: str) -> ExtractionRuntimeConfig:
        return self.extraction_configs_by_target.get(target_id, self.extraction_config)

    async def acquire(
        self,
        target_id: str,
        *,
        client_event_id: str,
    ) -> AcquisitionResultRecord:
        event_key = client_event_id.strip()
        if not event_key:
            raise ValueError("client_event_id must not be blank")
        request_id = self.request_id_for(target_id, client_event_id=event_key)
        ext_config = self._resolve_extraction_config(target_id)

        target = self.store.get_watch_target(target_id)
        if target is None:
            return AcquisitionResultRecord(
                state="blocked",
                snapshot_id=None,
                proposal_ids=(),
                target_id=target_id,
                request_id=request_id,
                client_event_id=event_key,
                operator_outcome="blocked_by_policy_or_target",
                extraction_mode=ext_config.mode.value,
                diagnostic=f"unknown watch target: {target_id}",
            )
        if (
            target.status != "active"
            or target.manual_only
            or target.preferred_backend != "firecrawl"
        ):
            return AcquisitionResultRecord(
                state="blocked",
                snapshot_id=None,
                proposal_ids=(),
                target_id=target_id,
                request_id=request_id,
                client_event_id=event_key,
                operator_outcome="blocked_by_policy_or_target",
                extraction_mode=ext_config.mode.value,
                diagnostic="watch target is not eligible for automated Firecrawl acquisition",
            )
        if target.page_kind not in {PageKind.CARD_PAGE, PageKind.OFFER_PAGE}:
            return AcquisitionResultRecord(
                state="blocked",
                snapshot_id=None,
                proposal_ids=(),
                target_id=target_id,
                request_id=request_id,
                client_event_id=event_key,
                operator_outcome="blocked_by_policy_or_target",
                extraction_mode=ext_config.mode.value,
                diagnostic="Firecrawl acquisition only accepts approved HTML page classes",
            )
        policy = self.store.get_source_policy(target.source_policy_id)
        if policy is None or policy.manual_only or not policy.automated_access_permitted:
            return AcquisitionResultRecord(
                state="blocked",
                snapshot_id=None,
                proposal_ids=(),
                target_id=target_id,
                request_id=request_id,
                client_event_id=event_key,
                operator_outcome="blocked_by_policy_or_target",
                extraction_mode=ext_config.mode.value,
                diagnostic="source policy does not permit automated Firecrawl acquisition",
            )

        prior_status = self.control.status(request_id)
        if prior_status is not None and prior_status.state in {
            "dispatching",
            "needs_reconciliation",
        }:
            return AcquisitionResultRecord(
                state="needs_reconciliation",
                snapshot_id=None,
                proposal_ids=(),
                target_id=target_id,
                request_id=request_id,
                client_event_id=event_key,
                operator_outcome=prior_status.operator_outcome,
                extraction_mode=ext_config.mode.value,
                diagnostic=prior_status.safe_diagnostic,
            )
        if prior_status is None:
            unresolved = self.control.unresolved_for_url(target.canonical_url)
            if unresolved is not None:
                return AcquisitionResultRecord(
                    state="needs_reconciliation",
                    snapshot_id=None,
                    proposal_ids=(),
                    target_id=target_id,
                    request_id=unresolved.request_id,
                    client_event_id=event_key,
                    operator_outcome=unresolved.operator_outcome,
                    extraction_mode=ext_config.mode.value,
                    diagnostic=unresolved.safe_diagnostic,
                )

        was_completed = prior_status is not None and prior_status.state == "completed"
        before_capture = self.store.latest_snapshot(target_id)

        fetch_request = FetchRequest(
            request_id=request_id,
            canonical_url=target.canonical_url,
            source_policy_id=policy.policy_id,
            evidence_kind="official_page",
            page_class=target.page_kind,
            max_bytes=self.max_bytes,
            max_pages=self.max_pages,
            timeout_seconds=self.timeout_seconds,
            forced_freshness=self.forced_freshness,
            run_id=self.run_id,
        )
        from ingestion.firecrawl_backend import FirecrawlBackend

        backend = FirecrawlBackend(
            artifacts=self.artifacts,
            policy=policy,
            transport=self._resolve_transport(target, policy),
            robots=self._resolve_robots(policy),
            preflight=self.preflight,
            control=self.control,
            enabled=self.firecrawl_enabled,
            estimated_credits=self.estimated_credits,
            now=self.now,
        )
        result = await backend.fetch(fetch_request)
        post_status = self.control.status(request_id)
        started_at = post_status.reserved_at if post_status is not None else self.now()
        ended_at = (
            post_status.completed_at
            if (post_status is not None and post_status.completed_at is not None)
            else started_at
        )
        settled_credits = (
            post_status.charged_credits
            if (post_status is not None and post_status.charged_credits is not None)
            else (
                0 if result.failure is not None and post_status is None else self.estimated_credits
            )
        )
        operator_outcome = (
            post_status.operator_outcome
            if post_status is not None
            else (
                "failed_with_retained_evidence"
                if result.failure is not None
                else "completed_and_replayable"
            )
        )

        if result.failure is not None:
            if "already used for different acquisition inputs" in result.failure.diagnostic:
                return AcquisitionResultRecord(
                    state="failed",
                    snapshot_id=None,
                    proposal_ids=(),
                    target_id=target_id,
                    request_id=request_id,
                    client_event_id=event_key,
                    operator_outcome="failed_with_retained_evidence",
                    extraction_mode=ext_config.mode.value,
                    replayed_fetch=False,
                    diagnostic=result.failure.diagnostic,
                )
            was_dispatched = post_status is not None and post_status.state in {
                "completed",
                "dispatching",
                "needs_reconciliation",
            }
            response_class: Literal["blocked", "failure"] = (
                "blocked"
                if (
                    not was_dispatched
                    and result.failure.kind
                    in {
                        FetchFailureKind.POLICY_BLOCKED,
                        FetchFailureKind.ROBOTS_BLOCKED,
                        FetchFailureKind.BUDGET_EXHAUSTED,
                    }
                )
                else "failure"
            )
            if post_status is not None:
                failed_attempt = FetchAttempt(
                    attempt_id=f"attempt:{request_id}",
                    request_id=request_id,
                    backend="firecrawl",
                    backend_version=backend.backend_version,
                    started_at=started_at,
                    ended_at=ended_at,
                    **({"final_url": result.final_url} if result.final_url is not None else {}),
                    response_class=response_class,
                    failure=result.failure,
                    retry_index=0,
                    credits_reserved=self.estimated_credits if was_dispatched else 0,
                    credits_settled=settled_credits,
                )
                self.store.put_fetch_attempt(failed_attempt)
            if (
                post_status is not None
                and post_status.state in {"dispatching", "needs_reconciliation"}
            ) or "reconciliation" in result.failure.diagnostic.lower():
                return AcquisitionResultRecord(
                    state="needs_reconciliation",
                    snapshot_id=None,
                    proposal_ids=(),
                    target_id=target_id,
                    request_id=request_id,
                    client_event_id=event_key,
                    operator_outcome="possibly_dispatched_ambiguous",
                    extraction_mode=ext_config.mode.value,
                    replayed_fetch=was_completed,
                    diagnostic=result.failure.diagnostic,
                )
            if response_class == "blocked":
                return AcquisitionResultRecord(
                    state="blocked",
                    snapshot_id=None,
                    proposal_ids=(),
                    target_id=target_id,
                    request_id=request_id,
                    client_event_id=event_key,
                    operator_outcome="blocked_by_budget_or_delay",
                    extraction_mode=ext_config.mode.value,
                    replayed_fetch=was_completed,
                    diagnostic=result.failure.diagnostic,
                )
            return AcquisitionResultRecord(
                state="failed",
                snapshot_id=None,
                proposal_ids=(),
                target_id=target_id,
                request_id=request_id,
                client_event_id=event_key,
                operator_outcome=operator_outcome,
                extraction_mode=ext_config.mode.value,
                replayed_fetch=was_completed,
                diagnostic=result.failure.diagnostic,
            )

        # Persist the fetched material and snapshot BEFORE running extraction so an extraction
        # failure or process restart never requires another Firecrawl scrape.
        attempt = FetchAttempt(
            attempt_id=f"attempt:{request_id}",
            request_id=request_id,
            backend="firecrawl",
            backend_version=backend.backend_version,
            started_at=started_at,
            ended_at=ended_at,
            **({"final_url": result.final_url} if result.final_url is not None else {}),
            response_class="success",
            retry_index=0,
            credits_reserved=self.estimated_credits,
            credits_settled=settled_credits,
        )
        snapshots = SnapshotService(
            store=self.store, artifacts=self.artifacts, now=lambda: started_at
        )
        snapshot = snapshots.capture(target_id=target_id, result=result, attempt=attempt)
        if snapshot is None:
            return AcquisitionResultRecord(
                state="failed",
                snapshot_id=None,
                proposal_ids=(),
                target_id=target_id,
                request_id=request_id,
                client_event_id=event_key,
                operator_outcome="failed_with_retained_evidence",
                extraction_mode=ext_config.mode.value,
                replayed_fetch=was_completed,
                diagnostic="fetched result did not produce an immutable snapshot",
            )

        envelope_sha = (
            snapshot.provider_envelope_artifact.sha256
            if snapshot.provider_envelope_artifact is not None
            else None
        )

        # Determine the true predecessor snapshot even if this request_id already persisted
        # `snapshot` on an earlier attempt that failed during extraction, or if a newer
        # snapshot was captured for the same target after this event completed.
        if any(item.request_id == request_id for item in snapshot.attempts):
            previous_snapshot = (
                self.store.get_snapshot(snapshot.supersedes_snapshot_id)
                if snapshot.supersedes_snapshot_id is not None
                else None
            )
        elif was_completed:
            previous_snapshot = snapshot
        elif before_capture is None:
            previous_snapshot = None
        else:
            previous_snapshot = before_capture

        diff = diff_text(
            None if previous_snapshot is None else previous_snapshot.canonical_markdown,
            snapshot.canonical_markdown,
        )
        if not diff.changed:
            return AcquisitionResultRecord(
                state="unchanged",
                snapshot_id=snapshot.snapshot_id,
                proposal_ids=(),
                target_id=target_id,
                request_id=request_id,
                client_event_id=event_key,
                operator_outcome=operator_outcome,
                extraction_mode=ext_config.mode.value,
                extraction_status="unchanged",
                llm_calls=0,
                replayed_fetch=was_completed,
                provider_envelope_sha256=envelope_sha,
                raw_sha256=snapshot.raw_sha256,
                normalized_sha256=snapshot.normalized_sha256,
                evidence_fidelity=snapshot.evidence_fidelity,
                diagnostic="normalized snapshot is unchanged; extraction skipped",
            )

        if ext_config.mode is ExtractionMode.DISABLED:
            return AcquisitionResultRecord(
                state="completed",
                snapshot_id=snapshot.snapshot_id,
                proposal_ids=(),
                target_id=target_id,
                request_id=request_id,
                client_event_id=event_key,
                operator_outcome=operator_outcome,
                extraction_mode=ext_config.mode.value,
                extraction_status="disabled",
                llm_calls=0,
                replayed_fetch=was_completed,
                provider_envelope_sha256=envelope_sha,
                raw_sha256=snapshot.raw_sha256,
                normalized_sha256=snapshot.normalized_sha256,
                evidence_fidelity=snapshot.evidence_fidelity,
                diagnostic="snapshot persisted; extraction disabled",
            )

        proposal_ids: list[str] = []
        total_llm_calls = 0
        last_status = "proposal_pending"
        for index, fact_id in enumerate(target.target_fact_ids):
            try:
                target_table, current_row, current_row_hash = _resolve_target_row(
                    fact_id, seeds=self.seeds, custom_rows=self.custom_rows
                )
            except SeedRowError as error:
                return AcquisitionResultRecord(
                    state="failed",
                    snapshot_id=snapshot.snapshot_id,
                    proposal_ids=tuple(proposal_ids),
                    target_id=target_id,
                    request_id=request_id,
                    client_event_id=event_key,
                    operator_outcome=operator_outcome,
                    extraction_mode=ext_config.mode.value,
                    extraction_status="extraction_failed",
                    llm_calls=total_llm_calls,
                    replayed_fetch=was_completed,
                    provider_envelope_sha256=envelope_sha,
                    raw_sha256=snapshot.raw_sha256,
                    normalized_sha256=snapshot.normalized_sha256,
                    evidence_fidelity=snapshot.evidence_fidelity,
                    diagnostic=str(error),
                )

            per_fact_config = ext_config
            if ext_config.mode in {
                ExtractionMode.SCRIPTED_REPLAY,
                ExtractionMode.CURATOR_AUTHORED,
            }:
                response_index = min(index, len(ext_config.responses) - 1)
                bound_response = _bind_scripted_response(
                    ext_config.responses[response_index], snapshot
                )
                per_fact_config = ExtractionRuntimeConfig(
                    mode=ext_config.mode,
                    responses=(bound_response,),
                    extractor_version=ext_config.extractor_version,
                )

            fact_event_id = (
                event_key if len(target.target_fact_ids) == 1 else f"{event_key}:{fact_id}"
            )
            runtime_outcome = FinancialExtractionRuntime(
                config=per_fact_config,
                store=self.store,
                artifacts=self.artifacts,
                now=self.now,
            ).extract_snapshot(
                target_table=target_table,
                target_id=fact_id,
                current_row=current_row,
                current_row_hash=current_row_hash,
                snapshot=snapshot,
                previous_snapshot=previous_snapshot,
                client_event_id=fact_event_id,
                manual_capture=False,
            )
            total_llm_calls += runtime_outcome.outcome.calls
            last_status = runtime_outcome.outcome.status
            if runtime_outcome.outcome.status != "proposal_pending" or (
                runtime_outcome.outcome.proposal is None
            ):
                return AcquisitionResultRecord(
                    state="failed",
                    snapshot_id=snapshot.snapshot_id,
                    proposal_ids=tuple(proposal_ids),
                    target_id=target_id,
                    request_id=request_id,
                    client_event_id=event_key,
                    operator_outcome=operator_outcome,
                    extraction_mode=ext_config.mode.value,
                    extraction_status=runtime_outcome.outcome.status,
                    llm_calls=total_llm_calls,
                    replayed_fetch=was_completed,
                    provider_envelope_sha256=envelope_sha,
                    raw_sha256=snapshot.raw_sha256,
                    normalized_sha256=snapshot.normalized_sha256,
                    evidence_fidelity=snapshot.evidence_fidelity,
                    diagnostic=runtime_outcome.outcome.diagnostic
                    or f"extraction ended with status {runtime_outcome.outcome.status}",
                )
            proposal_ids.append(runtime_outcome.outcome.proposal.proposal_id)

        return AcquisitionResultRecord(
            state="completed",
            snapshot_id=snapshot.snapshot_id,
            proposal_ids=tuple(proposal_ids),
            target_id=target_id,
            request_id=request_id,
            client_event_id=event_key,
            operator_outcome=operator_outcome,
            extraction_mode=ext_config.mode.value,
            extraction_status=last_status,
            llm_calls=total_llm_calls,
            replayed_fetch=was_completed,
            provider_envelope_sha256=envelope_sha,
            raw_sha256=snapshot.raw_sha256,
            normalized_sha256=snapshot.normalized_sha256,
            evidence_fidelity=snapshot.evidence_fidelity,
            diagnostic="snapshot persisted and draft proposal queued for curator review",
        )

    def acquire_sync(
        self,
        target_id: str,
        *,
        client_event_id: str,
    ) -> AcquisitionResultRecord:
        return asyncio.run(self.acquire(target_id, client_event_id=client_event_id))

    async def refresh_due(
        self,
        *,
        limit: int,
        client_event_prefix: str,
        targets: Sequence[WatchTarget] | None = None,
    ) -> RefreshDueBatchResult:
        if limit < 0:
            raise ValueError("limit cannot be negative")
        prefix = client_event_prefix.strip()
        if not prefix:
            raise ValueError("client_event_prefix must not be blank")
        candidate_targets = (
            list(targets) if targets is not None else self.store.list_watch_targets()
        )
        due_ids = tuple(self.control.due_targets(candidate_targets, now=self.now(), limit=limit))
        outcomes: list[AcquisitionResultRecord] = []
        for target_id in due_ids:
            outcome = await self.acquire(
                target_id,
                client_event_id=f"{prefix}:{target_id}",
            )
            outcomes.append(outcome)
        return RefreshDueBatchResult(
            limit=limit,
            selected_target_ids=due_ids,
            outcomes=tuple(outcomes),
        )

    def refresh_due_sync(
        self,
        *,
        limit: int,
        client_event_prefix: str,
        targets: Sequence[WatchTarget] | None = None,
    ) -> RefreshDueBatchResult:
        return asyncio.run(
            self.refresh_due(
                limit=limit,
                client_event_prefix=client_event_prefix,
                targets=targets,
            )
        )
