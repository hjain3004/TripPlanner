"""Controlled apply, rollback and recovery of an approved activation bundle onto seed files.

Nothing here runs by itself: every entry point is an explicit, curator-attributed call, there is
no scheduler or background path, and the destination is always an explicit seed directory that
must lie outside the repository (the demonstration copies the seeds to a scratch directory).

``apply`` is a sequence of refusals before a single byte is written:

1. the seed directory is not inside a protected root and has no unfinished earlier operation;
2. the bundle exists, hashes to its name, is schema v2, and the FI3 dry-run against *this* seed
   directory is consistent (so nothing is stale, conflicting or tampered with);
3. every entry is re-derived from the stored proposal and decision (never trusted from the
   bundle): the latest decision is the attested approval named by the entry, the row it attests
   is the row the bundle carries, no blocking finding exists, and the evidence still verifies;
4. D1 and D2 decide each row's provenance (``verification.py``); an unmet condition never blocks
   the apply, it leaves the row ``needs_verification=true`` and says why;
5. the resulting seed files load into a ``KnowledgeBase`` in memory.

Only then are the ledger record and the journaled multi-file write made. The write is recoverable
but not one transaction (see ``seed_writer.py``); ``recover`` reconciles the journal with the
ledger so an interrupted operation is never half-recorded.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ValidationError

from core.db import KnowledgeBase
from core.models import Card, Offer, PointValuation, RewardRule
from ingestion.activation import (
    BUNDLE_SCHEMA,
    ActivationBundle,
    ActivationBundleRecord,
    ActivationEntry,
    ActivationPlanner,
)
from ingestion.apply_store import ApplicationRecord, ApplyLedgerError, ApplyStore
from ingestion.artifacts import ArtifactIntegrityError
from ingestion.contracts import PageKind
from ingestion.review import ReviewService
from ingestion.review_rows import SUPPORTED_TABLES, SeedRowSource, flatten_row
from ingestion.review_types import CuratorFieldEdit, ReviewRefusedError
from ingestion.seed_writer import Checkpoint, SeedWriteError, SeedWriter
from ingestion.storage import FinancialIngestionStore
from ingestion.validation import canonical_row_hash
from ingestion.verification import (
    LedgerEvidence,
    OriginConfirmation,
    RowVerification,
    canonical_value,
    confirmation_problems,
    evaluate_row,
    new_confirmation,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
D2Status = Literal["not_needed", "confirmed", "unconfirmed"]


class ApplyRefused(RuntimeError):
    """A typed refusal. Nothing was written when this is raised."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RowOutcome(BaseModel):
    table: str
    row_id: str
    operation: Literal["update", "insert"]
    d1: RowVerification
    d2: D2Status
    needs_verification: bool
    provenance_source_type: str
    final_row_sha256: str
    reason: str


class _Prepared(BaseModel):
    entry_key: tuple[str, str]
    outcome: RowOutcome
    row: dict[str, Any]
    evidence: list[LedgerEvidence]


def _quote_for(ctx: Any, decision: Any, path: str) -> tuple[str, str]:
    """(snapshot_id, quote) that evidences ``path`` under this decision."""
    for edit in (
        CuratorFieldEdit.model_validate(v) for v in (decision.edits or {}).get("fields", [])
    ):
        if edit.field_path == path and edit.action == "set" and edit.quote and edit.snapshot_id:
            return edit.snapshot_id, edit.quote
    for field in ctx.proposal.field_proposals:
        if field.field_path == path:
            span = field.evidence_spans[0]
            return span.snapshot_id, span.quote
    raise ApplyRefused("evidence_missing", f"no quoted evidence found for {path}")


