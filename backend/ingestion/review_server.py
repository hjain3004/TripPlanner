from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError

from ingestion.activation import ActivationPlanner
from ingestion.applier import ApplyRefused, ControlledApplier
from ingestion.apply_store import ApplyLedgerError, ApplyStore
from ingestion.artifacts import ContentAddressedStore
from ingestion.config_loaders import (
    ConfigIssue,
    ConfigValidationError,
    host_of,
    is_aggregator_host,
    load_discovery_candidate,
    load_discovery_sources,
    load_source_policies,
    load_watchlist,
)
from ingestion.contracts import (
    FetchAttempt,
    FetchResult,
    PageKind,
    SourcePolicyRecord,
    WatchTarget,
)
from ingestion.diff import diff_text
from ingestion.extraction import FinancialExtractor
from ingestion.policy import CuratorPromotion, promote_candidate_to_watch_target
from ingestion.preflight import SourcePreflight
from ingestion.review import ReviewService
from ingestion.review_app import ReviewAppConfig, SessionRegistry, create_review_app
from ingestion.review_rows import SeedRowSource
from ingestion.review_types import CuratorFieldEdit, DecisionRequest, ReviewRefusedError
from ingestion.seed_writer import SeedWriteError, SeedWriter
from ingestion.snapshots import SnapshotService
from ingestion.staging import StageLimits, StageOutcome, load_curator_extraction, stage_capture
from ingestion.storage import ConflictingWriteError, FinancialIngestionStore, IngestionStoreError

_T = TypeVar("_T")


class LocalOnlyError(RuntimeError):
    pass


def resolve_bind_host(host: str) -> str:
    if host == "localhost":
        return "127.0.0.1"
    if host in {"127.0.0.1", "::1"}:
        return host
    raise LocalOnlyError("FI3 review server must bind to loopback")


def assert_local_profile(env: Mapping[str, str]) -> None:
    if env.get("TRIPWISE_ENV") == "production":
        raise LocalOnlyError("FI3 review server is disabled in production")


def resolve_data_dir(arg: str | None, *, env: Mapping[str, str], repo_root: Path) -> Path:
    # Decide on the raw text: `Path("")` is `.`, which would silently mean "the current directory".
    raw = arg or (
        str(Path(env["TRIPWISE_DATA_DIR"]) / "ingestion") if env.get("TRIPWISE_DATA_DIR") else ""
    )
    if not raw:
        raise LocalOnlyError("FI3 requires --data-dir or TRIPWISE_DATA_DIR")
    resolved = Path(raw).expanduser().resolve()
    root = repo_root.resolve()
    if resolved == root or root in resolved.parents:
        raise LocalOnlyError("FI3 data directory must be outside the repository")
    return resolved


def build_runtime(
    data_dir: Path, seeds_dir: Path, *, now: Callable[[], datetime]
) -> tuple[FinancialIngestionStore, ReviewService, ActivationPlanner]:

    store = FinancialIngestionStore(
        data_dir / "ingestion.sqlite", now=now, id_factory=lambda: uuid.uuid4().hex
    )
    artifacts = ContentAddressedStore(data_dir / "artifacts")
    service = ReviewService(
        store=store, artifacts=artifacts, rows=SeedRowSource(seeds_dir), now=now
    )
    return (
        store,
        service,
        ActivationPlanner(
            store=store, artifacts=artifacts, rows=SeedRowSource(seeds_dir), service=service
        ),
    )


def add_curator(
    data_dir: Path, curator_id: str, display_name: str, *, now: Callable[[], datetime]
) -> int:
    """Register a named curator. Re-running for the same curator and name succeeds."""
    from ingestion.contracts import CuratorRecord

    store = FinancialIngestionStore(
        data_dir / "ingestion.sqlite", now=now, id_factory=lambda: uuid.uuid4().hex
    )

    def settled(existing: CuratorRecord) -> int:
        if existing.display_name == display_name:
            print(f"curator {curator_id!r} already registered as {display_name!r}", file=sys.stderr)
            return 0
        print(
            f"curator {curator_id!r} is already registered as {existing.display_name!r}, "
            f"not {display_name!r}; nothing was changed",
            file=sys.stderr,
        )
        return 2

    existing = store.get_curator(curator_id)
    if existing is not None:
        return settled(existing)
    try:
        store.put_curator(
            CuratorRecord(curator_id=curator_id, display_name=display_name, created_at=now())
        )
    except ConflictingWriteError:
        # Another process registered the same curator between our lookup and our write.
        existing = store.get_curator(curator_id)
        if existing is None:
            raise
        return settled(existing)
    return 0


