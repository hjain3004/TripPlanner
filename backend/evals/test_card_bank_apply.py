"""Controlled apply, rollback and recovery, end to end on scratch copies of the seeds.

Real SQLite, the real staging pipeline, review service, activation planner, journaled writer and
apply ledger. Documents are synthetic (``example.invalid``). The repository seeds are hashed
before and after every test and must never change.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.db import SEEDS_DIR, load_kb, seed_database
from core.models import UserWallet
from core.optimizer import optimize
from core.optimizer.demo_data import demo_trip
from evals.test_card_bank_inserts import (
    CARD,
    EARN,
    RULE,
    InsertEnv,
    approve,
    card_insert,
    card_records,
    rec,
    rule_insert,
    rule_records,
)
from evals.test_card_bank_staging import NOW
from ingestion.activation import (
    ActivationBundle,
    ActivationBundleRecord,
    canonical_bundle_bytes,
)
from ingestion.applier import ApplyRefused, ControlledApplier
from ingestion.apply_store import ApplyStore
from ingestion.contracts import PageKind
from ingestion.review_server import build_runtime
from ingestion.seed_writer import SeedWriter
from ingestion.verification import (
    LedgerEvidence,
    canonical_value,
    confirmation_problems,
    evaluate_row,
    new_confirmation,
)

RICH_PAGE = (
    "<html><body><main><p>SYNTHETIC FIXTURE (not issuer content).</p>"
    "<p>Card name: Example Voyager.</p><p>Issued by Synthetic Bank.</p>"
    "<p>Network: visa.</p><p>Country: IN.</p>"
    "<p>The annual fee is INR 2,500 per year.</p><p>Fee currency: INR.</p>"
    "<p>Foreign currency markup is 3.5% on every international transaction.</p>"
    "<p>GST of 18% applies on the markup.</p>"
    "<p>Earn 5 reward points for every INR 150 spent.</p>"
    "<p>Earn 10 reward points for every INR 100 spent on dining.</p>"
    "</main></body></html>"
)
FX = "Foreign currency markup is 3.5% on every international transaction."
EXISTING = "hdfc-infinia"
FILES = (
    "cards.yaml",
    "reward_rules.yaml",
    "offers.yaml",
    "point_valuations.yaml",
)


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def file_hashes(seeds: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(seeds.glob("*.yaml"))
    }


@pytest.fixture(autouse=True)
def repository_seeds_never_change() -> Iterator[None]:
    before = tree_hash(SEEDS_DIR)
    yield
    assert tree_hash(SEEDS_DIR) == before, "a test modified the repository seeds"


def full_card_records() -> list[dict[str, Any]]:
    return card_records() + [
        rec("cards", CARD, "name", "Example Voyager", "Card name: Example Voyager."),
        rec("cards", CARD, "issuer", "Synthetic Bank", "Issued by Synthetic Bank."),
        rec("cards", CARD, "network", "visa", "Network: visa."),
        rec("cards", CARD, "country", "IN", "Country: IN."),
        rec("cards", CARD, "fee_currency", "INR", "Fee currency: INR."),
        rec("cards", CARD, "forex_markup_tax_bp", "18%", "GST of 18% applies on the markup."),
        rec("cards", CARD, "base_earn.currency", "INR", EARN),
    ]


REMAINING_PAGE = (
    "<html><body><main><p>SYNTHETIC FIXTURE detail page (not issuer content).</p>"
    "<p>Card name: Example Voyager.</p><p>Issued by Synthetic Bank.</p>"
    "<p>Network: visa.</p><p>Country: IN.</p><p>Fee currency: INR.</p>"
    "<p>GST of 18% applies on the markup.</p>"
    "<p>Earn 5 reward points for every INR 150 spent.</p>"
    "</main></body></html>"
)


def remaining_records() -> list[dict[str, Any]]:
    return [r for r in full_card_records() if r not in card_records()]


def stage_second_capture(
    env: ApplyEnv,
    *,
    extra_page: str = "",
    extra: list[dict[str, Any]] | None = None,
    records: list[dict[str, Any]] | None = None,
    name: str = "detail",
) -> str:
    """A second, different page of the same issuer that quotes the facts the first one lacked."""
    env.capture.write_text(
        REMAINING_PAGE.replace("</main>", f"<p>page {name}</p>{extra_page}</main>"),
        encoding="utf-8",
    )
    detail = env.target(
        target_id=f"synth-card-{name}",
        canonical_url=f"https://www.example.invalid/card/{name}",
        target_fact_ids=(CARD,),
    )
    outcome = env.put(
        records=(remaining_records() if records is None else records) + (extra or []),
        inserts=[],
        target=detail,
        seeds=env.scratch,
    )
    assert outcome.status == "staged", outcome.refusals
    (staged,) = outcome.proposals
    return staged.proposal_id


class ApplyEnv(InsertEnv):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.capture.write_text(RICH_PAGE, encoding="utf-8")
        self.scratch = root / "scratch_seeds"
        shutil.copytree(SEEDS_DIR, self.scratch)
        self.ledger = ApplyStore(root / "apply.sqlite", now=lambda: NOW)
        self.writer = SeedWriter(state_dir=root / "apply_state", now=lambda: NOW)
        self.applier = ControlledApplier(
            store=self.store,
            service_factory=lambda s: build_runtime(root, s, now=lambda: NOW)[1],
            planner_factory=lambda s: build_runtime(root, s, now=lambda: NOW)[2],
            ledger=self.ledger,
            writer=self.writer,
            now=lambda: NOW,
        )
        self.events = 0

    def evidence(self, table: str, row_id: str) -> list[Any]:
        return self.ledger.active_evidence(table, row_id, str(self.scratch.resolve()))

    def event(self, prefix: str = "evt") -> str:
        self.events += 1
        return f"{prefix}-{self.events:04d}-padding-ok"

    def stage_card(
        self, records: list[dict[str, Any]] | None = None, *, with_rule: bool = False
    ) -> list[str]:
        target = self.facts(CARD, f"reward_rules:{RULE}") if with_rule else self.facts(CARD)
        ids = [
            self.put(
                records=full_card_records() if records is None else records,
                inserts=[
                    {"table": "cards", "id": CARD, "row": {}} if records is None else card_insert()
                ],
                target=target,
                seeds=self.scratch,
            )
            .proposals[0]
            .proposal_id
        ]
        if with_rule:
            ids.append(
                self.put(
                    records=rule_records(),
                    inserts=[rule_insert()],
                    target=target,
                    seeds=self.scratch,
                )
                .proposals[0]
                .proposal_id
            )
        return ids

    def approve_all(self, ids: list[str]) -> None:
        service, _ = self.runtime(self.scratch)
        for index, pid in enumerate(ids):
            approve(service, pid, event=f"approve-{pid[-8:]}-{index:04d}-x")

    def bundle(self, ids: list[str]) -> str:
        _, planner = self.runtime(self.scratch)
        record, _ = planner.build(
            proposal_ids=tuple(ids), curator_id="alice", client_event_id=self.event("bundle")
        )
        return record.bundle_sha256

    def apply(self, sha: str, **over: Any) -> Any:
        args: dict[str, Any] = {
            "bundle_sha256": sha,
            "seeds_dir": self.scratch,
            "curator_id": "alice",
            "reason": "apply synthetic bundle to scratch seeds",
            "client_event_id": self.event("apply"),
        }
        args.update(over)
        return self.applier.apply(**args)

    def confirm(self, pid: str, *, document_class: str = "card_page") -> Any:
        return self.applier.confirm_origin(
            proposal_id=pid,
            document_class=document_class,  # type: ignore[arg-type]
            curator_id="alice",
            statement="I opened the capture and it is the issuer's own card page",
            seeds_dir=self.scratch,
        )

    def row(self, table: str, row_id: str) -> dict[str, Any]:
        from ingestion.review_rows import SeedRowSource

        return SeedRowSource(self.scratch).current_row(table, row_id)


@pytest.fixture
def env(tmp_path: Path) -> ApplyEnv:
    return ApplyEnv(tmp_path)


# ------------------------------------------------------------------ D1: pure matrix


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "x",
        "issuer": "I",
        "fee": 5,
        "optional": None,
        "provenance": {"source_type": "manual_curation", "needs_verification": True},
    }
    row.update(over)
    return row


def _ev(path: str, value: Any, apply_id: str = "a1") -> LedgerEvidence:
    return LedgerEvidence(
        apply_id=apply_id,
        table_name="cards",
        row_id="x",
        field_path=path,
        value_json=canonical_value(value),
        proposal_id="p",
        decision_id="d",
        reviewer_id="alice",
        snapshot_id="s",
        quote="q",
    )


def test_d1_requires_evidence_for_every_valued_non_identity_field() -> None:
    result = evaluate_row(_row(), now_evidence={"fee": canonical_value(5)}, earlier=[])
    assert not result.satisfied and result.missing == ("issuer",)
    done = evaluate_row(
        _row(),
        now_evidence={"fee": canonical_value(5), "issuer": canonical_value("I")},
        earlier=[],
    )
    assert done.satisfied and done.missing == () and done.stale == ()


def test_d1_identity_and_provenance_bookkeeping_never_count_or_are_required() -> None:
    result = evaluate_row(_row(), now_evidence={}, earlier=[])
    assert "id" not in result.required
    assert not any(p.startswith("provenance") for p in result.required)
    assert "optional" not in result.required  # a None asserts nothing
    # evidence offered for identity/provenance cannot satisfy a real field
    forged = evaluate_row(
        _row(),
        now_evidence={"id": canonical_value("x"), "provenance.needs_verification": "true"},
        earlier=[_ev("provenance.source_type", "manual_curation")],
    )
    assert not forged.satisfied and set(forged.missing) == {"fee", "issuer"}


def test_d1_combines_earlier_evidence_only_while_the_value_still_matches() -> None:
    earlier = [_ev("issuer", "I"), _ev("fee", 5)]
    ok = evaluate_row(_row(), now_evidence={}, earlier=earlier)
    assert ok.satisfied and set(ok.evidenced_earlier) == {"issuer", "fee"}
    changed = evaluate_row(_row(fee=6), now_evidence={}, earlier=earlier)
    assert not changed.satisfied and changed.stale == ("fee",) and changed.missing == ()
    # new evidence for the new value supersedes the stale record
    fixed = evaluate_row(_row(fee=6), now_evidence={"fee": canonical_value(6)}, earlier=earlier)
    assert fixed.satisfied and fixed.evidenced_now == ("fee",)


def test_d1_is_all_or_nothing_for_a_partially_evidenced_row() -> None:
    result = evaluate_row(_row(), now_evidence={"fee": canonical_value(5)}, earlier=[])
    assert not result.satisfied and result.evidenced_now == ("fee",)


# ------------------------------------------------------------------ D2


def test_a_confirmation_is_bound_to_the_capture_the_url_and_the_issuer_domain(
    env: ApplyEnv,
) -> None:
    (pid, *_) = env.stage_card()
    ctx = env.runtime(env.scratch)[0].context(pid)
    assert ctx.lineage is not None
    snapshot, target, policy = (
        ctx.lineage.snapshots[0],
        ctx.lineage.watch_target,
        ctx.lineage.source_policy,
    )
    good = new_confirmation(
        snapshot=snapshot,
        target=target,
        policy=policy,
        document_class="card_page",
        curator_id="alice",
        statement="confirmed on the issuer site by hand",
        now=NOW,
    )
    assert confirmation_problems(good, snapshot=snapshot, target=target, policy=policy) == []
    # a different capture
    other = good.model_copy(update={"raw_sha256": "0" * 64})
    assert confirmation_problems(other, snapshot=snapshot, target=target, policy=policy)
    # a URL off the issuer domain is never accepted, however it is confirmed
    off = target.model_copy(update={"canonical_url": "https://www.elsewhere.invalid/card"})
    assert any(
        "issuer domain" in p
        for p in confirmation_problems(
            good.model_copy(update={"canonical_url": off.canonical_url}),
            snapshot=snapshot,
            target=off,
            policy=policy,
        )
    )
    # an aggregator is never an issuer
    agg_policy = policy.model_copy(update={"domain": "www.bankbazaar.com"})
    agg_target = target.model_copy(update={"canonical_url": "https://www.bankbazaar.com/card"})
    assert any(
        "aggregator" in p
        for p in confirmation_problems(
            good.model_copy(update={"canonical_url": agg_target.canonical_url}),
            snapshot=snapshot,
            target=agg_target,
            policy=agg_policy,
        )
    )
    # the document class must match the capture's format
    pdf = good.model_copy(update={"document_class": "tnc_pdf"})
    assert any(
        "format" in p
        for p in confirmation_problems(pdf, snapshot=snapshot, target=target, policy=policy)
    )


def test_confirming_an_origin_is_durable_idempotent_and_immutable(env: ApplyEnv) -> None:
    (pid, *_) = env.stage_card()
    first, created = env.confirm(pid)
    again, created_again = env.confirm(pid)
    assert created and not created_again and first.confirmation_id == again.confirmation_id
    with pytest.raises(ApplyRefused) as refused:
        env.applier.confirm_origin(
            proposal_id=pid,
            document_class="card_page",
            curator_id="alice",
            statement="a different statement about the same capture",
            seeds_dir=env.scratch,
        )
    assert refused.value.code == "confirmation_conflict"
    reopened = ApplyStore(env.root / "apply.sqlite", now=lambda: NOW)
    assert reopened.confirmations_for(first.snapshot_id)[0].statement == first.statement
    assert [e["event"] for e in reopened.events(first.confirmation_id)] == ["created"]


def test_only_a_registered_curator_can_confirm_and_a_pdf_class_needs_a_pdf(env: ApplyEnv) -> None:
    (pid, *_) = env.stage_card()
    with pytest.raises(ApplyRefused) as unknown:
        env.applier.confirm_origin(
            proposal_id=pid,
            document_class="card_page",
            curator_id="mallory",
            statement="I opened the capture and it is the issuer's own page",
            seeds_dir=env.scratch,
        )
    assert unknown.value.code == "unknown_curator"
    with pytest.raises(ApplyRefused) as wrong:
        env.confirm(pid, document_class="tnc_pdf")
    assert wrong.value.code == "origin_not_confirmable"


# ------------------------------------------------------------------ apply: the happy paths


def test_a_fully_evidenced_insert_stays_unverified_until_the_origin_is_confirmed(
    env: ApplyEnv,
) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    sha = env.bundle(ids)
    record = env.apply(sha)
    assert record.status == "committed"
    row = env.row("cards", CARD)
    assert row["provenance"]["needs_verification"] is True
    (outcome,) = record.plan["rows"]
    assert outcome["d1"]["satisfied"] is True and outcome["d2"] == "unconfirmed"
    assert "D2 open" in outcome["reason"]
    # the ledger still holds the evidence it will combine later
    assert len(env.evidence("cards", CARD)) == 11


def test_a_fully_evidenced_insert_with_a_confirmed_origin_clears_needs_verification(
    env: ApplyEnv,
) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    env.confirm(ids[0])
    record = env.apply(env.bundle(ids))
    row = env.row("cards", CARD)
    prov = row["provenance"]
    assert prov["needs_verification"] is False
    assert prov["source_type"] == "official_page" and prov["verified_by"] == "alice"
    assert prov["source_url"] == "https://www.example.invalid/card"
    assert prov["confidence"] == 0.8
    assert record.plan["rows"][0]["d2"] == "confirmed"


def test_a_partially_evidenced_insert_stays_needs_verification_even_with_a_confirmed_origin(
    env: ApplyEnv,
) -> None:
    ids = env.stage_card(records=card_records())  # 4 of 11 facts quoted
    env.approve_all(ids)
    env.confirm(ids[0])
    record = env.apply(env.bundle(ids))
    assert env.row("cards", CARD)["provenance"]["needs_verification"] is True
    d1 = record.plan["rows"][0]["d1"]
    assert d1["satisfied"] is False and len(d1["missing"]) == 7
    assert "D1 open" in record.plan["rows"][0]["reason"]


def test_earlier_applied_evidence_combines_with_a_later_capture_to_satisfy_d1(
    env: ApplyEnv,
) -> None:
    ids = env.stage_card(records=card_records())
    env.approve_all(ids)
    env.confirm(ids[0])  # evidence from an unconfirmed manual capture would not count (D2)
    env.apply(env.bundle(ids))
    assert env.row("cards", CARD)["provenance"]["needs_verification"] is True
    # a second capture confirms the remaining facts, unchanged values
    pid = stage_second_capture(env)
    service, _ = env.runtime(env.scratch)
    approve(service, pid, event="approve-second-capture-0001")
    env.confirm(pid)
    record = env.apply(env.bundle([pid]))
    outcome = record.plan["rows"][0]
    assert outcome["d1"]["satisfied"] and len(outcome["d1"]["evidenced_earlier"]) == 4
    assert env.row("cards", CARD)["provenance"]["needs_verification"] is False


def test_evidence_for_a_value_changed_since_is_invalidated_not_reused(env: ApplyEnv) -> None:
    ids = env.stage_card(records=card_records())
    env.approve_all(ids)
    env.confirm(ids[0])
    env.apply(env.bundle(ids))
    # someone edits the fee in the seeds out of band (the very case stale evidence protects)
    path = env.scratch / "cards.yaml"
    data = yaml.safe_load(path.read_text())
    for row in data:
        if row["id"] == CARD:
            row["annual_fee_minor"] = 999_900
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    pid = stage_second_capture(
        env,
        extra_page="<p>Foreign currency markup is 4.0% from now on.</p>",
        extra=[
            rec(
                "cards",
                CARD,
                "forex_markup_bp",
                "4.0%",
                "Foreign currency markup is 4.0% from now on.",
            )
        ],
    )
    service, _ = env.runtime(env.scratch)
    approve(service, pid, event="approve-second-capture-0001")
    env.confirm(pid)
    record = env.apply(env.bundle([pid]))
    d1 = record.plan["rows"][0]["d1"]
    assert d1["stale"] == ["annual_fee_minor"] and not d1["satisfied"]
    assert env.row("cards", CARD)["provenance"]["needs_verification"] is True


def test_a_card_and_its_rule_apply_together_load_and_drive_the_optimizer(
    env: ApplyEnv, tmp_path: Path
) -> None:
    before = file_hashes(env.scratch)
    ids = env.stage_card(with_rule=True)
    env.approve_all(ids)
    sha = env.bundle(ids)
    record = env.apply(sha)
    assert record.status == "committed"
    after = file_hashes(env.scratch)
    assert {n for n in after if after[n] != before[n]} == {"cards.yaml", "reward_rules.yaml"}
    seed_database(env.scratch, tmp_path / "applied.db")
    kb = load_kb(tmp_path / "applied.db")
    assert CARD in {c.id for c in kb.cards.values()} if hasattr(kb.cards, "values") else True
    result = optimize(demo_trip(), UserWallet(card_ids=[CARD]), kb)
    assert result.assignments and all(a.card_id == CARD for a in result.assignments)
    dining = next(a for a in result.assignments if a.line.id == "dining")
    assert dining.points_earned == 2_000_000 // 10_000 * 10  # Rs20,000 at 10 pts / Rs100


def test_an_update_to_an_existing_card_is_applied_and_keeps_its_other_bytes(
    env: ApplyEnv,
) -> None:
    original = yaml.safe_load((env.scratch / "cards.yaml").read_text())
    outcome = env.put(
        records=[rec("cards", EXISTING, "forex_markup_bp", "3.5%", FX)],
        inserts=[],
        target=env.facts(EXISTING),
        seeds=env.scratch,
    )
    assert outcome.status == "staged", outcome.refusals
    ids = [p.proposal_id for p in outcome.proposals]
    env.approve_all(ids)
    record = env.apply(env.bundle(ids))
    assert env.row("cards", EXISTING)["forex_markup_bp"] == 350
    assert record.plan["rows"][0]["needs_verification"] is True  # placeholders keep it so
    now = yaml.safe_load((env.scratch / "cards.yaml").read_text())
    untouched = [r for r in now if r["id"] != EXISTING]
    assert untouched == [r for r in original if r["id"] != EXISTING]
    # the leading comment block of the seed file survives the rewrite
    assert (env.scratch / "cards.yaml").read_text().startswith("# seeds/cards.yaml")


# ------------------------------------------------------------------ apply: refusals


def refuse(env: ApplyEnv, sha: str, code: str, **over: Any) -> ApplyRefused:
    before = file_hashes(env.scratch)
    with pytest.raises(ApplyRefused) as refused:
        env.apply(sha, **over)
    assert refused.value.code == code, (refused.value.code, str(refused.value))
    assert file_hashes(env.scratch) == before, "a refused apply must not touch the seeds"
    return refused.value


def test_apply_never_writes_inside_the_repository(env: ApplyEnv) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    sha = env.bundle(ids)
    refuse(env, sha, "protected_seeds", seeds_dir=SEEDS_DIR)


def test_apply_refuses_an_unknown_curator_a_short_reason_and_an_unknown_bundle(
    env: ApplyEnv,
) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    sha = env.bundle(ids)
    refuse(env, sha, "unknown_curator", curator_id="mallory")
    refuse(env, sha, "reason_required", reason="short")
    refuse(env, "0" * 64, "unknown_bundle")


def test_a_bundle_built_before_the_seeds_moved_is_stale_and_cannot_be_applied(
    env: ApplyEnv,
) -> None:
    ids = env.stage_card(records=card_records())
    env.approve_all(ids)
    first = env.bundle(ids)
    other = env.put(
        records=[rec("cards", EXISTING, "forex_markup_bp", "3.5%", FX)],
        inserts=[],
        target=env.facts(EXISTING),
        seeds=env.scratch,
    )
    other_ids = [p.proposal_id for p in other.proposals]
    env.approve_all(other_ids)
    second = env.bundle(other_ids)
    env.apply(second)
    refuse(env, first, "stale_bundle")


def test_a_bundle_that_includes_an_unapproved_proposal_is_not_applicable(env: ApplyEnv) -> None:
    ids = env.stage_card()  # staged but never approved
    refuse(env, env.bundle(ids), "dry_run_inconsistent")


def _forged_bundle(env: ApplyEnv, sha: str, mutate: Any) -> str:
    """A bundle whose bytes are genuine for its (new) hash but whose content was altered."""
    _, planner = env.runtime(env.scratch)
    record = ActivationBundleRecord.model_validate_json(env.store.get_activation_bundle(sha) or "")
    bundle = ActivationBundle.model_validate_json(planner.artifacts.read(record.artifact))
    forged = mutate(bundle)
    body = canonical_bundle_bytes(forged)
    digest = hashlib.sha256(body).hexdigest()
    artifact = planner.artifacts.put(body, media_type="application/json")
    env.store.put_activation_bundle(
        ActivationBundleRecord(
            bundle_sha256=digest, artifact=artifact, proposal_ids=record.proposal_ids
        ).model_dump_json(),
        bundle_sha256=digest,
        client_event_id=env.event("forged"),
        request_fingerprint=hashlib.sha256(digest.encode()).hexdigest(),
        created_by="alice",
    )
    return digest


def test_a_forged_bundle_row_is_caught_by_rederiving_it_from_the_approval(
    env: ApplyEnv,
) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    sha = env.bundle(ids)

    def cheaper(bundle: ActivationBundle) -> ActivationBundle:
        entry = bundle.entries[0]
        row = json.loads(json.dumps(entry.new_row))
        row["annual_fee_minor"] = 1
        forged = entry.model_copy(update={"new_row": row})
        return bundle.model_copy(update={"entries": (forged,)})

    refuse(env, _forged_bundle(env, sha, cheaper), "entry_tampered")


def test_a_forged_decision_id_is_not_the_latest_approval(env: ApplyEnv) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    sha = env.bundle(ids)

    def other_decision(bundle: ActivationBundle) -> ActivationBundle:
        forged = bundle.entries[0].model_copy(update={"decision_id": "decision-that-never-was"})
        return bundle.model_copy(update={"entries": (forged,)})

    refuse(env, _forged_bundle(env, sha, other_decision), "decision_changed")


def test_a_legacy_schema_bundle_is_never_applied(env: ApplyEnv) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    sha = env.bundle(ids)
    _, planner = env.runtime(env.scratch)
    record = ActivationBundleRecord.model_validate_json(env.store.get_activation_bundle(sha) or "")
    body = json.loads(planner.artifacts.read(record.artifact))
    body["schema_version"] = "tripwise.financial-activation-bundle/v1"
    raw = json.dumps(body, sort_keys=True).encode()
    digest = hashlib.sha256(raw).hexdigest()
    artifact = planner.artifacts.put(raw, media_type="application/json")
    env.store.put_activation_bundle(
        ActivationBundleRecord(
            bundle_sha256=digest, artifact=artifact, proposal_ids=record.proposal_ids
        ).model_dump_json(),
        bundle_sha256=digest,
        client_event_id=env.event("legacy"),
        request_fingerprint=hashlib.sha256(digest.encode()).hexdigest(),
        created_by="alice",
    )
    refuse(env, digest, "bundle_schema")


def test_a_tampered_bundle_artifact_is_refused(env: ApplyEnv) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    sha = env.bundle(ids)
    record = ActivationBundleRecord.model_validate_json(env.store.get_activation_bundle(sha) or "")
    files = [p for p in (env.root / "artifacts").rglob("*") if p.is_file()]
    target = next(p for p in files if sha in p.name or p.read_bytes()[:1] == b"{")
    assert record.artifact is not None
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ApplyRefused) as refused:
        env.apply(sha)
    assert refused.value.code in {"bundle_tampered", "bundle_unreadable"}


def test_an_insert_whose_id_appeared_in_the_seeds_is_refused_not_merged(env: ApplyEnv) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    sha = env.bundle(ids)
    path = env.scratch / "cards.yaml"
    data = yaml.safe_load(path.read_text())
    clone = dict(data[0])
    clone["id"] = CARD
    path.write_text(yaml.safe_dump([*data, clone], sort_keys=False))
    refuse(env, sha, "stale_bundle")


def test_a_replayed_apply_returns_the_original_and_a_conflicting_replay_is_refused(
    env: ApplyEnv,
) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    sha = env.bundle(ids)
    first = env.apply(sha, client_event_id="apply-replay-event-0001")
    after = file_hashes(env.scratch)
    again = env.apply(sha, client_event_id="apply-replay-event-0001")
    assert again.apply_id == first.apply_id and again.status == "committed"
    assert file_hashes(env.scratch) == after
    refuse(
        env,
        sha,
        "idempotency_conflict",
        client_event_id="apply-replay-event-0001",
        reason="a different reason for the same event id",
    )
    refuse(env, sha, "stale_bundle")  # a new event id cannot re-apply a spent bundle


# ------------------------------------------------------------------ rollback


def test_rollback_restores_exact_prior_bytes_and_withdraws_the_evidence(env: ApplyEnv) -> None:
    before = file_hashes(env.scratch)
    ids = env.stage_card(with_rule=True)
    env.approve_all(ids)
    record = env.apply(env.bundle(ids))
    assert file_hashes(env.scratch) != before
    assert env.evidence("cards", CARD)
    rolled = env.applier.rollback(
        apply_id=record.apply_id, curator_id="alice", reason="synthetic demonstration rollback"
    )
    assert rolled.status == "rolled_back"
    assert file_hashes(env.scratch) == before
    assert env.evidence("cards", CARD) == []  # rolled-back evidence no longer counts
    events = [e["event"] for e in env.ledger.events(record.apply_id)]
    assert events == ["planned", "committed", "rolled_back"]  # history is retained
    again = env.applier.rollback(
        apply_id=record.apply_id, curator_id="alice", reason="repeating the same rollback"
    )
    assert again.status == "rolled_back"
    assert not list(env.scratch.glob("*.tmp"))


def test_rollback_refuses_to_overwrite_a_later_unrelated_change(env: ApplyEnv) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    record = env.apply(env.bundle(ids))
    path = env.scratch / "cards.yaml"
    path.write_text(path.read_text() + "\n# a later human edit\n")
    changed = file_hashes(env.scratch)
    with pytest.raises(ApplyRefused) as refused:
        env.applier.rollback(
            apply_id=record.apply_id, curator_id="alice", reason="trying to undo too much"
        )
    assert refused.value.code == "changed_since_apply"
    assert file_hashes(env.scratch) == changed
    assert env.ledger.get_application(record.apply_id).status == "committed"  # type: ignore[union-attr]


def test_rollback_of_something_never_committed_is_refused(env: ApplyEnv) -> None:
    with pytest.raises(ApplyRefused) as refused:
        env.applier.rollback(
            apply_id="apply-nope", curator_id="alice", reason="there is nothing to undo"
        )
    assert refused.value.code == "unknown_apply"


# ------------------------------------------------------------------ interruption and recovery


class Crash(RuntimeError):
    pass


def crash_at(name: str) -> Any:
    def checkpoint(step: str) -> None:
        if step == name:
            raise Crash(step)

    return checkpoint


@pytest.mark.parametrize("step", ["planned", "backed_up", "staged", "committing", "replaced:1"])
def test_an_apply_interrupted_before_every_file_changed_is_rolled_back_by_recovery(
    env: ApplyEnv, step: str
) -> None:
    before = file_hashes(env.scratch)
    ids = env.stage_card(with_rule=True)
    env.approve_all(ids)
    sha = env.bundle(ids)
    with pytest.raises(Crash):
        env.apply(sha, client_event_id="apply-interrupted-0001", checkpoint=crash_at(step))
    # no further operation is allowed while the interrupted one is unresolved
    refuse(env, sha, "incomplete_apply", client_event_id="apply-after-crash-0001")
    outcomes = env.applier.recover(env.scratch)
    assert len(outcomes) == 1
    assert file_hashes(env.scratch) == before
    assert not list(env.scratch.glob("*.tmp"))
    record = env.ledger.application_for_event("apply-interrupted-0001")
    assert record is not None and record.status == "aborted"
    assert env.evidence("cards", CARD) == []
    # the system is usable again and the same bundle can be applied
    assert env.apply(sha, client_event_id="apply-retry-after-recover-1").status == "committed"


def test_an_apply_interrupted_after_every_file_changed_is_completed_by_recovery(
    env: ApplyEnv,
) -> None:
    ids = env.stage_card(with_rule=True)
    env.approve_all(ids)
    sha = env.bundle(ids)
    with pytest.raises(Crash):
        env.apply(sha, client_event_id="apply-interrupted-0002", checkpoint=crash_at("replaced:2"))
    applied = file_hashes(env.scratch)
    assert env.applier.recover(env.scratch)[0][1] == "committed"
    assert file_hashes(env.scratch) == applied
    record = env.ledger.application_for_event("apply-interrupted-0002")
    assert record is not None and record.status == "committed"
    assert len(env.evidence("cards", CARD)) == 11


def test_a_crash_after_the_journal_committed_but_before_the_ledger_is_reconciled(
    env: ApplyEnv,
) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    with pytest.raises(Crash):
        env.apply(
            env.bundle(ids),
            client_event_id="apply-interrupted-0003",
            checkpoint=crash_at("committed"),
        )
    record = env.ledger.application_for_event("apply-interrupted-0003")
    assert record is not None and record.status == "planned"
    env.applier.recover(env.scratch)
    record = env.ledger.application_for_event("apply-interrupted-0003")
    assert record is not None and record.status == "committed"
    assert env.evidence("cards", CARD)


def test_an_interrupted_rollback_is_finished_by_recovery(env: ApplyEnv) -> None:
    before = file_hashes(env.scratch)
    ids = env.stage_card(with_rule=True)
    env.approve_all(ids)
    record = env.apply(env.bundle(ids))
    with pytest.raises(Crash):
        env.applier.rollback(
            apply_id=record.apply_id,
            curator_id="alice",
            reason="interrupted demonstration rollback",
            checkpoint=crash_at("restored:1"),
        )
    env.applier.recover(env.scratch)
    assert file_hashes(env.scratch) == before
    assert env.ledger.get_application(record.apply_id).status == "rolled_back"  # type: ignore[union-attr]
    assert env.evidence("cards", CARD) == []


# ------------------------------------------------------------------ coverage and durability


def test_coverage_reports_per_row_d1_state_from_the_ledger(env: ApplyEnv) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    env.confirm(ids[0])
    env.apply(env.bundle(ids))
    by_id = {(r["table"], r["row_id"]): r for r in env.applier.coverage(env.scratch)}
    assert by_id[("cards", CARD)]["d1_satisfied"] is True
    assert by_id[("cards", CARD)]["needs_verification"] is False
    assert by_id[("cards", EXISTING)]["d1_satisfied"] is False


def test_the_ledger_survives_reopening(env: ApplyEnv) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    record = env.apply(env.bundle(ids))
    reopened = ApplyStore(env.root / "apply.sqlite", now=lambda: NOW)
    stored = reopened.get_application(record.apply_id)
    assert stored is not None and stored.status == "committed"
    assert len(reopened.active_evidence("cards", CARD, str(env.scratch.resolve()))) == 11


def test_a_second_apply_on_a_different_scratch_copy_is_independent(
    env: ApplyEnv, tmp_path: Path
) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    sha = env.bundle(ids)
    other = tmp_path / "scratch_two"
    shutil.copytree(SEEDS_DIR, other)
    one = file_hashes(other)
    env.apply(sha)
    assert file_hashes(other) == one  # the other copy was never touched
    assert PageKind.MANUAL_CAPTURE and datetime.now(UTC)  # imports used


# ================================================================== independent-review regressions


def test_evidence_from_an_unconfirmed_capture_does_not_count_toward_d1(env: ApplyEnv) -> None:
    """D2 follows the evidence: 4 facts from a never-confirmed capture cannot ride along."""
    ids = env.stage_card(records=card_records())
    env.approve_all(ids)
    env.apply(env.bundle(ids))  # no confirmation for this capture
    pid = stage_second_capture(env)
    service, _ = env.runtime(env.scratch)
    approve(service, pid, event="approve-second-capture-0001")
    env.confirm(pid)  # only the second capture is confirmed
    record = env.apply(env.bundle([pid]))
    d1 = record.plan["rows"][0]["d1"]
    assert not d1["satisfied"] and len(d1["missing"]) == 4 and d1["evidenced_earlier"] == []
    assert env.row("cards", CARD)["provenance"]["needs_verification"] is True


def test_evidence_only_confirmations_accumulate_across_captures(env: ApplyEnv) -> None:
    """Three captures: 4 facts, then 3 more (nothing in the file changes), then the last 4."""
    ids = env.stage_card(records=card_records())
    env.approve_all(ids)
    env.confirm(ids[0])
    env.apply(env.bundle(ids))
    remaining = remaining_records()
    second = stage_second_capture(env, records=remaining[:3], name="second")
    third = stage_second_capture(env, records=remaining[3:], name="third")
    service, _ = env.runtime(env.scratch)
    for index, pid in enumerate((second, third)):
        approve(service, pid, event=f"approve-accumulate-{index:04d}-x")
        env.confirm(pid)
    before = file_hashes(env.scratch)
    middle = env.apply(env.bundle([second]))
    assert middle.plan["ledger_only"] is True and middle.status == "committed"
    assert file_hashes(env.scratch) == before  # evidence recorded, no file touched
    assert len(env.evidence("cards", CARD)) == 7
    last = env.apply(env.bundle([third]))
    assert last.plan["rows"][0]["d1"]["satisfied"] is True
    assert env.row("cards", CARD)["provenance"]["needs_verification"] is False
    # rolling a ledger-only application back withdraws its evidence and touches no file
    env.applier.rollback(
        apply_id=middle.apply_id, curator_id="alice", reason="withdraw the middle capture"
    )
    assert len(env.evidence("cards", CARD)) == 11 - 3


def test_a_planned_write_is_refused_if_the_seeds_changed_after_planning(
    env: ApplyEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    sha = env.bundle(ids)
    original = env.ledger.begin_application

    def edit_then_begin(*args: Any, **kwargs: Any) -> Any:
        path = env.scratch / "cards.yaml"
        path.write_text(path.read_text() + "\n# a human edit made after planning\n")
        return original(*args, **kwargs)

    monkeypatch.setattr(env.ledger, "begin_application", edit_then_begin)
    with pytest.raises(ApplyRefused) as refused:
        env.apply(sha, client_event_id="apply-raced-event-0001")
    assert refused.value.code == "seeds_changed"
    assert "a human edit made after planning" in (env.scratch / "cards.yaml").read_text()
    record = env.ledger.application_for_event("apply-raced-event-0001")
    assert record is not None and record.status == "aborted"
    assert env.evidence("cards", CARD) == []


def test_a_second_operation_on_the_same_seed_directory_is_refused_while_one_is_running(
    env: ApplyEnv,
) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    sha = env.bundle(ids)
    other_process = SeedWriter(state_dir=env.root / "apply_state", now=lambda: NOW)
    with other_process.locked(env.scratch):
        refuse(env, sha, "locked")
        with pytest.raises(ApplyRefused) as refused:
            env.applier.recover(env.scratch)
        assert refused.value.code == "locked"
    assert env.apply(sha).status == "committed"  # released: the lock never outlives its holder
    assert not list((env.root / "apply_state" / "locks").glob("*.lock"))


def test_a_rolled_back_apply_stops_counting_even_if_its_ledger_write_failed(
    env: ApplyEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    record = env.apply(env.bundle(ids))
    real = env.ledger.set_status

    def fail_once(apply_id: str, status: str, **kwargs: Any) -> Any:
        if status == "rolled_back":
            monkeypatch.setattr(env.ledger, "set_status", real)
            raise RuntimeError("database is locked")
        return real(apply_id, status, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(env.ledger, "set_status", fail_once)
    with pytest.raises(RuntimeError):
        env.applier.rollback(
            apply_id=record.apply_id, curator_id="alice", reason="rollback whose ledger write dies"
        )
    assert env.evidence("cards", CARD)  # the ledger still (wrongly) says committed
    env.applier.coverage(env.scratch)  # any apply or coverage reconciles first
    assert env.evidence("cards", CARD) == []
    assert env.ledger.get_application(record.apply_id).status == "rolled_back"  # type: ignore[union-attr]


def test_an_apply_reconciles_the_ledger_before_it_counts_any_evidence(
    env: ApplyEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    record = env.apply(env.bundle(ids))
    real = env.ledger.set_status

    def fail_once(apply_id: str, status: str, **kwargs: Any) -> Any:
        if status == "rolled_back":
            monkeypatch.setattr(env.ledger, "set_status", real)
            raise RuntimeError("database is locked")
        return real(apply_id, status, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(env.ledger, "set_status", fail_once)
    with pytest.raises(RuntimeError):
        env.applier.rollback(
            apply_id=record.apply_id, curator_id="alice", reason="rollback whose ledger write dies"
        )
    other = env.put(
        records=[rec("cards", EXISTING, "forex_markup_bp", "3.5%", FX)],
        inserts=[],
        target=env.target(
            target_id="synth-card-other",
            canonical_url="https://www.example.invalid/card/other",
            target_fact_ids=(EXISTING,),
        ),
        seeds=env.scratch,
    )
    assert other.status == "staged", other.refusals
    other_ids = [p.proposal_id for p in other.proposals]
    service, _ = env.runtime(env.scratch)
    approve(service, other_ids[0], event="approve-other-event-0001")
    env.apply(env.bundle(other_ids))  # no coverage call: the apply itself must reconcile
    assert env.evidence("cards", CARD) == []


def test_a_second_recover_finishes_a_ledger_left_open_by_a_crashed_recover(
    env: ApplyEnv,
) -> None:
    ids = env.stage_card(with_rule=True)
    env.approve_all(ids)
    with pytest.raises(Crash):
        env.apply(
            env.bundle(ids), client_event_id="apply-m1-event-0001", checkpoint=crash_at("staged")
        )
    env.writer.recover(env.scratch)  # the journal is resolved, then the process "dies"
    record = env.ledger.application_for_event("apply-m1-event-0001")
    assert record is not None and record.status == "planned"
    env.applier.recover(env.scratch)
    record = env.ledger.application_for_event("apply-m1-event-0001")
    assert record is not None and record.status == "aborted"


def test_yaml_that_would_not_load_back_to_the_approved_row_is_refused(env: ApplyEnv) -> None:
    """PyYAML turns U+0085 into a space on a round trip; the written file must be checked."""
    # the template route is the only way an un-quoted string can reach a row
    partial = env.put(
        records=card_records(),
        inserts=[card_insert(name="Example\u0085Voyager")],
        target=env.facts(CARD),
        seeds=env.scratch,
    )
    assert partial.status == "staged", partial.refusals
    ids = [p.proposal_id for p in partial.proposals]
    env.approve_all(ids)
    refuse(env, env.bundle(ids), "render_mismatch")


def test_a_hash_valid_bundle_cannot_forge_provenance_or_ledger_fields(env: ApplyEnv) -> None:
    from ingestion.activation import ProvenanceCandidate

    ids = env.stage_card()
    env.approve_all(ids)
    sha = env.bundle(ids)

    def forge_candidate(bundle: ActivationBundle) -> ActivationBundle:
        entry = bundle.entries[0]
        candidate = ProvenanceCandidate(
            source_type="official_page",
            verified_by="bob-never-approved",
            last_verified="2031-01-01",
            source_url="https://www.example.invalid/NOT-THE-CAPTURE",
            confidence=0.99,
        )
        forged = entry.model_copy(update={"provenance_candidate": candidate})
        return bundle.model_copy(update={"entries": (forged,)})

    def forge_reviewer(bundle: ActivationBundle) -> ActivationBundle:
        forged = bundle.entries[0].model_copy(update={"reviewer_id": "mallory"})
        return bundle.model_copy(update={"entries": (forged,)})

    def forge_evidenced(bundle: ActivationBundle) -> ActivationBundle:
        entry = bundle.entries[0]
        forged = entry.model_copy(update={"evidenced_fields": entry.evidenced_fields[:-1]})
        return bundle.model_copy(update={"entries": (forged,)})

    for forge in (forge_candidate, forge_reviewer, forge_evidenced):
        error = refuse(env, _forged_bundle(env, sha, forge), "entry_tampered")
        assert "differs" in str(error)


def test_a_bundle_listing_one_row_twice_is_refused(env: ApplyEnv) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    sha = env.bundle(ids)

    def twice(bundle: ActivationBundle) -> ActivationBundle:
        return bundle.model_copy(update={"entries": (bundle.entries[0], bundle.entries[0])})

    refuse(env, _forged_bundle(env, sha, twice), "duplicate_entry")


def test_unknown_proposals_and_malformed_bundles_are_typed_refusals(env: ApplyEnv) -> None:
    with pytest.raises(ApplyRefused) as unknown:
        env.applier.confirm_origin(
            proposal_id="proposal:nothing",
            document_class="card_page",
            curator_id="alice",
            statement="there is no such proposal at all",
            seeds_dir=env.scratch,
        )
    assert unknown.value.code == "unknown_proposal"
    ids = env.stage_card()
    env.approve_all(ids)
    sha = env.bundle(ids)

    def no_hashes(bundle: ActivationBundle) -> ActivationBundle:
        return bundle.model_copy(update={"seed_files": {}})

    refuse(env, _forged_bundle(env, sha, no_hashes), "bundle_invalid")


def test_the_repository_guard_does_not_depend_on_which_checkout_is_running(
    env: ApplyEnv, tmp_path: Path
) -> None:
    """Any directory under a git checkout is refused, e.g. a sibling clone's real seeds."""
    clone = tmp_path / "some_other_clone"
    (clone / ".git").mkdir(parents=True)
    shutil.copytree(SEEDS_DIR, clone / "backend" / "core" / "seeds")
    ids = env.stage_card()
    env.approve_all(ids)
    sha = env.bundle(ids)
    with pytest.raises(ApplyRefused) as refused:
        env.apply(sha, seeds_dir=clone / "backend" / "core" / "seeds")
    assert refused.value.code == "inside_git_checkout"
    # a clone that is a git *worktree* has a .git file, not a directory
    worktree = tmp_path / "a_worktree"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: /elsewhere")
    shutil.copytree(SEEDS_DIR, worktree / "seeds")
    with pytest.raises(ApplyRefused) as second:
        env.apply(sha, seeds_dir=worktree / "seeds")
    assert second.value.code == "inside_git_checkout"