def _render_yaml(original: bytes, rows: list[dict[str, Any]]) -> bytes:
    """Deterministic YAML for a seed table. Only a leading comment block survives (see report)."""
    header: list[str] = []
    for line in original.decode("utf-8").splitlines():
        if line.startswith("#"):
            header.append(line)
        else:
            break
    body = yaml.safe_dump(rows, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return ("\n".join(header) + ("\n" if header else "") + body).encode("utf-8")


class ControlledApplier:
    def __init__(
        self,
        *,
        store: FinancialIngestionStore,
        service_factory: Callable[[Path], ReviewService],
        planner_factory: Callable[[Path], ActivationPlanner],
        ledger: ApplyStore,
        writer: SeedWriter,
        now: Callable[[], datetime],
        protected_roots: Sequence[Path] = (_REPO_ROOT,),
    ) -> None:
        self.store = store
        self.service_factory = service_factory
        self.planner_factory = planner_factory
        self.ledger = ledger
        self.writer = writer
        self.now = now
        self.protected_roots = tuple(p.resolve() for p in protected_roots)

    # ------------------------------------------------------------------ guards

    def _check_destination(self, seeds_dir: Path) -> Path:
        resolved = seeds_dir.resolve()
        for root in self.protected_roots:
            if resolved == root or root in resolved.parents:
                raise ApplyRefused(
                    "protected_seeds",
                    f"{resolved} is inside the repository ({root}); controlled apply only writes "
                    "to an explicit seed directory outside it (a scratch copy)",
                )
        for parent in (resolved, *resolved.parents):
            if (parent / ".git").exists():
                raise ApplyRefused(
                    "inside_git_checkout",
                    f"{resolved} is inside a git checkout ({parent}); controlled apply only "
                    "writes to a scratch directory that is not under version control",
                )
        for name, _ in SUPPORTED_TABLES.values():
            seed_file = resolved / name
            if not seed_file.is_file():
                raise ApplyRefused("not_a_seed_dir", f"{resolved} has no {name}")
            if seed_file.is_symlink():
                raise ApplyRefused(
                    "seed_file_is_symlink",
                    f"{seed_file} is a symbolic link; replacing it would change the file "
                    "system object, not just its bytes",
                )
        return resolved

    def _curator(self, curator_id: str) -> None:
        if self.store.get_curator(curator_id) is None:
            raise ApplyRefused("unknown_curator", f"{curator_id!r} is not a registered curator")

    # ------------------------------------------------------------------ D2

    def confirm_origin(
        self,
        *,
        proposal_id: str,
        document_class: Literal["card_page", "offer_page", "tnc_pdf"],
        curator_id: str,
        statement: str,
        seeds_dir: Path,
    ) -> tuple[OriginConfirmation, bool]:
        """Record, durably, that a named curator confirmed a manual capture is the issuer's own.

        The confirmation is bound to the capture's snapshot and hashes. It is never inferred from
        a URL: a URL on the issuer domain is a necessary condition checked here, not a
        sufficient one.
        """
        self._curator(curator_id)
        try:
            ctx = self.service_factory(seeds_dir).context(proposal_id)
        except KeyError as error:
            raise ApplyRefused("unknown_proposal", f"no proposal {proposal_id!r}") from error
        if ctx.lineage is None or len(ctx.lineage.snapshots) != 1:
            raise ApplyRefused("no_lineage", "the proposal has no single capture to confirm")
        snapshot = ctx.lineage.snapshots[0]
        candidate = new_confirmation(
            snapshot=snapshot,
            target=ctx.lineage.watch_target,
            policy=ctx.lineage.source_policy,
            document_class=document_class,
            curator_id=curator_id,
            statement=statement,
            now=self.now(),
        )
        problems = confirmation_problems(
            candidate,
            snapshot=snapshot,
            target=ctx.lineage.watch_target,
            policy=ctx.lineage.source_policy,
        )
        if problems:
            raise ApplyRefused("origin_not_confirmable", "; ".join(problems))
        try:
            return self.ledger.put_confirmation(candidate)
        except ApplyLedgerError as error:
            raise ApplyRefused(error.code, str(error)) from error

    # ------------------------------------------------------------------ apply

    def _load_bundle(self, bundle_sha256: str) -> ActivationBundle:
        record_json = self.store.get_activation_bundle(bundle_sha256)
        if record_json is None:
            raise ApplyRefused("unknown_bundle", f"no stored bundle {bundle_sha256}")
        planner = self.planner_factory(Path("."))  # artifact access only; no seeds are read here
        record = ActivationBundleRecord.model_validate_json(record_json)
        try:
            body = planner.artifacts.read(record.artifact)
        except Exception as error:
            raise ApplyRefused("bundle_unreadable", f"bundle artifact: {error}") from error
        if hashlib.sha256(body).hexdigest() != bundle_sha256:
            raise ApplyRefused("bundle_tampered", "the bundle bytes do not hash to its name")
        schema = json.loads(body).get("schema_version")
        if schema != BUNDLE_SCHEMA:
            raise ApplyRefused(
                "bundle_schema", f"only {BUNDLE_SCHEMA} bundles can be applied, not {schema!r}"
            )
        try:
            bundle = ActivationBundle.model_validate_json(body)
        except ValidationError as error:
            raise ApplyRefused("bundle_invalid", f"the bundle does not parse: {error}") from error
        missing = [n for n, _ in SUPPORTED_TABLES.values() if n not in bundle.seed_files]
        if missing:
            raise ApplyRefused("bundle_invalid", f"the bundle has no hash for {missing}")
        seen: set[tuple[str, str]] = set()
        for item in bundle.entries:
            key = (item.target_table, item.target_id)
            if key in seen:
                raise ApplyRefused("duplicate_entry", f"the bundle lists {key[0]}/{key[1]} twice")
            seen.add(key)
        return bundle

    def _revalidate(
        self, entry: ActivationEntry, service: ReviewService, planner: ActivationPlanner
    ) -> tuple[Any, Any]:
        """Re-derive the entry from the stored proposal and approval; refuse any difference."""
        key = f"{entry.target_table}/{entry.target_id}"
        try:
            ctx = service.context(entry.proposal_id)
        except KeyError as error:
            raise ApplyRefused("unknown_proposal", f"{key}: proposal is gone") from error
        if not ctx.decisions:
            raise ApplyRefused("under_approved", f"{key}: the proposal has no decision")
        decision = ctx.decisions[-1]
        if (
            decision.decision_id != entry.decision_id
            or decision.status.value not in {"approved", "edited"}
            or decision.attestation is None
        ):
            raise ApplyRefused(
                "decision_changed",
                f"{key}: the approval the bundle rests on is no longer the latest decision",
            )
        if self.store.get_curator(decision.reviewer_id) is None:
            raise ApplyRefused("under_approved", f"{key}: approver is not a registered curator")
        blocking = [f for f in ctx.computed_findings if f.severity == "blocking"]
        if blocking:
            raise ApplyRefused("blocking_finding", f"{key}: {blocking[0].message}")
        try:
            rebuilt = planner.entry_for(entry.proposal_id)
        except (ValueError, KeyError, ReviewRefusedError, ArtifactIntegrityError) as error:
            raise ApplyRefused("entry_invalid", f"{key}: {error}") from error
        have, want = entry.model_dump(mode="json"), rebuilt.model_dump(mode="json")
        if have != want:
            differing = sorted(k for k in have.keys() | want.keys() if have.get(k) != want.get(k))
            raise ApplyRefused(
                "entry_tampered",
                f"{key}: the bundle entry differs from what the stored approval supports "
                f"({', '.join(differing)})",
            )
        return ctx, decision

    def _origin_ok(self, snapshot_id: str, cache: dict[str, bool]) -> bool:
        """May evidence quoted from this capture count? Manual captures need a valid D2."""
        if snapshot_id in cache:
            return cache[snapshot_id]
        verdict = False
        snapshot = self.store.get_snapshot(snapshot_id)
        target = self.store.get_watch_target(snapshot.target_id) if snapshot else None
        policy = self.store.get_source_policy(target.source_policy_id) if target else None
        if snapshot is not None and target is not None and policy is not None:
            if target.page_kind is not PageKind.MANUAL_CAPTURE:
                verdict = True
            else:
                verdict = any(
                    not confirmation_problems(c, snapshot=snapshot, target=target, policy=policy)
                    for c in self.ledger.confirmations_for(snapshot_id)
                )
        cache[snapshot_id] = verdict
        return verdict

    def _usable_evidence(self, table: str, row_id: str, seeds: Path) -> list[LedgerEvidence]:
        """Committed evidence on this seed directory whose capture's origin is established."""
        cache: dict[str, bool] = {}
        return [
            item
            for item in self.ledger.active_evidence(table, row_id, str(seeds))
            if self._origin_ok(item.snapshot_id, cache)
        ]

    def _prepare(
        self,
        entry: ActivationEntry,
        ctx: Any,
        decision: Any,
        *,
        apply_id: str,
        seeds: Path,
    ) -> _Prepared:
        table, row_id = entry.target_table, entry.target_id
        row = copy.deepcopy(entry.new_row)
        flat = flatten_row(row)
        now_evidence: dict[str, str] = {}
        ledger_items: list[LedgerEvidence] = []
        for path in entry.evidenced_fields:
            if path not in flat:
                continue
            snapshot_id, quote = _quote_for(ctx, decision, path)
            now_evidence[path] = canonical_value(flat[path])
            ledger_items.append(
                LedgerEvidence(
                    apply_id=apply_id,
                    table_name=table,
                    row_id=row_id,
                    field_path=path,
                    value_json=now_evidence[path],
                    proposal_id=entry.proposal_id,
                    decision_id=entry.decision_id,
                    reviewer_id=entry.reviewer_id,
                    snapshot_id=snapshot_id,
                    quote=quote,
                )
            )
        d1 = evaluate_row(
            row,
            now_evidence=now_evidence,
            earlier=self._usable_evidence(table, row_id, seeds),
        )
        manual = ctx.lineage.watch_target.page_kind is PageKind.MANUAL_CAPTURE
        d2: D2Status = "not_needed"
        document_class: str | None = None
        if manual:
            d2 = "unconfirmed"
            snapshot = ctx.lineage.snapshots[0]
            for confirmation in self.ledger.confirmations_for(snapshot.snapshot_id):
                if not confirmation_problems(
                    confirmation,
                    snapshot=snapshot,
                    target=ctx.lineage.watch_target,
                    policy=ctx.lineage.source_policy,
                ):
                    d2 = "confirmed"
                    document_class = confirmation.document_class
                    break
        base = copy.deepcopy(row["provenance"])
        candidate = entry.provenance_candidate
        verified = d1.satisfied and d2 in {"not_needed", "confirmed"}
        reason: str
        if verified:
            source_type = (
                "tnc_pdf"
                if document_class == "tnc_pdf" or (not manual and entry.source_type == "tnc_pdf")
                else "official_page"
            )
            base.update(
                {
                    "source_type": source_type,
                    "source_url": candidate.source_url,
                    "last_verified": candidate.last_verified,
                    "verified_by": candidate.verified_by,
                    "needs_verification": False,
                    "notes": f"verified by controlled apply {apply_id}: every fact field has "
                    "quoted evidence (D1)"
                    + ("; origin confirmed by a curator (D2)" if manual else ""),
                }
            )
            if candidate.confidence is not None:
                base["confidence"] = candidate.confidence
            reason = "D1 satisfied" + (" and D2 confirmed" if manual else "")
        else:
            base["needs_verification"] = True
            parts: list[str] = []
            if not d1.satisfied:
                parts.append(
                    f"D1 open: {len(d1.missing)} field(s) without evidence, "
                    f"{len(d1.stale)} with stale evidence"
                )
            if d2 == "unconfirmed":
                parts.append("D2 open: manual capture without a curator origin confirmation")
            reason = "; ".join(parts)
        row["provenance"] = base
        typed = SUPPORTED_TABLES[table][1].model_validate(row)
        row = typed.model_dump(mode="json")
        return _Prepared(
            entry_key=(table, row_id),
            outcome=RowOutcome(
                table=table,
                row_id=row_id,
                operation=entry.operation,
                d1=d1,
                d2=d2,
                needs_verification=bool(base["needs_verification"]),
                provenance_source_type=str(base["source_type"]),
                final_row_sha256=canonical_row_hash(row),
                reason=reason,
            ),
            row=row,
            evidence=ledger_items,
        )

    def apply(
        self,
        *,
        bundle_sha256: str,
        seeds_dir: Path,
        curator_id: str,
        reason: str,
        client_event_id: str,
        checkpoint: Checkpoint | None = None,
    ) -> ApplicationRecord:
        seeds = self._check_destination(seeds_dir)
        self._curator(curator_id)
        if len(reason.strip()) < 10:
            raise ApplyRefused(
                "reason_required", "an apply needs a reason of at least 10 characters"
            )
        try:
            with self.writer.locked(seeds):
                return self._apply_locked(
                    bundle_sha256, seeds, curator_id, reason, client_event_id, checkpoint
                )
        except SeedWriteError as error:
            raise ApplyRefused(error.code, str(error)) from error

    def _apply_locked(
        self,
        bundle_sha256: str,
        seeds: Path,
        curator_id: str,
        reason: str,
        client_event_id: str,
        checkpoint: Checkpoint | None,
    ) -> ApplicationRecord:
        fingerprint = hashlib.sha256(
            json.dumps(
                [bundle_sha256, str(seeds), curator_id, reason], separators=(",", ":")
            ).encode()
        ).hexdigest()
        self._reconcile_ledger(seeds)  # a rolled-back apply must not keep counting as evidence
        replay = self.ledger.application_for_event(client_event_id)
        if replay is not None:
            if self._fingerprint_of(replay) != fingerprint:
                raise ApplyRefused(
                    "idempotency_conflict",
                    "this client event id was already used for a different apply request",
                )
            return replay
        if self.writer.open_journals(seeds):
            raise ApplyRefused(
                "incomplete_apply",
                "an earlier apply or rollback on this seed directory did not finish: run recover",
            )
        bundle = self._load_bundle(bundle_sha256)
        planner = self.planner_factory(seeds)
        try:
            report = planner.dry_run(bundle_sha256)
        except (KeyError, ValueError, ArtifactIntegrityError) as error:
            raise ApplyRefused(
                "bundle_invalid", f"the bundle cannot be dry-run: {error}"
            ) from error
        if not report.seed_files_unchanged:
            raise ApplyRefused(
                "stale_bundle",
                "the seed files changed since this bundle was built; rebuild it from the "
                "current seeds and re-review",
            )
        bad = [
            e
            for e in report.entries
            if e.status not in {"would_update", "would_insert", "confirmed_unchanged"}
        ]
        if bad or not report.dry_run_consistent:
            raise ApplyRefused(
                "dry_run_inconsistent",
                "the dry-run is not consistent: "
                + ", ".join(f"{e.target_table}/{e.target_id}={e.status}" for e in bad)
                + ("; " + "; ".join(report.reference_errors) if report.reference_errors else ""),
            )
        if bundle.refused:
            raise ApplyRefused(
                "bundle_has_refusals", "the bundle lists refused entries; rebuild it without them"
            )
        service = self.service_factory(seeds)
        apply_id = "apply-" + hashlib.sha256(client_event_id.encode()).hexdigest()[:16]
        prepared: list[_Prepared] = []
        evidence_only: list[_Prepared] = []
        for entry in bundle.entries:
            ctx, decision = self._revalidate(entry, service, planner)
            item = self._prepare(entry, ctx, decision, apply_id=apply_id, seeds=seeds)
            # An update whose evidence only confirms what is stored writes the row when that
            # evidence changes its provenance (D1 newly met). When the row would be identical
            # there is nothing to write, but the evidence is still recorded so that it can be
            # combined with later captures.
            if (
                entry.operation == "update"
                and item.outcome.final_row_sha256 == entry.base_row_sha256
            ):
                evidence_only.append(item)
            else:
                prepared.append(item)
        evidence_items = [e for p in (*prepared, *evidence_only) for e in p.evidence]
        if not prepared and not evidence_items:
            raise ApplyRefused("nothing_to_apply", "the bundle changes no seed row")
        contents: dict[str, bytes] = {}
        files: dict[str, dict[str, str]] = {}
        if prepared:
            contents, files = self._build_files(seeds, bundle, prepared)
        plan = {
            "files": files,
            "ledger_only": not prepared,
            "rows": [p.outcome.model_dump(mode="json") for p in (*prepared, *evidence_only)],
            "evidence": [e.model_dump(mode="json") for e in evidence_items],
            "repository_seeds_touched": False,
        }
        record = ApplicationRecord(
            apply_id=apply_id,
            bundle_sha256=bundle_sha256,
            seeds_dir=str(seeds),
            curator_id=curator_id,
            reason=reason,
            client_event_id=client_event_id,
            status="planned",
            plan=plan,
        )
        try:
            record, created = self.ledger.begin_application(record, fingerprint=fingerprint)
        except ApplyLedgerError as error:
            raise ApplyRefused(error.code, str(error)) from error
        if not created:
            return record
        if prepared:
            try:
                self.writer.apply(
                    seeds_dir=seeds,
                    apply_id=apply_id,
                    bundle_sha256=bundle_sha256,
                    contents=contents,
                    expected_priors={n: f["prior_sha256"] for n, f in files.items()},
                    checkpoint=checkpoint,
                )
            except SeedWriteError as error:
                if error.code in {"seeds_changed", "incomplete_apply", "apply_exists"}:
                    # nothing was written: close the record instead of leaving it open
                    self.ledger.set_status(apply_id, "aborted", detail=f"{error.code}: {error}")
                    raise ApplyRefused(error.code, str(error)) from error
                self.ledger.set_status(apply_id, "failed", detail=f"{error.code}: {error}")
                raise ApplyRefused(
                    error.code, f"{error}; run recover before any further operation"
                ) from error
        return self.ledger.set_status(
            apply_id,
            "committed",
            evidence=evidence_items,
            detail="seed files committed"
            if prepared
            else "evidence recorded; no seed file changed",
        )

    @staticmethod
    def _fingerprint_of(record: ApplicationRecord) -> str:
        return hashlib.sha256(
            json.dumps(
                [record.bundle_sha256, record.seeds_dir, record.curator_id, record.reason],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    def _build_files(
        self, seeds: Path, bundle: ActivationBundle, prepared: list[_Prepared]
    ) -> tuple[dict[str, bytes], dict[str, dict[str, str]]]:
        rows_source = SeedRowSource(seeds)
        by_table: dict[str, list[_Prepared]] = {}
        for item in prepared:
            by_table.setdefault(item.entry_key[0], []).append(item)
        contents: dict[str, bytes] = {}
        files: dict[str, dict[str, str]] = {}
        models: dict[str, list[dict[str, Any]]] = {
            table: rows_source.table_rows(table) for table in SUPPORTED_TABLES
        }
        for table, items in by_table.items():
            filename = SUPPORTED_TABLES[table][0]
            path = seeds / filename
            original = path.read_bytes()
            if hashlib.sha256(original).hexdigest() != bundle.seed_files[filename]:
                raise ApplyRefused("stale_bundle", f"{filename} changed since the bundle was built")
            raw = yaml.safe_load(original)
            replacements = {i.entry_key[1]: i.row for i in items if i.outcome.operation == "update"}
            out: list[dict[str, Any]] = []
            for raw_row in raw:
                rid = raw_row.get("id") if isinstance(raw_row, dict) else None
                out.append(replacements.pop(rid) if rid in replacements else raw_row)
            if replacements:
                raise ApplyRefused("row_missing", f"{table}: {sorted(replacements)} not found")
            out.extend(i.row for i in items if i.outcome.operation == "insert")
            contents[filename] = _render_yaml(original, out)
            model = SUPPORTED_TABLES[table][1]
            reloaded = [
                model.model_validate(r).model_dump(mode="json")
                for r in yaml.safe_load(contents[filename])
            ]
            planned = [model.model_validate(r).model_dump(mode="json") for r in out]
            if reloaded != planned:
                raise ApplyRefused(
                    "render_mismatch",
                    f"{filename} as it would be written does not load back to the approved "
                    "rows (a value does not survive YAML round-tripping); nothing was written",
                )
            files[filename] = {
                "prior_sha256": hashlib.sha256(original).hexdigest(),
                "new_sha256": hashlib.sha256(contents[filename]).hexdigest(),
            }
            ids = {i.entry_key[1]: i.row for i in items}
            models[table] = [ids.get(r["id"], r) for r in models[table]] + [
                i.row for i in items if i.outcome.operation == "insert"
            ]
        try:
            KnowledgeBase.from_models(
                cards=[Card.model_validate(r) for r in models["cards"]],
                reward_rules=[RewardRule.model_validate(r) for r in models["reward_rules"]],
                offers=[Offer.model_validate(r) for r in models["offers"]],
                point_valuations=[
                    PointValuation.model_validate(r) for r in models["point_valuations"]
                ],
            )
            card_ids = {r["id"] for r in models["cards"]}
            dangling = [
                f"{t}/{r['id']}"
                for t in ("reward_rules", "point_valuations")
                for r in models[t]
                if r["card_id"] not in card_ids
            ]
            if dangling:
                raise ValueError(f"unknown card reference: {', '.join(dangling)}")
        except Exception as error:
            raise ApplyRefused("kb_invalid", f"the resulting seeds do not load: {error}") from error
        return contents, files

    # ------------------------------------------------------------------ rollback / recover

    def rollback(
        self,
        *,
        apply_id: str,
        curator_id: str,
        reason: str,
        seeds_dir: Path | None = None,
        checkpoint: Checkpoint | None = None,
    ) -> ApplicationRecord:
        self._curator(curator_id)
        if len(reason.strip()) < 10:
            raise ApplyRefused(
                "reason_required", "a rollback needs a reason of at least 10 characters"
            )
        record = self.ledger.get_application(apply_id)
        if record is None:
            raise ApplyRefused("unknown_apply", f"no apply {apply_id!r}")
        seeds = self._check_destination(Path(record.seeds_dir))
        if seeds_dir is not None and seeds_dir.resolve() != seeds:
            raise ApplyRefused(
                "wrong_seeds_dir", f"apply {apply_id} was made on {seeds}, not {seeds_dir}"
            )
        try:
            with self.writer.locked(seeds):
                self._reconcile_ledger(seeds)
                record = self.ledger.get_application(apply_id) or record
                if record.status == "rolled_back":
                    return record
                if record.status != "committed":
                    raise ApplyRefused(
                        "not_committed",
                        f"apply {apply_id} is {record.status}; only committed applies roll back",
                    )
                if not record.plan.get("ledger_only"):
                    self.writer.rollback(apply_id=apply_id, checkpoint=checkpoint)
                return self.ledger.set_status(
                    apply_id, "rolled_back", detail=f"rolled back by {curator_id}: {reason}"
                )
        except SeedWriteError as error:
            raise ApplyRefused(error.code, str(error)) from error

    def recover(self, seeds_dir: Path) -> list[tuple[str, str]]:
        """Resolve interrupted operations, then bring the ledger in line with the journals."""
        seeds = self._check_destination(seeds_dir)
        try:
            with self.writer.locked(seeds):
                outcomes = self.writer.recover(seeds)
                done = {apply_id for apply_id, _ in outcomes}
                outcomes += [
                    (apply_id, outcome)
                    for apply_id, outcome in self._reconcile_ledger(seeds)
                    if apply_id not in done
                ]
                return outcomes
        except SeedWriteError as error:
            raise ApplyRefused(error.code, str(error)) from error

    def _reconcile_ledger(self, seeds: Path) -> list[tuple[str, str]]:
        """Make the ledger say what the journals (the record of the files) say. Lock held."""
        changed: list[tuple[str, str]] = []
        for record in self.ledger.applications_for(str(seeds)):
            try:
                state: str | None = self.writer.summary(record.apply_id).state
            except SeedWriteError:
                state = None
            outcome = self._reconcile(record, state)
            if outcome is not None:
                changed.append((record.apply_id, outcome))
        return changed

    def _reconcile(self, record: ApplicationRecord, journal_state: str | None) -> str | None:
        apply_id = record.apply_id
        evidence = [LedgerEvidence.model_validate(e) for e in record.plan["evidence"]]
        open_status = record.status in {"planned", "failed"}
        if record.plan.get("ledger_only"):
            if open_status:
                self.ledger.set_status(apply_id, "aborted", detail="recovery: never committed")
                return "aborted"
            return None
        if journal_state is None:
            if open_status:  # died before the journal existed: nothing was written
                self.ledger.set_status(apply_id, "aborted", detail="recovery: no journal")
                return "aborted"
            return None
        if journal_state == "committed" and open_status:
            self.ledger.set_status(
                apply_id,
                "committed",
                evidence=evidence,
                detail="reconciled after recovery: the seed files had been committed",
            )
            return "committed"
        if journal_state in {"aborted", "rolled_back_by_recovery"} and open_status:
            self.ledger.set_status(apply_id, "aborted", detail=f"recovery: {journal_state}")
            return "aborted"
        if journal_state == "rolled_back" and record.status == "committed":
            self.ledger.set_status(apply_id, "rolled_back", detail="reconciled after recovery")
            return "rolled_back"
        return None

    # ------------------------------------------------------------------ coverage

    def coverage(self, seeds_dir: Path) -> list[dict[str, Any]]:
        """Per-row D1 coverage from the ledger alone (no decision is being applied)."""
        seeds = self._check_destination(seeds_dir)
        try:
            with self.writer.locked(seeds):
                self._reconcile_ledger(seeds)
        except SeedWriteError as error:
            raise ApplyRefused(error.code, str(error)) from error
        rows = SeedRowSource(seeds)
        report: list[dict[str, Any]] = []
        for table in SUPPORTED_TABLES:
            for row in rows.table_rows(table):
                row_id = str(row["id"])
                usable = self._usable_evidence(table, row_id, seeds)
                verification = evaluate_row(row, now_evidence={}, earlier=usable)
                # Evidence a committed apply recorded but that does not count yet because the
                # capture's origin (D2) is unconfirmed: without this a ledger-only apply would
                # read as "nothing happened".
                counted = {item.field_path for item in usable}
                awaiting = sorted(
                    {
                        item.field_path
                        for item in self.ledger.active_evidence(table, row_id, str(seeds))
                        if item.field_path not in counted
                    }
                )
                report.append(
                    {
                        "table": table,
                        "row_id": row["id"],
                        "needs_verification": row["provenance"]["needs_verification"],
                        "d1_satisfied": verification.satisfied,
                        "evidenced": len(verification.evidenced_earlier),
                        "awaiting_origin_confirmation": awaiting,
                        "missing": len(verification.missing),
                        "stale": list(verification.stale),
                    }
                )
        return report


__all__ = ["ApplyRefused", "ControlledApplier", "RowOutcome"]