def create_scripted_demo_proposal(
    *, store: FinancialIngestionStore, service: ReviewService, seeds_dir: Path, now: datetime
) -> str:
    """Create one explicitly synthetic manual-upload proposal through FI2."""
    from agents.llm import ScriptedLLMClient
    from ingestion.review_rows import SeedRowSource
    from ingestion.validation import canonical_row_hash

    artifacts = service.artifacts
    rows = SeedRowSource(seeds_dir)
    current = rows.current_row("cards", "hdfc-infinia")
    store.put_source_policy(
        SourcePolicyRecord(
            policy_id="fi3-demo-policy",
            name="FI3 synthetic demo source",
            owner="TripWise test fixture",
            domain="example.invalid",
            source_url="https://example.invalid/fi3-demo",
            terms_url="https://example.invalid/terms",
            terms_read_on=now.date(),
            automated_access_permitted=False,
            manual_only=True,
            allowed_page_classes=("card_page",),
            reviewed_on=now.date(),
            reviewed_by="alice",
        )
    )
    target = WatchTarget(
        target_id="fi3-demo-hdfc",
        canonical_url="https://example.invalid/fi3-demo",
        source_policy_id="fi3-demo-policy",
        target_fact_ids=("hdfc-infinia",),
        page_kind="manual_capture",
        check_frequency_days=365,
        preferred_backend="manual",
        manual_only=True,
    )
    store.put_watch_target(target)
    text = "Annual fee is INR 12,500."
    raw = artifacts.put(text.encode(), media_type="text/html")
    normalized = artifacts.put(text.encode(), media_type="text/plain")
    result = FetchResult(
        request_id="fi3-demo-fetch",
        final_url=target.canonical_url,
        content_type="text/html",
        raw_artifact=raw,
        normalized_artifact=normalized,
        normalized_text=text,
        engine="fi3-manual-upload",
        engine_version="fixture-1",
    )
    attempt = FetchAttempt(
        attempt_id="fi3-demo-attempt",
        request_id=result.request_id,
        backend="manual",
        backend_version="fixture-1",
        started_at=now,
        ended_at=now,
        final_url=target.canonical_url,
        response_class="success",
        retry_index=0,
    )
    snapshot = SnapshotService(store=store, artifacts=artifacts, now=lambda: now).capture(
        target_id=target.target_id, result=result, attempt=attempt
    )
    assert snapshot is not None
    proposed = dict(current)
    response = {
        "target_table": "cards",
        "target_id": current["id"],
        "proposed_row": proposed,
        "fields": [
            {
                "field_path": "annual_fee_minor",
                "proposed_raw_value": "INR 12,500",
                "evidence_spans": [
                    {
                        "snapshot_id": snapshot.snapshot_id,
                        "snapshot_hash": snapshot.normalized_sha256,
                        "quote": text,
                        "normalized_start": 0,
                        "normalized_end": len(text),
                        "field_path": "annual_fee_minor",
                        "verification": "exact",
                    }
                ],
            }
        ],
        "change_summary": "Synthetic manual-upload FI3 demonstration.",
        "extractor_confidence": 0.0,
    }
    outcome = FinancialExtractor(
        client=ScriptedLLMClient({"financial_extractor": [response]}),
        store=store,
        artifacts=artifacts,
        now=lambda: now,
        extractor_version="fi3-scripted-demo",
    ).extract(
        target_table="cards",
        target_id=current["id"],
        current_row=current,
        current_row_hash=canonical_row_hash(current),
        snapshot=snapshot,
        diff=diff_text(None, text),
        client_event_id="fi3-demo-extraction",
        manual_capture=True,
    )
    if outcome.proposal is None:
        raise RuntimeError(outcome.diagnostic or "scripted FI2 demo did not produce a proposal")
    return outcome.proposal.proposal_id