def test_symlinked_seed_files_are_refused(env: ApplyEnv, tmp_path: Path) -> None:
    link_dir = tmp_path / "linked"
    shutil.copytree(env.scratch, link_dir)
    real = tmp_path / "real_cards.yaml"
    shutil.move(link_dir / "cards.yaml", real)
    (link_dir / "cards.yaml").symlink_to(real)
    ids = env.stage_card()
    env.approve_all(ids)
    with pytest.raises(ApplyRefused) as refused:
        env.apply(env.bundle(ids), seeds_dir=link_dir)
    assert refused.value.code == "seed_file_is_symlink"


def test_evidence_does_not_travel_between_seed_directories(env: ApplyEnv, tmp_path: Path) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    env.apply(env.bundle(ids))
    other = tmp_path / "second_scratch"
    shutil.copytree(SEEDS_DIR, other)
    assert env.ledger.active_evidence("cards", CARD, str(other.resolve())) == []
    assert len(env.evidence("cards", CARD)) == 11


def test_rollback_must_name_the_seed_directory_the_apply_was_made_on(
    env: ApplyEnv, tmp_path: Path
) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    record = env.apply(env.bundle(ids))
    other = tmp_path / "elsewhere"
    shutil.copytree(SEEDS_DIR, other)
    with pytest.raises(ApplyRefused) as refused:
        env.applier.rollback(
            apply_id=record.apply_id,
            curator_id="alice",
            reason="naming the wrong directory",
            seeds_dir=other,
        )
    assert refused.value.code == "wrong_seeds_dir"


