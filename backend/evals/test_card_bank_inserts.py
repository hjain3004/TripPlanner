"""Insert proposals: a new card/rule/valuation row, from capture to a ``would_insert`` dry-run.

Real SQLite, the real staging pipeline, review service, activation planner and review web app.
Documents are synthetic (``example.invalid``) and say nothing about any real issuer. The seeds
are never written: tests that need the id to appear later copy them.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from core.db import SEEDS_DIR
from evals.test_card_bank_staging import NOW, Env, refusal_codes, rows
from ingestion.contracts import ChangeProposal, FieldProposal, PageKind
from ingestion.insert_validation import absent_row_hash
from ingestion.review_app import ReviewAppConfig, SessionRegistry, create_review_app
from ingestion.review_server import build_runtime
from ingestion.review_types import DecisionRequest, ReviewRefusedError
from ingestion.staging import CuratorExtraction, StageOutcome, StageRefusalCode, stage_capture
from ingestion.storage import FinancialIngestionStore

INSERT_PAGE = (
    "<html><body><main>"
    "<p>SYNTHETIC FIXTURE Example Voyager Card (not issuer content).</p>"
    "<p>The annual fee is INR 2,500 per year.</p>"
    "<p>Foreign currency markup is 3.5% on every international transaction.</p>"
    "<p>Earn 5 reward points for every INR 150 spent.</p>"
    "<p>Earn 10 reward points for every INR 100 spent on dining.</p>"
    "<p>Each point is worth INR 0.40 when redeemed for cashback.</p>"
    "</main></body></html>"
)
CARD = "synthetic-voyager"
RULE = "synthetic-voyager-dining"
EARN = "Earn 5 reward points for every INR 150 spent."
DINING = "Earn 10 reward points for every INR 100 spent on dining."
VALUE = "Each point is worth INR 0.40 when redeemed for cashback."
VALUATION = "synthetic-voyager-cashback-val"


def card_insert(**row_over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "issuer": "Synthetic Bank",
        "network": "visa",
        "country": "IN",
        "name": "Example Voyager",
        "fee_currency": "INR",
        "forex_markup_tax_bp": 1800,
        "base_earn": {"currency": "INR"},
    }
    row.update(row_over)
    return {"table": "cards", "id": CARD, "row": row}


def rule_insert() -> dict[str, Any]:
    return {
        "table": "reward_rules",
        "id": RULE,
        "row": {
            "card_id": CARD,
            "description": "Dining accelerated earn (synthetic)",
            "categories": ["dining"],
            "earn": {"currency": "INR"},
        },
    }


def rec(table: str, row_id: str, path: str, raw: str, quote: str, **extra: Any) -> dict[str, Any]:
    return {
        "table": table,
        "id": row_id,
        "field_path": path,
        "raw_value": raw,
        "quote": quote,
        **extra,
    }


def card_records() -> list[dict[str, Any]]:
    fee = "The annual fee is INR 2,500 per year."
    fx = "Foreign currency markup is 3.5% on every international transaction."
    return [
        rec("cards", CARD, "annual_fee_minor", "INR 2,500", fee),
        rec("cards", CARD, "forex_markup_bp", "3.5%", fx),
        rec("cards", CARD, "base_earn.points", "5", EARN),
        rec("cards", CARD, "base_earn.per_amount_minor", "INR 150", EARN),
    ]


def rule_records() -> list[dict[str, Any]]:
    return [
        rec("reward_rules", RULE, "earn.points", "10", DINING),
        rec("reward_rules", RULE, "earn.per_amount_minor", "INR 100", DINING),
    ]


class InsertEnv(Env):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.capture.write_text(INSERT_PAGE, encoding="utf-8")

    def facts(self, *ids: str) -> Any:
        return self.target(target_fact_ids=ids or (CARD,))

    def put(
        self,
        records: list[dict[str, Any]] | None = None,
        inserts: list[dict[str, Any]] | None = None,
        *,
        target: Any = None,
        seeds: Path | None = None,
        curator: str = "alice",
        now: Any = None,
    ) -> StageOutcome:
        extraction = CuratorExtraction.model_validate(
            {
                "schema": "tripwise.curator-extraction/v1",
                "curator_id": curator,
                "records": card_records() if records is None else records,
                "inserts": [card_insert()] if inserts is None else inserts,
            }
        )
        return stage_capture(
            store=self.store,
            artifacts=self.artifacts,
            seeds_dir=seeds or self.seeds,
            capture_path=self.capture,
            policy=self.policy(),
            target=target or self.facts(),
            extraction=extraction,
            document_class=PageKind.CARD_PAGE,
            now=now or (lambda: NOW),
        )

    def runtime(self, seeds: Path | None = None) -> tuple[Any, Any]:
        _, service, planner = build_runtime(self.root, seeds or self.seeds, now=lambda: NOW)
        return service, planner


@pytest.fixture
def env(tmp_path: Path) -> InsertEnv:
    return InsertEnv(tmp_path)


def scratch_seeds(tmp_path: Path, *, taken: tuple[str, str] | None = None) -> Path:
    """A writable copy of the seeds; ``taken=(table_file, id)`` makes that id already exist."""
    seeds = tmp_path / "seeds"
    shutil.copytree(SEEDS_DIR, seeds)
    if taken is not None:
        filename, row_id = taken
        data = yaml.safe_load((seeds / filename).read_text())
        row = copy.deepcopy(data[0])
        row["id"] = row_id
        data.append(row)
        (seeds / filename).write_text(yaml.safe_dump(data, sort_keys=False))
    return seeds


def approve(service: Any, proposal_id: str, *, event: str = "approve-insert-event-0001") -> Any:
    return service.decide(
        DecisionRequest(
            proposal_id=proposal_id,
            action="approve",
            reason="synthetic insert reviewed",
            expected_version=1,
            client_event_id=event,
            curator_confidence=0.8,
        ),
        curator_id="alice",
    )


# ------------------------------------------------------------------ contract


def _update_proposal(**over: Any) -> ChangeProposal:
    from ingestion.contracts import EvidenceSpan

    span = EvidenceSpan(
        snapshot_id="s",
        snapshot_hash="0" * 64,
        quote="q",
        normalized_start=0,
        normalized_end=1,
        field_path="a",
        verification="exact",
    )
    base: dict[str, Any] = {
        "proposal_id": "p",
        "target_table": "cards",
        "target_id": "x",
        "current_row_hash": "1" * 64,
        "proposed_row": {"id": "x"},
        "field_proposals": (FieldProposal(field_path="a", evidence_spans=(span,)),),
        "change_summary": "c",
        "extractor_version": "v",
        "lineage_ids": ("s",),
        "version": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return ChangeProposal(**{**base, **over})


def test_an_update_proposal_serializes_exactly_as_it_did_before_inserts_existed() -> None:
    """Stored bytes (and the payload hash a decision attests) must not change for updates."""
    update = _update_proposal()
    assert "intent" not in json.loads(update.model_dump_json())
    assert "intent" not in update.model_dump(mode="json")
    insert = _update_proposal(intent="insert", current_row_hash=None)
    assert json.loads(insert.model_dump_json())["intent"] == "insert"
    assert ChangeProposal.model_validate_json(insert.model_dump_json()).intent == "insert"
    assert ChangeProposal.model_validate_json(update.model_dump_json()).intent == "update"


def test_an_insert_proposal_cannot_claim_a_base_row() -> None:
    with pytest.raises(ValueError, match="no base row"):
        _update_proposal(intent="insert", current_row_hash="1" * 64)


def test_the_absence_hash_binds_the_table_and_the_id() -> None:
    assert absent_row_hash("cards", "a") != absent_row_hash("cards", "b")
    assert absent_row_hash("cards", "a") != absent_row_hash("offers", "a")
    assert absent_row_hash("cards", "a") == absent_row_hash("cards", "a")


# ------------------------------------------------------------------ staging an insert


def test_a_new_card_is_staged_as_an_unverified_insert_draft(env: InsertEnv) -> None:
    outcome = env.put()
    assert outcome.status == "staged", outcome.refusals
    (staged,) = outcome.proposals
    assert staged.intent == "insert" and staged.target_id == CARD
    proposal = env.store.get_proposal(staged.proposal_id)
    assert proposal is not None and proposal.intent == "insert"
    assert proposal.current_row_hash is None  # nothing to bind to
    assert proposal.proposed_row["annual_fee_minor"] == 250_000
    assert proposal.proposed_row["forex_markup_bp"] == 350
    assert proposal.proposed_row["base_earn"] == {
        "points": 5,
        "per_amount_minor": 15_000,
        "currency": "INR",
    }
    # provenance is built by code, never supplied, and can never start verified
    assert proposal.proposed_row["provenance"] == {
        "source_url": "https://www.example.invalid/card",
        "source_type": "crawl_draft",
        "last_verified": "2026-11-04",
        "verified_by": "UNVERIFIED",
        "needs_verification": True,
        "confidence": 0.0,
        "notes": "draft insert from a curator-authored extraction by alice; unverified",
    }
    # evidenced facts and curator-typed values are told apart, persistently
    evidenced = {f.field_path for f in proposal.field_proposals}
    assert evidenced == {
        "annual_fee_minor",
        "forex_markup_bp",
        "base_earn.points",
        "base_earn.per_amount_minor",
    }
    unevidenced = {
        f.field_path for f in proposal.validation_findings if f.code == "unevidenced_field"
    }
    assert unevidenced == {
        "issuer",
        "network",
        "country",
        "name",
        "fee_currency",
        "forex_markup_tax_bp",
        "base_earn.currency",
    }
    assert all(f.old_value is None for f in proposal.field_proposals)


def test_the_draft_date_is_the_capture_date_so_a_later_run_is_the_same_request(
    env: InsertEnv,
) -> None:
    first = env.put()
    before = rows(env)
    later = datetime(2026, 12, 20, 8, 0, tzinfo=UTC)
    again = env.put(now=lambda: later)
    assert again.status == "staged", again.refusals
    assert again.proposals[0].state == "already_stored"
    assert again.proposals[0].proposal_id == first.proposals[0].proposal_id
    assert rows(env) == before


def test_a_different_insert_for_the_same_id_and_snapshot_is_a_conflict_not_an_overwrite(
    env: InsertEnv,
) -> None:
    first = env.put()
    stored = env.store.get_proposal(first.proposals[0].proposal_id)
    before = rows(env)
    changed = env.put(inserts=[card_insert(name="A different name")])
    assert refusal_codes(changed) == [StageRefusalCode.PROPOSAL_CONFLICT]
    assert rows(env) == before and env.store.get_proposal(first.proposals[0].proposal_id) == stored


def test_an_id_that_already_exists_is_refused_not_merged(env: InsertEnv) -> None:
    taken = {**card_insert(), "id": "hdfc-infinia"}
    refused = env.put(
        records=[{**r, "id": "hdfc-infinia"} for r in card_records()],
        inserts=[taken],
        target=env.facts("hdfc-infinia"),
    )
    assert refusal_codes(refused) == [StageRefusalCode.INSERT_ID_EXISTS]
    assert rows(env)["change_proposals"] == 0


def test_a_row_the_target_does_not_list_is_refused(env: InsertEnv) -> None:
    refused = env.put(target=env.facts("some-other-card"))
    assert StageRefusalCode.ROW_NOT_BOUND in refusal_codes(refused)
    assert rows(env)["change_proposals"] == 0


def test_a_row_that_cannot_be_completed_is_refused_never_padded(env: InsertEnv) -> None:
    """The template omits `issuer`; the tool must not invent one to satisfy the schema."""
    template = card_insert()
    del template["row"]["issuer"]
    refused = env.put(inserts=[template])
    assert refusal_codes(refused) == [StageRefusalCode.NEEDS_MORE_EVIDENCE]
    assert "issuer" in refused.refusals[0].message
    assert rows(env)["change_proposals"] == 0


def test_an_insert_with_no_quoted_evidence_at_all_needs_more_evidence(env: InsertEnv) -> None:
    other = [
        rec(
            "cards",
            "hdfc-infinia",
            "annual_fee_minor",
            "INR 2,500",
            "The annual fee is INR 2,500 per year.",
        )
    ]
    refused = env.put(
        records=other, inserts=[card_insert()], target=env.facts(CARD, "hdfc-infinia")
    )
    assert StageRefusalCode.NEEDS_MORE_EVIDENCE in refusal_codes(refused)
    assert rows(env)["change_proposals"] == 0


def test_a_template_value_that_contradicts_the_quoted_evidence_is_refused(env: InsertEnv) -> None:
    template = card_insert(annual_fee_minor=999)
    refused = env.put(inserts=[template])
    assert refusal_codes(refused) == [StageRefusalCode.TEMPLATE_CONFLICTS_WITH_EVIDENCE]


def test_the_template_may_restate_a_value_the_evidence_also_gives(env: InsertEnv) -> None:
    assert env.put(inserts=[card_insert(annual_fee_minor=250_000)]).status == "staged"


@pytest.mark.parametrize("key", ["id", "provenance"])
def test_a_template_cannot_supply_identity_or_provenance(key: str) -> None:
    with pytest.raises(ValueError, match="id or provenance"):
        CuratorExtraction.model_validate(
            {
                "schema": "tripwise.curator-extraction/v1",
                "curator_id": "alice",
                "records": card_records(),
                "inserts": [card_insert(**{key: "x"})],
            }
        )


def test_insert_declaration_mistakes_are_typed(env: InsertEnv) -> None:
    assert refusal_codes(env.put(inserts=[card_insert(), card_insert()])) == [
        StageRefusalCode.INSERT_INVALID
    ]
    odd = {**card_insert(), "table": "loyalty_programs"}
    assert StageRefusalCode.UNSUPPORTED_TABLE in refusal_codes(env.put(inserts=[odd]))


def test_a_value_the_quote_does_not_support_is_refused_for_an_insert_too(env: InsertEnv) -> None:
    bad = card_records()
    bad[0] = {**bad[0], "raw_value": "INR 2"}  # a fragment of "INR 2,500"
    refused = env.put(records=bad)
    assert refusal_codes(refused) == [StageRefusalCode.VALUE_NOT_SUPPORTED_BY_QUOTE]
    assert rows(env)["change_proposals"] == 0


def test_an_unknown_field_path_is_refused(env: InsertEnv) -> None:
    refused = env.put(records=[*card_records(), rec("cards", CARD, "no_such_bp", "2%", "3.5%")])
    assert StageRefusalCode.FIELD_PATH_INVALID in refusal_codes(refused)


def test_staging_an_insert_writes_nothing_to_the_seeds(env: InsertEnv) -> None:
    before = {p.name: p.read_bytes() for p in SEEDS_DIR.glob("*.yaml")}
    assert env.put().status == "staged"
    assert {p.name: p.read_bytes() for p in SEEDS_DIR.glob("*.yaml")} == before


# ------------------------------------------------------------------ review and decision


def test_the_decision_binds_to_the_absence_of_the_id(env: InsertEnv) -> None:
    (staged,) = env.put().proposals
    service, _ = env.runtime()
    context = service.context(staged.proposal_id)
    assert context.current_row is None
    assert context.current_row_sha256 == absent_row_hash("cards", CARD)
    assert [f.code.value for f in context.computed_findings] == ["manual_capture"]
    assert all(d.current is None for d in context.field_diffs)
    decision = approve(service, staged.proposal_id)
    assert decision.attestation is not None
    assert decision.attestation.current_row_sha256 == absent_row_hash("cards", CARD)


def test_an_id_that_appears_before_the_decision_blocks_approval_but_not_rejection(
    env: InsertEnv, tmp_path: Path
) -> None:
    (staged,) = env.put().proposals
    taken = scratch_seeds(tmp_path, taken=("cards.yaml", CARD))
    service, _ = env.runtime(taken)
    context = service.context(staged.proposal_id)
    assert [f.code.value for f in context.computed_findings if f.severity == "blocking"] == [
        "insert_id_exists"
    ]
    assert context.current_row_sha256 is None
    with pytest.raises(ReviewRefusedError, match="blocking findings"):
        approve(service, staged.proposal_id)
    rejected = service.decide(
        DecisionRequest(
            proposal_id=staged.proposal_id,
            action="reject",
            reason="id was taken",
            expected_version=1,
            client_event_id="reject-insert-event-0001",
        ),
        curator_id="alice",
    )
    assert rejected.status.value == "rejected" and rejected.attestation is None


def test_edits_are_not_supported_on_an_insert(env: InsertEnv) -> None:
    (staged,) = env.put().proposals
    service, _ = env.runtime()
    with pytest.raises(ReviewRefusedError, match="not supported on an insert"):
        service.decide(
            DecisionRequest.model_validate(
                {
                    "proposal_id": staged.proposal_id,
                    "action": "edit",
                    "reason": "x",
                    "expected_version": 1,
                    "client_event_id": "edit-insert-event-00001",
                    "curator_confidence": 0.5,
                    "edits": [
                        {
                            "field_path": "annual_fee_minor",
                            "action": "set",
                            "proposed_raw_value": "INR 2,500",
                            "quote": "The annual fee is INR 2,500 per year.",
                            "snapshot_id": env.store.get_proposal(staged.proposal_id).lineage_ids[
                                0
                            ],  # type: ignore[union-attr]
                        }
                    ],
                }
            ),
            curator_id="alice",
        )


# ------------------------------------------------------------------ bundle and dry-run


def _bundle(
    env: InsertEnv,
    ids: list[str],
    seeds: Path | None = None,
    event: str = "bundle-insert-event-0001",
) -> tuple[Any, Any, Any]:
    service, planner = env.runtime(seeds)
    record, bundle = planner.build(
        proposal_ids=tuple(ids), curator_id="alice", client_event_id=event
    )
    return service, planner, (record, bundle)


def test_an_approved_insert_dry_runs_as_would_insert_and_the_kb_still_constructs(
    env: InsertEnv,
) -> None:
    (staged,) = env.put().proposals
    service, _ = env.runtime()
    approve(service, staged.proposal_id)
    before = {p.name: p.read_bytes() for p in SEEDS_DIR.glob("*.yaml")}
    _, planner, (record, bundle) = _bundle(env, [staged.proposal_id])
    (entry,) = bundle.entries
    assert entry.operation == "insert" and entry.base_row_sha256 == absent_row_hash("cards", CARD)
    assert entry.blocked_by == ("D1", "D2") and bundle.activation_authorized is False
    assert entry.new_row["provenance"]["source_type"] == "crawl_draft"
    assert entry.new_row["provenance"]["needs_verification"] is True
    assert set(entry.evidenced_fields) == {
        "annual_fee_minor",
        "forex_markup_bp",
        "base_earn.points",
        "base_earn.per_amount_minor",
    }
    assert (
        "issuer" in entry.unevidenced_fields and "annual_fee_minor" not in entry.unevidenced_fields
    )
    report = planner.dry_run(record.bundle_sha256)
    assert [(e.target_id, e.status) for e in report.entries] == [(CARD, "would_insert")]
    assert report.kb_constructs and report.dry_run_consistent and report.seed_files_unchanged
    assert report.activation_authorized is False and report.reference_errors == ()
    assert {p.name: p.read_bytes() for p in SEEDS_DIR.glob("*.yaml")} == before


def test_an_update_bundle_entry_is_serialized_exactly_as_before_inserts_existed(
    env: InsertEnv,
) -> None:
    from ingestion.activation import canonical_bundle_bytes

    (staged,) = env.put().proposals
    service, _ = env.runtime()
    approve(service, staged.proposal_id)
    _, _, (_, bundle) = _bundle(env, [staged.proposal_id])
    assert json.loads(canonical_bundle_bytes(bundle))["entries"][0]["operation"] == "insert"
    update = bundle.entries[0].model_copy(update={"operation": "update"})
    assert "operation" not in json.loads(update.model_dump_json())


def test_an_id_that_appears_before_the_dry_run_is_an_id_conflict(
    env: InsertEnv, tmp_path: Path
) -> None:
    (staged,) = env.put().proposals
    service, _ = env.runtime()
    approve(service, staged.proposal_id)
    _, planner, (record, _) = _bundle(env, [staged.proposal_id])
    taken = scratch_seeds(tmp_path, taken=("cards.yaml", CARD))
    _, taken_planner = env.runtime(taken)
    report = taken_planner.dry_run(record.bundle_sha256)
    assert [(e.target_id, e.status) for e in report.entries] == [(CARD, "id_conflict")]
    assert not report.dry_run_consistent and not report.kb_constructs
    assert planner.dry_run(record.bundle_sha256).dry_run_consistent  # still fine on the old seeds


def test_building_a_bundle_after_the_id_appears_refuses_the_entry(
    env: InsertEnv, tmp_path: Path
) -> None:
    (staged,) = env.put().proposals
    service, _ = env.runtime()
    approve(service, staged.proposal_id)
    taken = scratch_seeds(tmp_path, taken=("cards.yaml", CARD))
    _, _, (_, bundle) = _bundle(env, [staged.proposal_id], seeds=taken)
    assert bundle.entries == () and not bundle.dry_run_consistent
    assert "now exists" in bundle.refused[0].message


def test_a_dependent_rule_must_be_bundled_with_its_card(env: InsertEnv) -> None:
    """Two individually valid inserts: the rule is only consistent if its card is in the bundle."""
    target = env.facts(CARD, f"reward_rules:{RULE}")
    card = env.put(target=target).proposals[0]
    rule = env.put(records=rule_records(), inserts=[rule_insert()], target=target).proposals[0]
    assert card.target_id == CARD and rule.target_id == RULE
    service, _ = env.runtime()
    approve(service, card.proposal_id, event="approve-card-event-000001")
    approve(service, rule.proposal_id, event="approve-rule-event-000001")

    alone = _bundle(env, [rule.proposal_id], event="bundle-rule-alone-00001")
    report_alone = alone[1].dry_run(alone[2][0].bundle_sha256)
    assert report_alone.reference_errors == (f"unknown card reference: {CARD}",)
    assert not report_alone.kb_constructs and not report_alone.dry_run_consistent

    together = _bundle(env, [card.proposal_id, rule.proposal_id], event="bundle-both-event-0001")
    report = together[1].dry_run(together[2][0].bundle_sha256)
    assert sorted((e.target_id, e.status) for e in report.entries) == sorted(
        [(CARD, "would_insert"), (RULE, "would_insert")]
    )
    assert report.reference_errors == () and report.kb_constructs and report.dry_run_consistent


def test_replaying_the_same_bundle_request_returns_the_original(env: InsertEnv) -> None:
    (staged,) = env.put().proposals
    service, _ = env.runtime()
    approve(service, staged.proposal_id)
    _, _, (first, _) = _bundle(env, [staged.proposal_id])
    _, planner = env.runtime()
    again, _ = planner.build(
        proposal_ids=(staged.proposal_id,),
        curator_id="alice",
        client_event_id="bundle-insert-event-0001",
    )
    assert again == first


# ------------------------------------------------------------------ durability and concurrency


def test_an_insert_decision_and_bundle_survive_reopening_the_database(env: InsertEnv) -> None:
    (staged,) = env.put().proposals
    service, _ = env.runtime()
    approve(service, staged.proposal_id)
    _, _, (record, _) = _bundle(env, [staged.proposal_id])
    reopened = FinancialIngestionStore(env.root / "ingestion.sqlite", now=lambda: NOW)
    proposal = reopened.get_proposal(staged.proposal_id)
    assert (
        proposal is not None and proposal.intent == "insert" and proposal.status.value == "approved"
    )
    assert reopened.get_activation_bundle(record.bundle_sha256) is not None


# ------------------------------------------------------------------ the review web page

PORT = 8765
ORIGIN = f"http://127.0.0.1:{PORT}"


def moving_clock() -> Any:
    """Each call is later than the last, as a real clock is (a frozen one hides races)."""
    lock = threading.Lock()
    state = {"n": 0}

    def tick() -> datetime:
        with lock:
            state["n"] += 1
            return NOW + timedelta(microseconds=state["n"])

    return tick


def test_the_review_page_marks_an_insert_and_offers_no_edit_form(env: InsertEnv) -> None:
    (staged,) = env.put().proposals
    service, planner = env.runtime()
    sessions = SessionRegistry(now=lambda: NOW)
    app = create_review_app(
        service=service, planner=planner, sessions=sessions, config=ReviewAppConfig(port=PORT)
    )
    client = TestClient(app, base_url=ORIGIN, follow_redirects=False)
    token = sessions.issue_login_token("alice")
    login = client.post("/review/login", data={"token": token}, headers={"origin": ORIGIN})
    assert login.status_code == 303
    page = client.get("/review/proposal", params={"id": staged.proposal_id})
    assert page.status_code == 200
    assert "Insert: a new cards row" in page.text and CARD in page.text
    assert "edit_field_path" not in page.text  # edits are not offered on an insert
    assert re.search(r"name='action' value='approve'", page.text)


def test_two_approved_inserts_for_one_id_are_refused_together(env: InsertEnv) -> None:
    """Two independent captures (separate watch targets) each approved for the same new id."""
    first = env.put().proposals[0]
    env.capture.write_text(INSERT_PAGE.replace("(not issuer content)", "(second capture)"))
    second = env.put(
        target=env.target(target_id="synth-card-b", target_fact_ids=(CARD,))
    ).proposals[0]
    assert first.proposal_id != second.proposal_id
    service, _ = env.runtime()
    approve(service, first.proposal_id, event="approve-first-event-0001")
    approve(service, second.proposal_id, event="approve-second-event-001")
    _, _, (_, bundle) = _bundle(env, [first.proposal_id, second.proposal_id])
    assert bundle.entries == ()
    assert {r.code for r in bundle.refused} == {"conflicting_entries"}


def test_a_changed_capture_supersedes_an_insert_so_the_old_one_cannot_be_approved(
    env: InsertEnv,
) -> None:
    first = env.put().proposals[0]
    env.capture.write_text(INSERT_PAGE.replace("(not issuer content)", "(newer capture)"))
    assert env.put().status == "staged"
    service, _ = env.runtime()
    with pytest.raises(ReviewRefusedError, match="blocking findings"):
        approve(service, first.proposal_id)


# ------------------------------------------------------------------ concurrency


def _race(
    root: Path, calls: list[dict[str, Any]]
) -> tuple[InsertEnv, list[StageOutcome], list[BaseException]]:
    """Run staging calls at the same instant, each with its own store handle (like a process)."""
    shared = InsertEnv(root)
    barrier = threading.Barrier(len(calls))
    clock = moving_clock()
    lock = threading.Lock()
    results: list[StageOutcome] = []
    errors: list[BaseException] = []

    def writer(kwargs: dict[str, Any]) -> None:
        local = InsertEnv.__new__(InsertEnv)
        local.root, local.artifacts = shared.root, shared.artifacts
        local.capture, local.seeds = shared.capture, shared.seeds
        local.store = FinancialIngestionStore(shared.root / "ingestion.sqlite", now=clock)
        barrier.wait()
        try:
            outcome = local.put(now=clock, **kwargs)
            with lock:
                results.append(outcome)
        except BaseException as error:  # noqa: BLE001 - the test reports whatever escaped
            with lock:
                errors.append(error)

    threads = [threading.Thread(target=writer, args=(kwargs,)) for kwargs in calls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return shared, results, errors


def test_concurrent_identical_inserts_store_exactly_one_proposal(tmp_path: Path) -> None:
    """Real clocks differ between runs, so payloads differ by created_at: still one request."""
    for trial in range(10):
        shared, results, errors = _race(tmp_path / f"same{trial}", [{}, {}, {}, {}])
        assert errors == [], f"trial {trial}: {errors}"
        assert [r.status for r in results] == ["staged"] * 4, [r.refusals for r in results]
        assert len(shared.store.list_proposals()) == 1
        assert len({r.proposals[0].proposal_id for r in results}) == 1
        # (each may report "stored": a simultaneous loser cannot tell it lost; one row exists)
        assert any(r.proposals[0].state == "stored" for r in results)


def test_concurrent_different_inserts_for_one_id_never_overwrite_each_other(tmp_path: Path) -> None:
    for trial in range(10):
        calls = [{"inserts": [card_insert(name=name)]} for name in ("Name One", "Name Two")]
        shared, results, errors = _race(tmp_path / f"diff{trial}", calls)
        assert errors == [], f"trial {trial}: {errors}"
        assert sorted(r.status for r in results) == ["refused", "staged"]
        (kept,) = shared.store.list_proposals()
        winner = next(r for r in results if r.status == "staged")
        assert kept.proposal_id == winner.proposals[0].proposal_id
        loser = next(r for r in results if r.status == "refused")
        assert refusal_codes(loser) == [StageRefusalCode.PROPOSAL_CONFLICT]


def test_a_point_valuation_insert_is_parsed_in_micro_major_units_and_bundled_with_its_card(
    env: InsertEnv,
) -> None:
    """All three kinds: card, rule and valuation, the last evidenced as a per-point rate."""
    valuation = {
        "table": "point_valuations",
        "id": VALUATION,
        "row": {"card_id": CARD, "path": "cashback", "currency": "INR"},
    }
    target = env.facts(CARD, f"point_valuations:{VALUATION}")
    card = env.put(target=target).proposals[0]
    outcome = env.put(
        records=[
            rec("point_valuations", VALUATION, "value_micro_major_per_point", "INR 0.40", VALUE)
        ],
        inserts=[valuation],
        target=target,
    )
    assert outcome.status == "staged", outcome.refusals
    proposal = env.store.get_proposal(outcome.proposals[0].proposal_id)
    assert proposal is not None
    assert (
        proposal.proposed_row["value_micro_major_per_point"] == 400_000
    )  # INR 0.40, integer micro
    service, _ = env.runtime()
    approve(service, card.proposal_id, event="approve-card-val-event-01")
    approve(service, outcome.proposals[0].proposal_id, event="approve-val-event-000001")
    _, planner, (record, _) = _bundle(
        env, [card.proposal_id, outcome.proposals[0].proposal_id], event="bundle-val-event-000001"
    )
    report = planner.dry_run(record.bundle_sha256)
    assert sorted(e.status for e in report.entries) == ["would_insert", "would_insert"]
    assert report.kb_constructs and report.dry_run_consistent