def _describe_invalid(error: ValueError) -> str:
    if isinstance(error, ValidationError):
        return "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors()
        )
    return str(error)


def _config_refusal(error: ConfigValidationError, *, file_label: str | None = None) -> int:
    """Print every problem in a refused file as typed JSON; exit code 2."""
    issues = [
        {"file": file_label or str(error.path), **issue.model_dump()} for issue in error.issues
    ]
    print(json.dumps({"status": "refused", "kind": "config", "issues": issues}, indent=2))
    print(f"refused: {error}", file=sys.stderr)
    return 2


def _select(items: Sequence[_T], wanted: str | None, key: str, path: str) -> _T:
    """Pick the one entry a command needs from a file that may list several."""
    names = [str(getattr(item, key)) for item in items]
    if wanted is None:
        if len(items) == 1:
            return items[0]
        raise ConfigValidationError(
            Path(path),
            [
                ConfigIssue(
                    code="config_ambiguous_selection",
                    location="file",
                    message=(
                        f"the file has {len(items)} entries; choose one with "
                        f"--{key.replace('_', '-')} ({', '.join(names)})"
                    ),
                )
            ],
        )
    for item, name in zip(items, names, strict=True):
        if name == wanted:
            return item
    raise ConfigValidationError(
        Path(path),
        [
            ConfigIssue(
                code="config_selection_not_found",
                location="file",
                message=f"no entry with {key} {wanted!r} (found: {', '.join(names)})",
            )
        ],
    )


def _name_key(name: str) -> str:
    """A comparison key for issuer/product names: case, spacing and a trailing "card" ignored."""
    folded = " ".join(unicodedata.normalize("NFKC", name).casefold().split())
    return folded.removesuffix(" card").strip()


_ROW_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


def _lead_refusal(code: str, message: str) -> int:
    print(json.dumps({"status": "refused", "kind": "lead", "code": code, "message": message}))
    print(f"refused: {code}: {message}", file=sys.stderr)
    return 2


def run_add_lead(
    args: argparse.Namespace,
    *,
    store: FinancialIngestionStore,
    seeds_dir: Path,
    now: Callable[[], datetime],
) -> int:
    """File a discovery lead (a card exists, here is the issuer page): never a fact."""
    sources = load_discovery_sources(Path(args.discovery_sources), today=now().date())
    domains = tuple(source.domain for source in sources)
    lead = load_discovery_candidate(Path(args.lead), sources=sources, aggregator_domains=domains)
    stored = store.get_discovery_candidate(lead.id)
    if stored is not None and stored != lead:
        return _lead_refusal(
            "lead_conflict",
            f"a different lead is already filed as {lead.id!r}; stored leads are immutable",
        )
    wanted = (_name_key(lead.issuer_guess), _name_key(lead.product_guess), lead.corridor)
    for other in store.list_discovery_candidates():
        if (
            other.id != lead.id
            and (_name_key(other.issuer_guess), _name_key(other.product_guess), other.corridor)
            == wanted
        ):
            return _lead_refusal(
                "lead_duplicate",
                f"lead {other.id!r} already covers this issuer, product and corridor",
            )
    from ingestion.review_rows import SeedRowSource

    for card in SeedRowSource(seeds_dir).table_rows("cards"):
        if (_name_key(str(card["issuer"])), _name_key(str(card["name"]))) == wanted[:2]:
            return _lead_refusal(
                "lead_duplicate", f"the knowledge base already has the card {card['id']!r}"
            )
    store.put_discovery_candidate(lead)
    print(
        json.dumps(
            {
                "status": "filed",
                "lead_id": lead.id,
                "state": "already_stored" if stored is not None else "stored",
                "facts_carried": 0,
            },
            sort_keys=True,
        )
    )
    return 0