def test_an_approval_superseded_by_a_newer_capture_is_refused_at_apply(env: ApplyEnv) -> None:
    ids = env.stage_card()
    env.approve_all(ids)
    sha = env.bundle(ids)
    env.capture.write_text(RICH_PAGE.replace("SYNTHETIC FIXTURE", "SYNTHETIC FIXTURE v2"))
    env.put(
        records=full_card_records(),
        inserts=[{"table": "cards", "id": CARD, "row": {}}],
        target=env.facts(CARD),
        seeds=env.scratch,
    )
    refuse(env, sha, "blocking_finding")


def test_an_edited_update_applies_exactly_the_edited_row(env: ApplyEnv) -> None:
    from ingestion.review_types import CuratorFieldEdit, DecisionRequest

    outcome = env.put(
        records=[rec("cards", EXISTING, "forex_markup_bp", "3.5%", FX)],
        inserts=[],
        target=env.facts(EXISTING),
        seeds=env.scratch,
    )
    (staged,) = outcome.proposals
    service, _ = env.runtime(env.scratch)
    ctx = service.context(staged.proposal_id)
    assert ctx.lineage is not None
    fee_quote = "The annual fee is INR 2,500 per year."
    service.decide(
        DecisionRequest(
            proposal_id=staged.proposal_id,
            action="edit",
            reason="also take the fee from the same page",
            expected_version=1,
            client_event_id="edit-decision-event-0001",
            curator_confidence=0.7,
            edits=(
                CuratorFieldEdit(
                    field_path="annual_fee_minor",
                    action="set",
                    proposed_raw_value="INR 2,500",
                    quote=fee_quote,
                    occurrence=1,
                    snapshot_id=ctx.lineage.snapshots[0].snapshot_id,
                ),
            ),
        ),
        curator_id="alice",
    )
    record = env.apply(env.bundle([staged.proposal_id]))
    row = env.row("cards", EXISTING)
    assert row["forex_markup_bp"] == 350 and row["annual_fee_minor"] == 250_000
    evidenced = {e.field_path for e in env.evidence("cards", EXISTING)}
    assert evidenced == {"forex_markup_bp", "annual_fee_minor"}
    assert record.status == "committed"
