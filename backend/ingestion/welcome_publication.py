"""Controlled publication of approved welcome offers to the catalog file the API reads.

A proposal reaches the catalog only after a registered curator approved it in the existing review
workflow. This module never approves anything and never writes inside the repository: it writes
the operator's runtime catalog file (``TRIPWISE_WELCOME_OFFERS_PATH``), through the same journaled,
crash-recoverable ``SeedWriter`` the core seed apply uses, and records every publication in the
ingestion store's insert-only history so it can be listed and rolled back.

The request-time service only *reads* that file (``welcome.catalog``); it imports nothing from
here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import ProposalStatus, ReviewDecisionStatus
from ingestion.evidence import EvidenceVerificationError, verify_evidence_span
from ingestion.seed_writer import SeedWriteError, SeedWriter, sha256_file
from ingestion.storage import FinancialIngestionStore
from ingestion.validation import canonical_row_hash
from ingestion.verification import canonical_value, evaluate_row
from welcome.models import CardAcquisitionOffer

CATALOG_FILE = "card_acquisition_offers.yaml"
TARGET_TABLE = "card_acquisition_offers"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_HEADER = (
    "# Published welcome-offer catalog. Written only by the controlled publisher after a\n"
    "# registered curator approved each row; every row carries its own provenance.\n"
)


class PublicationRefused(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PublicationRecord:
    publication_id: str
    proposal_id: str
    offer_id: str
    intent: str
    curator_id: str
    needs_verification: bool
    catalog_sha256_before: str
    catalog_sha256_after: str
    already_published: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def init_catalog(catalog_dir: Path) -> Path:
    """Create an empty published catalog; refuses to touch an existing one."""
    path = catalog_dir / CATALOG_FILE
    if path.exists():
        raise PublicationRefused("catalog_exists", f"{path} already exists")
    catalog_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(_HEADER + "[]\n", encoding="utf-8")
    return path


def _render(rows: list[dict[str, Any]]) -> bytes:
    body = yaml.safe_dump(rows, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return (_HEADER + body).encode("utf-8")


def read_catalog_rows(catalog_dir: Path) -> dict[str, dict[str, Any]]:
    """The published rows by id, as validated JSON-mode dicts (empty when there is no file)."""
    path = catalog_dir / CATALOG_FILE
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_bytes()) or []
    rows: dict[str, dict[str, Any]] = {}
    for item in raw:
        typed = CardAcquisitionOffer.model_validate(item)
        rows[typed.id] = typed.model_dump(mode="json")
    return rows


class WelcomePublisher:
    def __init__(
        self,
        *,
        store: FinancialIngestionStore,
        artifacts: ContentAddressedStore,
        catalog_dir: Path,
        state_dir: Path,
        now: Callable[[], datetime],
        protected_roots: tuple[Path, ...] = (_REPO_ROOT,),
    ) -> None:
        self.store = store
        self.artifacts = artifacts
        self.catalog_dir = catalog_dir
        self.writer = SeedWriter(state_dir=state_dir, now=now)
        self.now = now
        self.protected_roots = tuple(root.resolve() for root in protected_roots)

    # ------------------------------------------------------------------ guards

    def _check_destination(self) -> Path:
        resolved = self.catalog_dir.resolve()
        for root in self.protected_roots:
            if resolved == root or root in resolved.parents:
                raise PublicationRefused(
                    "protected_catalog",
                    f"{resolved} is inside the repository; the publisher writes only an "
                    "operator catalog outside it (repository files change through git review)",
                )
        for parent in (resolved, *resolved.parents):
            if (parent / ".git").exists():
                raise PublicationRefused(
                    "inside_git_checkout", f"{resolved} is inside a git checkout ({parent})"
                )
        target = resolved / CATALOG_FILE
        if not target.is_file():
            raise PublicationRefused("no_catalog", f"{target} does not exist; run init first")
        if target.is_symlink():
            raise PublicationRefused("catalog_is_symlink", f"{target} is a symbolic link")
        return resolved

    # ------------------------------------------------------------------ publish

    def publish(self, proposal_id: str) -> PublicationRecord:
        existing = self._published(proposal_id)
        if existing is not None:
            return PublicationRecord(**{**existing, "already_published": True})
        proposal = self.store.get_proposal(proposal_id)
        if proposal is None:
            raise PublicationRefused("unknown_proposal", f"no proposal {proposal_id!r}")
        if proposal.target_table != TARGET_TABLE:
            raise PublicationRefused("wrong_table", "only welcome-offer proposals publish here")
        if proposal.status is not ProposalStatus.APPROVED:
            raise PublicationRefused(
                "not_approved", f"proposal is {proposal.status.value}; a curator must approve it"
            )
        decisions = self.store.list_decisions(proposal_id)
        decision = decisions[-1] if decisions else None
        if decision is None or decision.status is not ReviewDecisionStatus.APPROVED:
            raise PublicationRefused("no_approval", "the latest decision is not an approval")
        # A decision bumps the proposal version once. Any other version means the proposal moved
        # on after this approval (a later decision or edit), so the approval no longer binds it.
        if proposal.version != decision.proposal_version + 1:
            raise PublicationRefused(
                "stale_decision", "the proposal changed after the approval; it needs a new decision"
            )
        if self.store.get_curator(decision.reviewer_id) is None:
            raise PublicationRefused(
                "unknown_curator", f"{decision.reviewer_id!r} is not a registered curator"
            )
        if decision.curator_confidence is None:
            raise PublicationRefused(
                "no_confidence", "an approval must state the curator's confidence to be published"
            )
        catalog_dir = self._check_destination()
        rows = read_catalog_rows(catalog_dir)
        before_sha = sha256_file(catalog_dir / CATALOG_FILE)

        # Re-verify the evidence now, from the retained snapshot, rather than trusting the draft.
        evidenced: dict[str, str] = {}
        for field in proposal.field_proposals:
            for span in field.evidence_spans:
                snapshot = self.store.get_snapshot(span.snapshot_id)
                if snapshot is None:
                    raise PublicationRefused("evidence_missing", f"snapshot {span.snapshot_id}")
                try:
                    verify_evidence_span(span, snapshot=snapshot, artifacts=self.artifacts)
                except EvidenceVerificationError as error:
                    raise PublicationRefused("evidence_invalid", str(error)) from error
            evidenced[field.field_path] = canonical_value(field.parsed_value)

        offer_id = proposal.target_id
        prior_row = rows.get(offer_id)
        if proposal.intent == "insert":
            if prior_row is not None:
                raise PublicationRefused(
                    "id_exists", f"{offer_id} is already published; this insert is stale"
                )
        elif prior_row is None or canonical_row_hash(prior_row) != proposal.current_row_hash:
            raise PublicationRefused(
                "stale_row", "the published row changed since this proposal was made"
            )

        row = json.loads(json.dumps(proposal.proposed_row))
        verification = evaluate_row(row, now_evidence=evidenced, earlier=())
        needs_verification = not verification.satisfied
        row["provenance"] = {
            **row["provenance"],
            "source_type": "official_page",
            "last_verified": decision.decided_at.date().isoformat(),
            "verified_by": decision.reviewer_id,
            "needs_verification": needs_verification,
            "confidence": decision.curator_confidence,
            "notes": (
                f"published from {proposal_id} after approval {decision.decision_id}; evidence is "
                "a quote from Firecrawl-rendered issuer HTML (not original issuer bytes)"
                + (
                    f"; fields without quoted evidence: {', '.join(verification.missing)}"
                    if verification.missing
                    else ""
                )
            ),
        }
        try:
            typed = CardAcquisitionOffer.model_validate(row)
        except ValidationError as error:
            raise PublicationRefused("invalid_row", f"invalid published row: {error}") from error
        rows[offer_id] = typed.model_dump(mode="json")
        content = _render([rows[key] for key in sorted(rows)])
        publication_id = (
            "pub-"
            + hashlib.sha256(f"{proposal_id}:{decision.decision_id}".encode()).hexdigest()[:20]
        )
        try:
            self.writer.apply(
                seeds_dir=catalog_dir,
                apply_id=publication_id,
                bundle_sha256=hashlib.sha256(content).hexdigest(),
                contents={CATALOG_FILE: content},
                expected_priors={CATALOG_FILE: before_sha},
            )
        except SeedWriteError as error:
            raise PublicationRefused(error.code, str(error)) from error
        record = PublicationRecord(
            publication_id=publication_id,
            proposal_id=proposal_id,
            offer_id=offer_id,
            intent=proposal.intent,
            curator_id=decision.reviewer_id,
            needs_verification=needs_verification,
            catalog_sha256_before=before_sha,
            catalog_sha256_after=sha256_file(catalog_dir / CATALOG_FILE),
        )
        self.store.record_publication_event(
            publication_id=publication_id,
            event_type="published",
            payload={
                **record.to_dict(),
                "decision_id": decision.decision_id,
                "published_at": self.now().isoformat(),
                "row": rows[offer_id],
                "prior_row": prior_row,
            },
        )
        return record

    def _published(self, proposal_id: str) -> dict[str, Any] | None:
        events = self.store.list_publication_events()
        rolled_back = {e["publication_id"] for e in events if e["event_type"] == "rolled_back"}
        names = [
            name for name in PublicationRecord.__dataclass_fields__ if name != "already_published"
        ]
        for event in events:
            if (
                event["event_type"] == "published"
                and event["proposal_id"] == proposal_id
                and event["publication_id"] not in rolled_back
            ):
                return {name: event[name] for name in names}
        return None

    # ------------------------------------------------------------------ history and rollback

    def history(self) -> list[dict[str, Any]]:
        return self.store.list_publication_events()

    def rollback(self, publication_id: str) -> PublicationRecord:
        events = self.store.list_publication_events()
        published = next(
            (
                e
                for e in events
                if e["publication_id"] == publication_id and e["event_type"] == "published"
            ),
            None,
        )
        if published is None:
            raise PublicationRefused("unknown_publication", f"no publication {publication_id!r}")
        if any(
            e["publication_id"] == publication_id and e["event_type"] == "rolled_back"
            for e in events
        ):
            raise PublicationRefused("already_rolled_back", "this publication was rolled back")
        catalog_dir = self._check_destination()
        if sha256_file(catalog_dir / CATALOG_FILE) != published["catalog_sha256_after"]:
            raise PublicationRefused(
                "catalog_changed",
                "the catalog changed after this publication; roll back later ones first",
            )
        try:
            self.writer.rollback(apply_id=publication_id)
        except SeedWriteError as error:
            raise PublicationRefused(error.code, str(error)) from error
        restored = sha256_file(catalog_dir / CATALOG_FILE)
        self.store.record_publication_event(
            publication_id=publication_id,
            event_type="rolled_back",
            payload={"restored_sha256": restored, "rolled_back_at": self.now().isoformat()},
        )
        return PublicationRecord(
            publication_id=publication_id,
            proposal_id=str(published["proposal_id"]),
            offer_id=str(published["offer_id"]),
            intent=str(published["intent"]),
            curator_id=str(published["curator_id"]),
            needs_verification=bool(published["needs_verification"]),
            catalog_sha256_before=str(published["catalog_sha256_after"]),
            catalog_sha256_after=restored,
        )