def run_promote_lead(
    args: argparse.Namespace,
    *,
    store: FinancialIngestionStore,
    seeds_dir: Path,
    now: Callable[[], datetime],
) -> int:
    """A curator turns a filed lead into a manual-capture target on the ISSUER's page."""
    from ingestion.review_rows import SUPPORTED_TABLES, SeedRowSource

    if args.table not in SUPPORTED_TABLES:
        return _lead_refusal(
            "unsupported_target_table",
            f"{args.table!r} is not a seed table ({', '.join(sorted(SUPPORTED_TABLES))})",
        )
    if not _ROW_ID.match(args.row_id):
        return _lead_refusal(
            "invalid_row_id", "a row id is lowercase letters, digits and hyphens, 2-64 characters"
        )
    out_path = Path(args.out)
    if not out_path.parent.is_dir():
        return _lead_refusal(
            "output_directory_missing", f"the directory for {out_path} does not exist"
        )
    lead = store.get_discovery_candidate(args.lead_id)
    if lead is None:
        return _lead_refusal("lead_not_found", f"no lead {args.lead_id!r}; file it with add-lead")
    if store.get_curator(args.curator_id) is None:
        return _lead_refusal("unknown_curator", f"curator {args.curator_id!r} is not registered")
    if lead.issuer_url_to_verify is None:
        return _lead_refusal("lead_without_issuer_url", "the lead names no issuer page to read")
    sources = (
        load_discovery_sources(Path(args.discovery_sources), today=now().date())
        if args.discovery_sources
        else ()
    )
    policies = load_source_policies(
        Path(args.source_policy), aggregator_domains=tuple(s.domain for s in sources)
    )
    policy = _select(policies, args.policy_id, "policy_id", args.source_policy)
    if is_aggregator_host(
        host_of(lead.issuer_url_to_verify), extra_domains=tuple(s.domain for s in sources)
    ):
        return _lead_refusal(
            "aggregator_domain", "the issuer page is an aggregator's, not the issuer's"
        )
    try:
        SourcePreflight().check_redirect(
            lead.issuer_url_to_verify, lead.issuer_url_to_verify, policy
        )
    except (ValueError, UnicodeError) as error:
        return _lead_refusal(
            "lead_outside_policy", f"the issuer page is outside the policy: {error}"
        )
    if any(row.get("id") == args.row_id for row in SeedRowSource(seeds_dir).table_rows(args.table)):
        return _lead_refusal(
            "insert_id_exists", f"a {args.table} row {args.row_id!r} already exists; use an update"
        )
    promoted = promote_candidate_to_watch_target(
        lead,
        CuratorPromotion(
            curator_id=args.curator_id, decided_at=now(), source_policy_id=policy.policy_id
        ),
    )
    # Phase 2 captures are manual: the document class is chosen at stage time, and review keys
    # the manual-capture marking on this page kind. The row the curator intends to add is named.
    target = promoted.model_copy(
        update={
            "page_kind": PageKind.MANUAL_CAPTURE,
            "target_fact_ids": (f"candidate:{lead.id}", f"{args.table}:{args.row_id}"),
        }
    )
    stored = store.get_watch_target(target.target_id)
    if stored is not None:
        if stored.model_copy(update={"promoted_at": None}) != target.model_copy(
            update={"promoted_at": None}
        ):
            return _lead_refusal(
                "target_conflict", f"a different target is already stored as {target.target_id!r}"
            )
        target = stored
    try:
        store.put_source_policy(policy)
        store.put_watch_target(target)
    except ConflictingWriteError as error:
        return _lead_refusal("policy_conflict", str(error))
    entry = {
        "target_id": target.target_id,
        "url": target.canonical_url,
        "kind": target.page_kind.value,
        "target": list(target.target_fact_ids),
        "source_policy_id": target.source_policy_id,
        "check_frequency_days": target.check_frequency_days,
        "backend": target.preferred_backend,
        "manual_only": target.manual_only,
        "promoted_from_candidate_id": target.promoted_from_candidate_id,
        "promoted_by": target.promoted_by,
        "promoted_at": target.promoted_at.isoformat() if target.promoted_at else None,
    }
    import yaml

    text = yaml.safe_dump([entry], sort_keys=False)
    out = Path(args.out)
    if out.exists() and out.read_text(encoding="utf-8") != text:
        return _lead_refusal(
            "output_exists", f"{out} exists with different content; not overwritten"
        )
    staged_out = out.with_name(f".{out.name}.tmp")
    staged_out.write_text(text, encoding="utf-8")
    staged_out.replace(out)  # whole file or nothing, never a half-written watch-target file
    print(
        json.dumps(
            {
                "status": "promoted",
                "lead_id": lead.id,
                "target_id": target.target_id,
                "issuer_url": target.canonical_url,
                "target_fact_ids": list(target.target_fact_ids),
                "watch_target_file": str(out),
                "aggregator_url_carried": is_aggregator_host(host_of(target.canonical_url)),
            },
            sort_keys=True,
        )
    )
    return 0


