"""Which financial facts does a concrete trip depend on, and what is the state of each?

The question an operator has before touching a capture is not "what is in the ingestion
database" but "for *this* trip and *this* wallet, which facts move the numbers, which of those
are still unverified placeholders, which have a draft waiting for a human, and what evidence is
missing altogether?". This module answers it for the shipped India -> Singapore demonstration
(``core.optimizer.demo_data.demo_trip``) and the demonstration wallet, and it changes nothing.

Two things are *measured*, not asserted:

* **Influence.** Every integer fact of the relevant seed rows is doubled and halved in memory
  (a nudge of one is too small for basis points, micro-major values and floored points) and the
  unchanged deterministic optimizer is run again; if neither change alters the full result the
  fact is reported as having no observed effect on *this* trip (not a proof for other trips).
  Whole rules, valuations and offers are removed the same way. Facts that are not integers
  (lists, enums, dates) are not probed and say so. Nothing is inferred from reading code, and
  nothing is written.
* **State.** Evidence comes from the real ingestion database (proposals, decisions) and the real
  apply ledger, never from the seeds' own claims.

What a capture does *not* say cannot be computed, so the operator records it in a small findings
file (``--findings``): "this document does not state the forex markup" is a human observation
and is reported as one, next to the fact it concerns. The module never writes a financial value,
never makes a decision, and never touches a network.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from core.db import KnowledgeBase
from core.models import Card, FxRate, Offer, PointValuation, RewardRule, UserWallet
from core.optimizer import optimize
from core.optimizer.demo_data import demo_trip
from ingestion.contracts import ChangeProposal, ProposalStatus
from ingestion.migrations import SCHEMA_VERSION
from ingestion.review_rows import SUPPORTED_TABLES, SeedRowSource, flatten_row
from ingestion.verification import LedgerEvidence, canonical_value, required_fact_paths

TRIP_ID = "demo-del-sin"
DEMO_WALLET = UserWallet(
    card_ids=["hdfc-infinia", "axis-atlas"], points_balances={"voyager-prime": 140000}
)

Influence = Literal["moves_trip_result", "no_effect_observed", "not_probed"]
FactState = Literal[
    "seed_claims_verified",
    "unverified_placeholder",
    "absent",
    "awaiting_human_review",
    "approved_not_applied",
    "evidence_recorded_origin_unconfirmed",
    "evidenced",
]
Verdict = Literal[
    "not_stated_in_capture", "needs_human_judgment", "not_representable", "conflicts_with_seed"
]

# Guidance only: which kind of issuer document normally states a family of facts.
_DOCUMENT_FOR = {
    "cards": "issuer fees & charges / most-important-terms-and-conditions document",
    "reward_rules": "issuer rewards terms (category rate, cap, exclusions, portal terms)",
    "point_valuations": "issuer rewards redemption terms",
    "offers": "offer terms page (issuer or merchant)",
}


class Finding(BaseModel):
    """What a human found when reading one capture, recorded next to the fact it concerns."""

    model_config = ConfigDict(extra="forbid")

    table: str
    id: str
    field: str
    verdict: Verdict
    note: str = Field(min_length=1, max_length=400)
    snapshot_id: str | None = None


class FactReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: str
    row_id: str
    field_path: str
    value: Any
    influence: Influence
    # True when the fact moves this trip's result, or could not be measured on a row that is
    # in scope (an unmeasured fact is *not* reported as harmless).
    needed_for_trip: bool = False
    state: FactState
    evidence: list[str] = Field(default_factory=list)
    finding: Verdict | None = None
    finding_note: str | None = None


class RowReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: str
    row_id: str
    issuer: str
    description: str
    row_influences_trip: bool | None  # None: a wallet card (always in scope, not probed by removal)
    provenance: str
    facts: list[FactReadiness]


class EvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issuer: str
    document: str
    situation: Literal["no_draft_or_recorded_finding", "read_but_not_stated_or_unusable"]
    facts: list[str]


class Gap(BaseModel):
    """A fact the current schema or catalogs cannot hold. A data requirement, not a draft."""

    model_config = ConfigDict(extra="forbid")

    id: str
    detail: str
    owner: str


class ReadinessReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trip: str
    wallet: list[str]
    seeds_dir: str
    data_dir: str | None
    as_of: datetime
    rows: list[RowReadiness]
    evidence_requests: list[EvidenceRequest]
    gaps: list[Gap]
    owner_decisions: list[str]
    summary: dict[str, int]
    unmatched_findings: list[Finding] = Field(default_factory=list)


# ---------------------------------------------------------------------------------------- #
# The knowledge base under evaluation and the influence probes
# ---------------------------------------------------------------------------------------- #

_MODELS: dict[str, Any] = {
    "cards": Card,
    "reward_rules": RewardRule,
    "offers": Offer,
    "point_valuations": PointValuation,
}


def _kb(rows: Mapping[str, Sequence[Mapping[str, Any]]], fx: Sequence[FxRate]) -> KnowledgeBase:
    return KnowledgeBase(
        cards=[Card.model_validate(r) for r in rows["cards"]],
        reward_rules=[RewardRule.model_validate(r) for r in rows["reward_rules"]],
        offers=[Offer.model_validate(r) for r in rows["offers"]],
        point_valuations=[PointValuation.model_validate(r) for r in rows["point_valuations"]],
        fx_rates=list(fx),
    )


_PROSE_KEYS = {"explanation", "assumptions", "provenance_flags"}


def _without_prose(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _without_prose(v) for k, v in value.items() if k not in _PROSE_KEYS}
    if isinstance(value, list):
        return [_without_prose(v) for v in value]
    return value


def _result_hash(kb: KnowledgeBase, wallet: UserWallet) -> str:
    """Digest of the numbers and choices; the explanatory prose is not what is being probed."""
    result = optimize(demo_trip(), wallet, kb)
    body = _without_prose(result.model_dump(mode="json"))
    text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _set_path(row: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node = row
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _relevant(
    rows: Mapping[str, list[dict[str, Any]]], wallet: Sequence[str]
) -> list[tuple[str, dict[str, Any]]]:
    held = set(wallet)
    picked: list[tuple[str, dict[str, Any]]] = []
    for row in rows["cards"]:
        if row["id"] in held:
            picked.append(("cards", row))
    for table in ("reward_rules", "point_valuations"):
        picked.extend((table, r) for r in rows[table] if r["card_id"] in held)
    picked.extend(("offers", r) for r in rows["offers"])
    return picked


def probe_influence(
    rows: Mapping[str, list[dict[str, Any]]],
    fx: Sequence[FxRate],
    wallet: UserWallet,
) -> tuple[dict[tuple[str, str], bool | None], dict[tuple[str, str, str], Influence]]:
    """Run the unchanged optimizer on the demo trip with each fact varied or each row removed.

    Integers are doubled and halved. Scalar text facts (a network, an issuer, a card link, a
    merchant, a date) are replaced by each *other* value the seeds hold for the same field.
    Lists and facts with no sibling value cannot be varied and are reported ``not_probed``.
    """
    base_rows = {t: [copy.deepcopy(r) for r in rows[t]] for t in SUPPORTED_TABLES}
    baseline = _result_hash(_kb(base_rows, fx), wallet)
    row_effect: dict[tuple[str, str], bool | None] = {}
    fact_effect: dict[tuple[str, str, str], Influence] = {}
    for table, row in _relevant(base_rows, wallet.card_ids):
        row_id = str(row["id"])
        if table == "cards":
            row_effect[(table, row_id)] = None
        else:
            without = {t: [r for r in base_rows[t] if r is not row] for t in SUPPORTED_TABLES}
            try:
                row_effect[(table, row_id)] = _result_hash(_kb(without, fx), wallet) != baseline
            except Exception:  # the trip cannot be costed without it: it certainly matters
                row_effect[(table, row_id)] = True
        for path, value in sorted(flatten_row(row).items()):
            if path == "id" or path.startswith("provenance."):
                continue
            if _is_int(value):
                candidates: list[Any] = sorted(
                    {c for c in (value * 2 if value else 1, value // 2, value + 1) if c != value}
                )
            elif isinstance(value, str):
                candidates = sorted(
                    {
                        other
                        for other_row in base_rows[table]
                        for other in [flatten_row(other_row).get(path)]
                        if isinstance(other, str) and other != value
                    }
                )
            else:
                candidates = []
            fact_effect[(table, row_id, path)] = _vary(
                base_rows, fx, wallet, baseline, table, row, path, candidates
            )
    return row_effect, fact_effect


def _vary(
    base_rows: dict[str, list[dict[str, Any]]],
    fx: Sequence[FxRate],
    wallet: UserWallet,
    baseline: str,
    table: str,
    row: dict[str, Any],
    path: str,
    candidates: Sequence[Any],
) -> Influence:
    tried = False
    for candidate in candidates:
        if _is_int(candidate) and candidate < 0:
            continue
        changed = copy.deepcopy(row)
        _set_path(changed, path, candidate)
        try:
            _MODELS[table].model_validate(changed)
        except Exception:
            continue
        tried = True
        rows = {t: [changed if r is row else r for r in base_rows[t]] for t in SUPPORTED_TABLES}
        try:
            digest = _result_hash(_kb(rows, fx), wallet)
        except Exception:
            return "moves_trip_result"  # the trip no longer costs: it certainly matters
        if digest != baseline:
            return "moves_trip_result"
    return "no_effect_observed" if tried else "not_probed"


# ---------------------------------------------------------------------------------------- #
# Evidence state from the real ingestion database and apply ledger (strictly read-only)
# ---------------------------------------------------------------------------------------- #


class ReadinessRefused(RuntimeError):
    """The data directory cannot be read without changing it; nothing was touched."""


def _label(proposal_id: str) -> str:
    """Short, unambiguous name: the row and the watch target the proposal was staged under."""
    row_part, _, rest = proposal_id.partition(":snapshot:")
    target = rest.split(":", 1)[0]
    return f"{row_part.removeprefix('proposal:')}@{target}"


class ReadOnlyView:
    """Proposals, ledger evidence and origin confirmations, read with SQLite ``mode=ro``.

    The normal stores migrate an older database when they open it. A report must not: if the
    ingestion database is not at the current schema version this refuses, and any other command
    (which migrates deliberately) can be run first.
    """

    def __init__(self, data_dir: Path) -> None:
        self.proposals: list[ChangeProposal] = []
        self._evidence: list[tuple[str, LedgerEvidence]] = []  # (seeds_dir, evidence)
        self._confirmed: set[str] = set()
        ingestion = data_dir / "ingestion.sqlite"
        if ingestion.exists():
            with closing(self._connect(ingestion)) as db:
                version = int(db.execute("PRAGMA user_version").fetchone()[0])
                if version != SCHEMA_VERSION:
                    raise ReadinessRefused(
                        f"{ingestion} is at schema version {version}, not {SCHEMA_VERSION}; "
                        "readiness never migrates a database (run another command once to do so)"
                    )
                self.proposals = [
                    ChangeProposal.model_validate_json(row[0])
                    for row in db.execute("SELECT payload FROM change_proposals")
                ]
        ledger = data_dir / "apply.sqlite"
        if ledger.exists():
            with closing(self._connect(ledger)) as db:
                query = (
                    "SELECT a.seeds_dir, e.payload FROM field_evidence e JOIN applications a "
                    "ON a.apply_id = e.apply_id WHERE a.status = 'committed'"
                )
                self._evidence = [
                    (row[0], LedgerEvidence.model_validate_json(row[1]))
                    for row in db.execute(query)
                ]
                self._confirmed = {
                    row[0] for row in db.execute("SELECT snapshot_id FROM confirmations")
                }

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        try:
            return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.Error as error:
            raise ReadinessRefused(f"cannot open {path} read-only: {error}") from error

    def evidence_for(self, seeds: Path, table: str, row_id: str, path: str) -> list[LedgerEvidence]:
        key = str(seeds)
        return [
            e
            for seeds_dir, e in self._evidence
            if seeds_dir == key and (e.table_name, e.row_id, e.field_path) == (table, row_id, path)
        ]

    def origin_confirmed(self, snapshot_id: str) -> bool:
        return snapshot_id in self._confirmed


class _Evidence:
    """Per-fact evidence. Several states can hold at once; all are listed, the strongest leads."""

    def __init__(self, view: ReadOnlyView | None, seeds: Path) -> None:
        self.view, self.seeds = view, seeds
        self.proposals = view.proposals if view is not None else []

    def for_fact(
        self, table: str, row_id: str, path: str, value: Any
    ) -> tuple[list[str], set[str]]:
        notes: list[str] = []
        states: set[str] = set()
        recorded = self.view.evidence_for(self.seeds, table, row_id, path) if self.view else []
        current = [e for e in recorded if e.value_json == canonical_value(value)]
        applied_from = {e.proposal_id for e in current}
        for proposal in self.proposals:
            if proposal.target_table != table or proposal.target_id != row_id:
                continue
            if path not in {f.field_path for f in proposal.field_proposals}:
                continue
            label = _label(proposal.proposal_id)
            if proposal.status == ProposalStatus.PENDING:
                states.add("awaiting_human_review")
                notes.append(f"{label}: pending a curator decision")
            elif proposal.status in {ProposalStatus.APPROVED, ProposalStatus.EDITED}:
                if proposal.proposal_id in applied_from:
                    notes.append(f"{label}: approved and applied")
                else:
                    states.add("approved_not_applied")
                    notes.append(f"{label}: approved, not applied to these seeds")
        for item in recorded:
            if item not in current:
                notes.append(f"apply {item.apply_id}: evidence is for an earlier value (stale)")
                continue
            confirmed = self.view is not None and self.view.origin_confirmed(item.snapshot_id)
            states.add("evidenced" if confirmed else "evidence_recorded_origin_unconfirmed")
            notes.append(
                f"apply {item.apply_id}: evidence recorded in the ledger "
                f"(origin {'confirmed' if confirmed else 'unconfirmed'})"
            )
        return notes, states


def _precedence(states: set[str], row: Mapping[str, Any], value: Any) -> FactState:
    for state in (
        "evidenced",
        "evidence_recorded_origin_unconfirmed",
        "approved_not_applied",
        "awaiting_human_review",
    ):
        if state in states:
            return state
    if value is None:
        return "absent"
    provenance = row.get("provenance") or {}
    if provenance.get("needs_verification", True) or provenance.get("verified_by") == "UNVERIFIED":
        return "unverified_placeholder"
    # The seed's own flags are a claim, not evidence: nothing here corroborates it.
    return "seed_claims_verified"


# ---------------------------------------------------------------------------------------- #
# Gaps: facts the current schema or shipped catalogs cannot hold
# ---------------------------------------------------------------------------------------- #


def schema_and_catalog_gaps(seeds_dir: Path, wallet: UserWallet) -> list[Gap]:
    from welcome.catalog import shipped_offer_catalog
    from welcome.models import CardAcquisitionOffer

    catalog = shipped_offer_catalog()
    shipped = sum(len(catalog.offers_for_card(card_id)) for card_id in wallet.card_ids)
    gaps: list[Gap] = [
        Gap(
            id="welcome_offer_catalog_empty",
            detail=(
                f"The shipped held-card welcome-offer catalog holds {shipped} offers for the "
                f"demonstration wallet's cards ({', '.join(wallet.card_ids)}), so a welcome-status "
                "request answers NO_APPROVED_OFFER. The ingestion tables cannot hold one either "
                "(supported tables: " + ", ".join(sorted(SUPPORTED_TABLES)) + ")."
            ),
            owner="card-acquisition track (welcome/ catalog); this track only prepares evidence",
        )
    ]
    required = [
        name
        for name, field in CardAcquisitionOffer.model_fields.items()
        if field.is_required() and name not in {"id", "provenance"}
    ]
    gaps.append(
        Gap(
            id="welcome_offer_required_fields",
            detail=(
                "A welcome offer needs, per the acquisition model: "
                + ", ".join(required)
                + ", plus exactly one of bonus_points (with bonus_currency_id) or "
                "bonus_flat_minor, verbatim eligibility_exclusions and provenance. An issuer "
                "page that states a bonus but no minimum spend or spend window cannot become "
                "an offer without a model decision (nothing is guessed here)."
            ),
            owner="card-acquisition track",
        )
    )
    programs = yaml.safe_load((seeds_dir / "loyalty_programs.yaml").read_text())
    kinds = sorted({str(p.get("kind")) for p in programs})
    if not [p for p in programs if p.get("kind") == "card_currency"]:
        gaps.append(
            Gap(
                id="no_card_currency_programs",
                detail=(
                    "No loyalty program of kind card_currency is seeded (seeded kinds: "
                    + ", ".join(kinds)
                    + "), so a points welcome bonus has no program identity to be valued through."
                ),
                owner="data owner: verified program identities; acquisition track: model use",
            )
        )
    linked = [n for n in [*Card.model_fields, *PointValuation.model_fields] if "program" in n]
    if not linked:
        gaps.append(
            Gap(
                id="no_card_to_program_link",
                detail=(
                    "Neither Card nor PointValuation carries a program identity, so a card's "
                    "points "
                    "currency cannot be tied to a transfer edge or a welcome bonus currency."
                ),
                owner="schema owner (core models); not changed by this track",
            )
        )
    unknown = sorted(set(wallet.points_balances) - {str(p["id"]) for p in programs})
    if unknown:
        gaps.append(
            Gap(
                id="demo_balance_program_not_seeded",
                detail=(
                    "The demonstration wallet holds points in "
                    + ", ".join(unknown)
                    + ", which is not a seeded loyalty program; the transfer graph and award "
                    "chart in the seeds are fictional placeholders, not India-corridor facts."
                ),
                owner="data owner",
            )
        )
    return gaps


# ---------------------------------------------------------------------------------------- #
# Putting it together
# ---------------------------------------------------------------------------------------- #


def load_findings(path: Path) -> list[Finding]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = raw if isinstance(raw, list) else (raw or {}).get("findings", [])
    return [Finding.model_validate(entry) for entry in entries]


def _row_issuer(table: str, row: Mapping[str, Any], cards: Mapping[str, Mapping[str, Any]]) -> str:
    if table == "cards":
        return str(row["issuer"])
    if table == "offers":
        return str(row.get("issuer") or row.get("merchant") or "any issuer")
    return str(cards.get(str(row.get("card_id")), {}).get("issuer", "unknown"))


def _describe(row: Mapping[str, Any]) -> str:
    return str(
        row.get("name") or row.get("description") or row.get("title") or row.get("path") or ""
    )


def build_readiness(
    *,
    seeds_dir: Path,
    wallet: UserWallet = DEMO_WALLET,
    view: ReadOnlyView | None = None,
    findings: Sequence[Finding] = (),
    data_dir: Path | None = None,
    as_of: datetime,
) -> ReadinessReport:
    source = SeedRowSource(seeds_dir)
    rows = {t: source.table_rows(t) for t in SUPPORTED_TABLES}
    fx_text = (seeds_dir / "fx_rates.yaml").read_text()
    fx = [FxRate.model_validate(r) for r in yaml.safe_load(fx_text)]
    row_effect, fact_effect = probe_influence(rows, fx, wallet)
    cards = {str(r["id"]): r for r in rows["cards"]}
    evidence = _Evidence(view, seeds_dir.resolve())
    by_fact = {(f.table, f.id, f.field): f for f in findings}
    used: set[tuple[str, str, str]] = set()

    out_rows: list[RowReadiness] = []
    for table, row in _relevant(rows, wallet.card_ids):
        row_id = str(row["id"])
        flat = flatten_row(row)
        facts: list[FactReadiness] = []
        row_matters = row_effect.get((table, row_id))
        for path in required_fact_paths(row):
            notes, states = evidence.for_fact(table, row_id, path, flat[path])
            finding = by_fact.get((table, row_id, path))
            if finding is not None:
                used.add((table, row_id, path))
            facts.append(
                FactReadiness(
                    table=table,
                    row_id=row_id,
                    field_path=path,
                    value=flat[path],
                    influence=(influence := fact_effect.get((table, row_id, path), "not_probed")),
                    needed_for_trip=influence == "moves_trip_result"
                    or (influence == "not_probed" and row_matters is not False),
                    state=_precedence(states, row, flat[path]),
                    evidence=notes,
                    finding=finding.verdict if finding else None,
                    finding_note=finding.note if finding else None,
                )
            )
        prov = row.get("provenance") or {}
        out_rows.append(
            RowReadiness(
                table=table,
                row_id=row_id,
                issuer=_row_issuer(table, row, cards),
                description=_describe(row),
                row_influences_trip=row_effect.get((table, row_id)),
                provenance=(
                    f"{prov.get('source_type')} / {prov.get('verified_by')} / "
                    f"needs_verification={prov.get('needs_verification')} / "
                    f"last_verified={prov.get('last_verified')}"
                ),
                facts=facts,
            )
        )

    requests = _evidence_requests(out_rows)
    pending = [p for p in evidence.proposals if p.status == ProposalStatus.PENDING]
    counts: dict[str, int] = {}
    for out_row in out_rows:
        for fact in out_row.facts:
            if fact.needed_for_trip:
                key = f"needed_for_trip:{fact.state}"
                counts[key] = counts.get(key, 0) + 1
    return ReadinessReport(
        trip=TRIP_ID,
        wallet=list(wallet.card_ids),
        seeds_dir=str(seeds_dir),
        data_dir=str(data_dir) if data_dir else None,
        as_of=as_of,
        rows=out_rows,
        evidence_requests=requests,
        gaps=schema_and_catalog_gaps(seeds_dir, wallet),
        owner_decisions=_owner_decisions(pending, requests),
        summary=dict(sorted(counts.items())),
        unmatched_findings=[f for k, f in by_fact.items() if k not in used],
    )


def _evidence_requests(rows: Sequence[RowReadiness]) -> list[EvidenceRequest]:
    grouped: dict[tuple[str, str, str], list[str]] = {}
    for row in rows:
        for fact in row.facts:
            if (not fact.needed_for_trip and fact.finding is None) or fact.field_path == "card_id":
                continue
            if fact.state not in {"unverified_placeholder", "absent"}:
                continue  # a draft or recorded evidence exists: the human decision is next
            situation = (
                "read_but_not_stated_or_unusable"
                if fact.finding
                else "no_draft_or_recorded_finding"
            )
            key = (row.issuer, _DOCUMENT_FOR[row.table], situation)
            grouped.setdefault(key, []).append(f"{row.table}/{row.row_id}:{fact.field_path}")
    return [
        EvidenceRequest(
            issuer=issuer,
            document=document,
            situation=situation,
            facts=sorted(facts),
        )
        for (issuer, document, situation), facts in sorted(grouped.items())
    ]


def _owner_decisions(pending: Sequence[Any], requests: Sequence[EvidenceRequest]) -> list[str]:
    decisions: list[str] = []
    for proposal in sorted(pending, key=lambda p: p.proposal_id):
        fields = ", ".join(f.field_path for f in proposal.field_proposals)
        decisions.append(
            f"Decide proposal {proposal.proposal_id} "
            f"({proposal.target_table}/{proposal.target_id}; "
            f"fields: {fields}): approve, edit or reject after reading its quotes."
        )
    if pending:
        decisions.append(
            "Confirm that your earlier terms review of the source applies to the document "
            "class the pending proposals were staged under (the source policy is a copy "
            "that only you can attest)."
        )
        decisions.append(
            "Decide whether to confirm the capture's origin (confirm-origin) so that approved "
            "evidence "
            "can count toward verification; without it rows stay needs_verification."
        )
    for request in requests:
        if request.situation == "no_draft_or_recorded_finding":
            decisions.append(
                f"Decide whether to capture by hand, within the issuer's terms, or point us to a "
                f"capture already held of: {request.document} ({request.issuer}). "
                f"{len(request.facts)} fact(s) this trip depends on have neither a draft nor a "
                "recorded finding."
            )
    return decisions


# ---------------------------------------------------------------------------------------- #
# Rendering
# ---------------------------------------------------------------------------------------- #

_STATE_TEXT: dict[str, str] = {
    "unverified_placeholder": "placeholder, unverified",
    "absent": "absent",
    "awaiting_human_review": "draft awaiting a curator",
    "seed_claims_verified": "seed claims verified (nothing here corroborates it)",
    "approved_not_applied": "approved, not applied",
    "evidence_recorded_origin_unconfirmed": "evidence recorded, origin unconfirmed",
    "evidenced": "evidenced",
}


def render_readiness_markdown(report: ReadinessReport) -> str:
    lines = [
        f"# Financial-data readiness: {report.trip}",
        "",
        f"As of {report.as_of.isoformat()}. Wallet: {', '.join(report.wallet)}. "
        f"Seeds read: `{report.seeds_dir}` (never written). Ingestion data: "
        f"`{report.data_dir or 'none given'}`.",
        "",
        "Influence is *measured*: each integer fact was doubled and halved, and each text fact "
        "replaced by the other values the seeds hold for it, in memory, and the unchanged "
        'optimizer re-run on this trip. "Not probed" means it could not be varied (a list, or no '
        "sibling value) and **could** matter; it is not reported as harmless. A fact with no "
        "observed effect here may still matter for another trip.",
        "",
        "Facts this trip depends on, by state: "
        + (
            ", ".join(
                f"{key.split(':', 1)[1].replace('_', ' ')} {count}"
                for key, count in report.summary.items()
            )
            or "none"
        ),
        "",
    ]
    for row in report.rows:
        matters = {True: "yes", False: "no", None: "n/a (a card in the wallet)"}[
            row.row_influences_trip
        ]
        lines += [
            f"## {row.table}/{row.row_id}: {row.description} ({row.issuer})",
            "",
            f"Removing this row changes the trip result: {matters}. Provenance: {row.provenance}",
            "",
            "| fact | value | influence | state | capture finding |",
            "|---|---|---|---|---|",
        ]
        quiet: list[tuple[str, str]] = []
        for fact in row.facts:
            if not fact.needed_for_trip and fact.finding is None:
                quiet.append((fact.field_path, fact.state))
                continue
            finding = f"{fact.finding}: {fact.finding_note}" if fact.finding else ""
            state = _STATE_TEXT[fact.state]
            if fact.evidence:
                state += " (" + "; ".join(fact.evidence) + ")"
            lines.append(
                f"| `{fact.field_path}` | {fact.value} | {fact.influence.replace('_', ' ')} "
                f"| {state} | {finding} |"
            )
        if quiet:
            grouped: dict[str, list[str]] = {}
            for path, state in quiet:
                grouped.setdefault(_STATE_TEXT[state], []).append(f"`{path}`")
            summary = "; ".join(f"{k}: {', '.join(v)}" for k, v in grouped.items())
            lines += ["", "Observed not to move this trip: " + summary]
        lines.append("")
    lines += ["## Evidence still to be captured", ""]
    if not report.evidence_requests:
        lines += ["None.", ""]
    for request in report.evidence_requests:
        lines.append(
            f"* **{request.issuer}**, {request.document} ({request.situation.replace('_', ' ')}):"
        )
        lines.append("  " + ", ".join(f"`{f}`" for f in request.facts))
    lines += ["", "## Schema and catalog gaps (data requirements, not drafts)", ""]
    for gap in report.gaps:
        lines += [f"* `{gap.id}`: {gap.detail} *Owner: {gap.owner}.*"]
    lines += ["", "## Decisions only a human can make", ""]
    lines += [f"{i}. {d}" for i, d in enumerate(report.owner_decisions, 1)] or ["None."]
    if report.unmatched_findings:
        lines += ["", "## Findings that matched no fact in scope", ""]
        lines += [
            f"* {f.table}/{f.id}:{f.field} {f.verdict}: {f.note}" for f in report.unmatched_findings
        ]
    lines.append("")
    return "\n".join(lines)
