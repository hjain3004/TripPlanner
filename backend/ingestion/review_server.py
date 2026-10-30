from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from ingestion.activation import ActivationPlanner
from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import (
    FetchAttempt,
    FetchResult,
    SourcePolicyRecord,
    WatchTarget,
)
from ingestion.diff import diff_text
from ingestion.extraction import FinancialExtractor
from ingestion.review import ReviewService
from ingestion.review_app import ReviewAppConfig, SessionRegistry, create_review_app
from ingestion.review_rows import SeedRowSource
from ingestion.review_types import CuratorFieldEdit, DecisionRequest
from ingestion.snapshots import SnapshotService
from ingestion.storage import FinancialIngestionStore


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
    candidate = Path(
        arg
        or (Path(env["TRIPWISE_DATA_DIR"]) / "ingestion" if env.get("TRIPWISE_DATA_DIR") else "")
    )
    if not str(candidate):
        raise LocalOnlyError("FI3 requires --data-dir or TRIPWISE_DATA_DIR")
    resolved = candidate.expanduser().resolve()
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


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    environment = env or {}
    parser = argparse.ArgumentParser(prog="python -m ingestion.review_server")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add-curator")
    add.add_argument("--data-dir", required=True)
    add.add_argument("--curator-id", required=True)
    add.add_argument("--display-name", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--data-dir", required=True)
    serve.add_argument("--seeds-dir", default=None)
    serve.add_argument("--curator-id", required=True)
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--host", default="127.0.0.1")
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--data-dir", required=True)
    inspect.add_argument("--seeds-dir", default=None)
    inspect.add_argument("--proposal-id", required=True)
    reopen = sub.add_parser("reopen")
    reopen.add_argument("--data-dir", required=True)
    reopen.add_argument("--seeds-dir", default=None)
    reopen.add_argument("--proposal-id", required=True)
    decide = sub.add_parser("decision")
    decide.add_argument("--data-dir", required=True)
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
    bundle.add_argument("--data-dir", required=True)
    bundle.add_argument("--seeds-dir", default=None)
    bundle.add_argument("--curator-id", required=True)
    bundle.add_argument("--client-event-id", required=True)
    bundle.add_argument("--proposal-id", action="append", default=None)
    dry = sub.add_parser("dry-run")
    dry.add_argument("--data-dir", required=True)
    dry.add_argument("--seeds-dir", default=None)
    dry.add_argument("--bundle-sha256", required=True)
    demo = sub.add_parser("demo")
    demo.add_argument("--data-dir", required=True)
    demo.add_argument("--seeds-dir", default=None)
    args = parser.parse_args(argv)
    assert_local_profile(environment)
    repo_root = Path(__file__).resolve().parents[2]
    data_dir = resolve_data_dir(args.data_dir, env=environment, repo_root=repo_root)

    def now() -> datetime:
        return datetime.now(UTC)

    if args.command == "add-curator":
        from ingestion.contracts import CuratorRecord

        store = FinancialIngestionStore(
            data_dir / "ingestion.sqlite", now=now, id_factory=lambda: uuid.uuid4().hex
        )
        store.put_curator(
            CuratorRecord(
                curator_id=args.curator_id, display_name=args.display_name, created_at=now()
            )
        )
        return 0
    from core.db import SEEDS_DIR

    store, service, planner = build_runtime(
        data_dir, Path(args.seeds_dir) if args.seeds_dir else SEEDS_DIR, now=now
    )
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
        edits = tuple(CuratorFieldEdit.model_validate(item) for item in json.loads(args.edits_json))
        request = DecisionRequest(
            proposal_id=args.proposal_id,
            action=args.action,
            reason=args.reason,
            expected_version=args.expected_version,
            client_event_id=args.client_event_id,
            curator_confidence=args.curator_confidence,
            edits=edits,
        )
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
    raise SystemExit(main())