def check_config(args: argparse.Namespace, *, today: datetime) -> int:
    """Validate configuration files without touching a data directory or the network."""
    summary: dict[str, object] = {"status": "ok", "network_calls": 0}
    sources = (
        load_discovery_sources(Path(args.discovery_sources), today=today.date())
        if (args.discovery_sources)
        else ()
    )
    aggregator_domains = tuple(source.domain for source in sources)
    if args.discovery_sources:
        summary["discovery_sources"] = [
            {
                "name": source.name,
                "domain": source.domain,
                "access": "manual_only" if source.manual_only else "automated",
            }
            for source in sources
        ]
    policies = (
        load_source_policies(Path(args.source_policies), aggregator_domains=aggregator_domains)
        if args.source_policies
        else ()
    )
    if args.source_policies:
        summary["source_policies"] = [
            {
                "policy_id": policy.policy_id,
                "domain": policy.domain,
                "allowed_page_classes": list(policy.allowed_page_classes),
            }
            for policy in policies
        ]
    if args.watchlist:
        targets = load_watchlist(
            Path(args.watchlist),
            policies={policy.policy_id: policy for policy in policies},
            aggregator_domains=aggregator_domains,
        )
        summary["watchlist"] = [
            {
                "target_id": target.target_id,
                "page_kind": target.page_kind.value,
                "url": target.canonical_url,
                "policy_id": target.source_policy_id,
            }
            for target in targets
        ]
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def run_stage_capture(
    args: argparse.Namespace,
    *,
    store: FinancialIngestionStore,
    artifacts: ContentAddressedStore,
    seeds_dir: Path,
    now: Callable[[], datetime],
) -> int:
    sources = (
        load_discovery_sources(Path(args.discovery_sources), today=now().date())
        if (args.discovery_sources)
        else ()
    )
    aggregator_domains = tuple(source.domain for source in sources)
    policies = load_source_policies(Path(args.source_policy), aggregator_domains=aggregator_domains)
    policy = _select(policies, args.policy_id, "policy_id", args.source_policy)
    targets = load_watchlist(
        Path(args.watch_target),
        policies={policy.policy_id: policy},
        aggregator_domains=aggregator_domains,
    )
    target = _select(targets, args.target_id, "target_id", args.watch_target)
    extraction = load_curator_extraction(Path(args.extraction))
    outcome: StageOutcome = stage_capture(
        store=store,
        artifacts=artifacts,
        seeds_dir=seeds_dir,
        capture_path=Path(args.capture),
        policy=policy,
        target=target,
        extraction=extraction,
        document_class=PageKind(args.document_class),
        now=now,
        limits=StageLimits(
            max_bytes=args.max_bytes, max_pages=args.max_pages, timeout_seconds=args.timeout_seconds
        ),
        aggregator_domains=aggregator_domains,
    )
    print(outcome.model_dump_json(indent=2))
    if outcome.status != "staged":
        first = outcome.refusals[0]
        extra = f" (+{len(outcome.refusals) - 1} more)" if len(outcome.refusals) > 1 else ""
        print(f"refused: {first.code.value}: {first.message}{extra}", file=sys.stderr)
        return 2
    return 0


def build_applier(
    data_dir: Path, store: FinancialIngestionStore, *, now: Callable[[], datetime]
) -> ControlledApplier:
    """The controlled applier, with its ledger and journals beside the ingestion data."""
    return ControlledApplier(
        store=store,
        service_factory=lambda seeds: build_runtime(data_dir, seeds, now=now)[1],
        planner_factory=lambda seeds: build_runtime(data_dir, seeds, now=now)[2],
        ledger=ApplyStore(data_dir / "apply.sqlite", now=now),
        writer=SeedWriter(state_dir=data_dir / "apply_state", now=now),
        now=now,
    )


def run_apply_command(args: argparse.Namespace, applier: ControlledApplier) -> int:
    """confirm-origin, apply, rollback, recover and coverage: each an explicit operator action."""
    try:
        if args.command == "confirm-origin":
            confirmation, created = applier.confirm_origin(
                proposal_id=args.proposal_id,
                document_class=args.document_class,
                curator_id=args.curator_id,
                statement=args.statement,
                seeds_dir=Path(args.seeds_dir),
            )
            print(
                json.dumps({"created": created, **confirmation.model_dump(mode="json")}, indent=2)
            )
        elif args.command == "apply":
            record = applier.apply(
                bundle_sha256=args.bundle_sha256,
                seeds_dir=Path(args.seeds_dir),
                curator_id=args.curator_id,
                reason=args.reason,
                client_event_id=args.client_event_id,
            )
            print(record.model_dump_json(indent=2))
        elif args.command == "rollback":
            record = applier.rollback(
                apply_id=args.apply_id, curator_id=args.curator_id, reason=args.reason
            )
            print(record.model_dump_json(indent=2))
        elif args.command == "recover":
            outcomes = applier.recover(Path(args.seeds_dir))
            print(json.dumps([{"apply_id": a, "outcome": o} for a, o in outcomes], indent=2))
        else:
            print(json.dumps(applier.coverage(Path(args.seeds_dir)), indent=2))
    except ApplyRefused as refusal:
        print(f"refused: {refusal.code}: {refusal}", file=sys.stderr)
        return 2
    except (SeedWriteError, ApplyLedgerError) as failure:
        print(f"refused: {failure.code}: {failure}", file=sys.stderr)
        return 2
    return 0


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    # `env or {}` would make the real process environment unreachable from the CLI.
    environment = os.environ if env is None else env
    parser = argparse.ArgumentParser(prog="python -m ingestion.review_server")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add-curator")
    add.add_argument("--data-dir", default=None)
    add.add_argument("--curator-id", required=True)
    add.add_argument("--display-name", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--data-dir", default=None)
    serve.add_argument("--seeds-dir", default=None)
    serve.add_argument("--curator-id", required=True)
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--host", default="127.0.0.1")
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--data-dir", default=None)
    inspect.add_argument("--seeds-dir", default=None)
    inspect.add_argument("--proposal-id", required=True)
    reopen = sub.add_parser("reopen")
    reopen.add_argument("--data-dir", default=None)
    reopen.add_argument("--seeds-dir", default=None)
    reopen.add_argument("--proposal-id", required=True)
    decide = sub.add_parser("decision")
    decide.add_argument("--data-dir", default=None)
    decide.add_argument("--seeds-dir", default=None)
    decide.add_argument("--proposal-id", required=True)
    decide.add_argument("--curator-id", required=True)
    decide.add_argument(
        "--action", choices=("approve", "edit", "reject", "reverify"), required=True
    )
    decide.add_argument("--reason", required=True)
    decide.add_argument("--expected-version", type=int, required=True)
    decide.add_argument("--client-event-id", required=True)
    decide.add_argument("--curator-confidence", type=float, default=None)
    decide.add_argument("--edits-json", default="[]")
    bundle = sub.add_parser("bundle")
    bundle.add_argument("--data-dir", default=None)
    bundle.add_argument("--seeds-dir", default=None)
    bundle.add_argument("--curator-id", required=True)
    bundle.add_argument("--client-event-id", required=True)
    bundle.add_argument("--proposal-id", action="append", default=None)
    dry = sub.add_parser("dry-run")
    dry.add_argument("--data-dir", default=None)
    dry.add_argument("--seeds-dir", default=None)
    dry.add_argument("--bundle-sha256", required=True)
    stage = sub.add_parser("stage-capture")
    stage.add_argument("--data-dir", default=None)
    stage.add_argument("--seeds-dir", default=None)
    stage.add_argument("--capture", required=True)
    stage.add_argument("--source-policy", required=True)
    stage.add_argument("--policy-id", default=None)
    stage.add_argument("--watch-target", required=True)
    stage.add_argument("--target-id", default=None)
    stage.add_argument("--extraction", required=True)
    stage.add_argument(
        "--document-class", required=True, choices=("card_page", "offer_page", "tnc_pdf")
    )
    stage.add_argument("--discovery-sources", default=None)
    stage.add_argument("--max-bytes", type=int, default=StageLimits.max_bytes)
    stage.add_argument("--max-pages", type=int, default=StageLimits.max_pages)
    stage.add_argument("--timeout-seconds", type=int, default=StageLimits.timeout_seconds)
    lead = sub.add_parser("add-lead")
    lead.add_argument("--data-dir", default=None)
    lead.add_argument("--seeds-dir", default=None)
    lead.add_argument("--lead", required=True)
    lead.add_argument("--discovery-sources", required=True)
    promote = sub.add_parser("promote-lead")
    promote.add_argument("--data-dir", default=None)
    promote.add_argument("--seeds-dir", default=None)
    promote.add_argument("--lead-id", required=True)
    promote.add_argument("--curator-id", required=True)
    promote.add_argument("--source-policy", required=True)
    promote.add_argument("--policy-id", default=None)
    promote.add_argument("--discovery-sources", default=None)
    promote.add_argument("--table", default="cards")
    promote.add_argument("--row-id", required=True)
    promote.add_argument("--out", required=True)
    check = sub.add_parser("check-config")
    check.add_argument("--source-policies", default=None)
    check.add_argument("--discovery-sources", default=None)
    check.add_argument("--watchlist", default=None)
    confirm = sub.add_parser("confirm-origin")
    confirm.add_argument("--data-dir", default=None)
    confirm.add_argument("--seeds-dir", required=True)
    confirm.add_argument("--proposal-id", required=True)
    confirm.add_argument(
        "--document-class", required=True, choices=("card_page", "offer_page", "tnc_pdf")
    )
    confirm.add_argument("--curator-id", required=True)
    confirm.add_argument("--statement", required=True)
    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("--data-dir", default=None)
    apply_cmd.add_argument("--seeds-dir", required=True)
    apply_cmd.add_argument("--bundle-sha256", required=True)
    apply_cmd.add_argument("--curator-id", required=True)
    apply_cmd.add_argument("--reason", required=True)
    apply_cmd.add_argument("--client-event-id", required=True)
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--data-dir", default=None)
    rollback.add_argument("--seeds-dir", required=True)
    rollback.add_argument("--apply-id", required=True)
    rollback.add_argument("--curator-id", required=True)
    rollback.add_argument("--reason", required=True)
    recover = sub.add_parser("recover")
    recover.add_argument("--data-dir", default=None)
    recover.add_argument("--seeds-dir", required=True)
    coverage = sub.add_parser("coverage")
    coverage.add_argument("--data-dir", default=None)
    coverage.add_argument("--seeds-dir", required=True)
    demo = sub.add_parser("demo")
    demo.add_argument("--data-dir", default=None)
    demo.add_argument("--seeds-dir", default=None)
    args = parser.parse_args(argv)
    assert_local_profile(environment)

    def now() -> datetime:
        return datetime.now(UTC)

    if args.command == "check-config":
        try:
            return check_config(args, today=now())
        except ConfigValidationError as error:
            return _config_refusal(error)
    repo_root = Path(__file__).resolve().parents[2]
    data_dir = resolve_data_dir(args.data_dir, env=environment, repo_root=repo_root)

    if args.command == "add-curator":
        return add_curator(data_dir, args.curator_id, args.display_name, now=now)
    from core.db import SEEDS_DIR

    store, service, planner = build_runtime(
        data_dir, Path(args.seeds_dir) if args.seeds_dir else SEEDS_DIR, now=now
    )
    if args.command in {"confirm-origin", "apply", "rollback", "recover", "coverage"}:
        return run_apply_command(args, build_applier(data_dir, store, now=now))
    if args.command in {"add-lead", "promote-lead"}:
        runner = run_add_lead if args.command == "add-lead" else run_promote_lead
        try:
            return runner(
                args,
                store=store,
                seeds_dir=Path(args.seeds_dir) if args.seeds_dir else SEEDS_DIR,
                now=now,
            )
        except ConfigValidationError as error:
            return _config_refusal(error)
    if args.command == "stage-capture":
        try:
            return run_stage_capture(
                args,
                store=store,
                artifacts=service.artifacts,
                seeds_dir=Path(args.seeds_dir) if args.seeds_dir else SEEDS_DIR,
                now=now,
            )
        except ConfigValidationError as error:
            return _config_refusal(error)
    if args.command in {"inspect", "reopen"}:
        context = service.context(args.proposal_id)
        payload = {
            "proposal": context.proposal.model_dump(mode="json"),
            "current_row": context.current_row,
            "current_row_sha256": context.current_row_sha256,
            "field_diffs": [diff.model_dump(mode="json") for diff in context.field_diffs],
            "evidence": [item.model_dump(mode="json") for item in context.evidence],
            "findings": [finding.model_dump(mode="json") for finding in context.computed_findings],
            "decisions": [decision.model_dump(mode="json") for decision in context.decisions],
            "audit_events": context.audit_events,
        }
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0
    if args.command == "decision":
        try:
            edits = tuple(
                CuratorFieldEdit.model_validate(item) for item in json.loads(args.edits_json)
            )
            request = DecisionRequest(
                proposal_id=args.proposal_id,
                action=args.action,
                reason=args.reason,
                expected_version=args.expected_version,
                client_event_id=args.client_event_id,
                curator_confidence=args.curator_confidence,
                edits=edits,
            )
        except (ValidationError, ValueError) as invalid:
            # Only the arguments the operator typed are reported this way; a validation error
            # raised anywhere else is a bug and keeps its traceback.
            print(f"refused: invalid input: {_describe_invalid(invalid)}", file=sys.stderr)
            return 2
        print(service.decide(request, curator_id=args.curator_id).model_dump_json(indent=2))
        return 0
    if args.command == "bundle":
        record, created = planner.build(
            proposal_ids=tuple(args.proposal_id) if args.proposal_id else None,
            curator_id=args.curator_id,
            client_event_id=args.client_event_id,
        )
        print(
            json.dumps(
                {
                    "record": record.model_dump(mode="json"),
                    "bundle": created.model_dump(mode="json"),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "dry-run":
        print(planner.dry_run(args.bundle_sha256).model_dump_json(indent=2))
        return 0
    if args.command == "demo":
        proposal_id = create_scripted_demo_proposal(
            store=store,
            service=service,
            seeds_dir=Path(args.seeds_dir) if args.seeds_dir else SEEDS_DIR,
            now=now(),
        )
        print(
            json.dumps(
                {"proposal_id": proposal_id, "synthetic": True, "manual_upload": True},
                sort_keys=True,
            )
        )
        return 0
    host = resolve_bind_host(args.host)
    if store.get_curator(args.curator_id) is None:
        print("unknown curator", file=sys.stderr)
        return 2
    sessions = SessionRegistry(now=now)
    token = sessions.issue_login_token(args.curator_id)
    print(f"FI3 review login token: {token}", file=sys.stderr)
    import uvicorn

    app = create_review_app(
        service=service, planner=planner, sessions=sessions, config=ReviewAppConfig(port=args.port)
    )
    uvicorn.Server(
        uvicorn.Config(
            app,
            host=host,
            port=args.port,
            access_log=False,
            server_header=False,
            proxy_headers=False,
            log_level="warning",
        )
    ).run()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LocalOnlyError as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        raise SystemExit(2) from None
    except (IngestionStoreError, ReviewRefusedError) as refusal:
        print(f"refused: {type(refusal).__name__}: {refusal}", file=sys.stderr)
        raise SystemExit(2) from None
