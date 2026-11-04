"""Milestone B acceptance: discovery lead to a ``would_insert`` dry-run through the real CLI.

Synthetic lead -> issuer target -> local synthetic capture -> insert proposal -> curator review
-> bundle -> dry-run, one process per step with real SQLite files between them, and the id
collision shown at each point it can appear. Every document is synthetic (``example.invalid``).
"""

from __future__ import annotations

import copy
import hashlib
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.db import SEEDS_DIR
from evals.test_card_bank_cli import POLICY, cli, js
from evals.test_card_bank_inserts import INSERT_PAGE

SOURCES = """\
- name: SyntheticLeads
  url: https://leads.example.invalid/
  corridor: IN
  tos_url: https://leads.example.invalid/terms
  tos_read_on: 2026-11-01
  automated_access_permitted: false
  manual_only: true
"""
LEAD = """\
id: lead-voyager
found_at: 2026-11-04
hint_url: https://leads.example.invalid/cards/voyager
hint_source: SyntheticLeads
corridor: IN
kind: card
issuer_guess: Synthetic Bank
product_guess: Example Voyager
claim_summary: Example Voyager card by Synthetic Bank
issuer_url_to_verify: https://www.example.invalid/synthetic/voyager
status: pending
"""
FEE = "The annual fee is INR 2,500 per year."
FX = "Foreign currency markup is 3.5% on every international transaction."
EARN = "Earn 5 reward points for every INR 150 spent."


def _record(path: str, raw: str, quote: str) -> dict[str, str]:
    return {
        "table": "cards",
        "id": "synthetic-voyager",
        "field_path": path,
        "raw_value": raw,
        "quote": quote,
    }


EXTRACTION = yaml.safe_dump(
    {
        "schema": "tripwise.curator-extraction/v1",
        "curator_id": "alice",
        "change_summary": "SYNTHETIC insert through the CLI",
        "inserts": [
            {
                "table": "cards",
                "id": "synthetic-voyager",
                "row": {
                    "issuer": "Synthetic Bank",
                    "network": "visa",
                    "country": "IN",
                    "name": "Example Voyager",
                    "fee_currency": "INR",
                    "forex_markup_tax_bp": 1800,
                    "base_earn": {"currency": "INR"},
                },
            }
        ],
        "records": [
            _record("annual_fee_minor", "INR 2,500", FEE),
            _record("forex_markup_bp", "3.5%", FX),
            _record("base_earn.points", "5", EARN),
            _record("base_earn.per_amount_minor", "INR 150", EARN),
        ],
    },
    sort_keys=False,
)


def seed_hashes() -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in SEEDS_DIR.glob("*.yaml")}


class Pipeline:
    def __init__(self, root: Path) -> None:
        self.root, self.data, self.inputs = root, root / "data", root / "in"
        self.inputs.mkdir()
        for name, text in {
            "discovery_sources.yaml": SOURCES,
            "lead.yaml": LEAD,
            "policy.yaml": POLICY,
            "extraction.yaml": EXTRACTION,
            "capture.html": INSERT_PAGE,
        }.items():
            (self.inputs / name).write_text(text)
        self.dd = ["--data-dir", str(self.data)]
        assert (
            cli(
                ["add-curator", *self.dd, "--curator-id", "alice", "--display-name", "Alice"]
            ).returncode
            == 0
        )

    def file_lead(self, lead: str = "lead.yaml") -> Any:
        return cli(
            [
                "add-lead",
                *self.dd,
                "--lead",
                str(self.inputs / lead),
                "--discovery-sources",
                str(self.inputs / "discovery_sources.yaml"),
            ]
        )

    def promote(self, row_id: str = "synthetic-voyager") -> Any:
        return cli(
            [
                "promote-lead",
                *self.dd,
                "--lead-id",
                "lead-voyager",
                "--curator-id",
                "alice",
                "--source-policy",
                str(self.inputs / "policy.yaml"),
                "--discovery-sources",
                str(self.inputs / "discovery_sources.yaml"),
                "--row-id",
                row_id,
                "--out",
                str(self.inputs / "target.yaml"),
            ]
        )

    def stage(self, *extra: str) -> Any:
        return cli(
            [
                "stage-capture",
                *self.dd,
                "--capture",
                str(self.inputs / "capture.html"),
                "--source-policy",
                str(self.inputs / "policy.yaml"),
                "--watch-target",
                str(self.inputs / "target.yaml"),
                "--extraction",
                str(self.inputs / "extraction.yaml"),
                "--document-class",
                "card_page",
                *extra,
            ]
        )


@pytest.fixture
def pipeline(tmp_path: Path) -> Pipeline:
    return Pipeline(tmp_path)


def taken_seeds(root: Path, row_id: str) -> Path:
    seeds = root / "seeds_taken"
    shutil.copytree(SEEDS_DIR, seeds)
    rows = yaml.safe_load((seeds / "cards.yaml").read_text())
    row = copy.deepcopy(rows[0])
    row["id"] = row_id
    rows.append(row)
    (seeds / "cards.yaml").write_text(yaml.safe_dump(rows, sort_keys=False))
    return seeds


def test_lead_to_would_insert_across_processes_with_the_id_collision(pipeline: Pipeline) -> None:
    before = seed_hashes()
    filed = js(pipeline.file_lead())
    assert filed["status"] == "filed" and filed["facts_carried"] == 0
    assert js(pipeline.file_lead())["state"] == "already_stored"

    promoted = pipeline.promote()
    assert promoted.returncode == 0, promoted.stderr
    summary = js(promoted)
    assert summary["issuer_url"] == "https://www.example.invalid/synthetic/voyager"
    assert summary["aggregator_url_carried"] is False
    assert summary["target_fact_ids"] == ["candidate:lead-voyager", "cards:synthetic-voyager"]

    staged = pipeline.stage()
    assert staged.returncode == 0, staged.stderr
    out = js(staged)
    assert out["llm_calls"] == 0 and out["network_calls"] == 0
    (proposal,) = out["proposals"]
    assert proposal["intent"] == "insert" and proposal["state"] == "stored"
    pid = proposal["proposal_id"]
    assert js(pipeline.stage())["proposals"][0]["state"] == "already_stored"

    inspected = js(cli(["inspect", *pipeline.dd, "--proposal-id", pid]))
    assert inspected["proposal"]["intent"] == "insert" and inspected["current_row"] is None
    evidenced = {d["field_path"] for d in inspected["field_diffs"] if d["evidence"]}
    assert evidenced == {
        "annual_fee_minor",
        "forex_markup_bp",
        "base_earn.points",
        "base_earn.per_amount_minor",
    }
    assert inspected["proposal"]["proposed_row"]["provenance"]["source_type"] == "crawl_draft"

    approve = [
        "decision",
        *pipeline.dd,
        "--proposal-id",
        pid,
        "--curator-id",
        "alice",
        "--action",
        "approve",
        "--reason",
        "SYNTHETIC insert reviewed",
        "--expected-version",
        "1",
        "--client-event-id",
        "approve-insert-cli-0001",
        "--curator-confidence",
        "0.8",
    ]
    approved = cli(approve)
    assert approved.returncode == 0, approved.stderr
    reopened = js(cli(["reopen", *pipeline.dd, "--proposal-id", pid]))
    assert reopened["proposal"]["status"] == "approved" and len(reopened["decisions"]) == 1

    bundle = js(
        cli(
            [
                "bundle",
                *pipeline.dd,
                "--curator-id",
                "alice",
                "--client-event-id",
                "bundle-insert-cli-0001",
                "--proposal-id",
                pid,
            ]
        )
    )
    (entry,) = bundle["bundle"]["entries"]
    assert entry["operation"] == "insert" and entry["blocked_by"] == ["D1", "D2"]
    assert bundle["bundle"]["activation_authorized"] is False
    sha = bundle["record"]["bundle_sha256"]

    dry = js(cli(["dry-run", *pipeline.dd, "--bundle-sha256", sha]))
    assert [(e["target_id"], e["status"], len(e["field_changes"])) for e in dry["entries"]] == [
        ("synthetic-voyager", "would_insert", 20)
    ]
    assert dry["dry_run_consistent"] and dry["kb_constructs"] and dry["seed_files_unchanged"]

    # the id appears AFTER the proposal was approved and bundled: the dry-run says so
    taken = taken_seeds(pipeline.root, "synthetic-voyager")
    late = js(cli(["dry-run", *pipeline.dd, "--seeds-dir", str(taken), "--bundle-sha256", sha]))
    assert [e["status"] for e in late["entries"]] == ["id_conflict"]
    assert late["dry_run_consistent"] is False and late["kb_constructs"] is False
    assert seed_hashes() == before


def test_an_id_that_appears_before_the_decision_is_refused_in_one_line(pipeline: Pipeline) -> None:
    assert pipeline.file_lead().returncode == 0 and pipeline.promote().returncode == 0
    pid = js(pipeline.stage())["proposals"][0]["proposal_id"]
    taken = taken_seeds(pipeline.root, "synthetic-voyager")
    refused = cli(
        [
            "decision",
            *pipeline.dd,
            "--seeds-dir",
            str(taken),
            "--proposal-id",
            pid,
            "--curator-id",
            "alice",
            "--action",
            "approve",
            "--reason",
            "x",
            "--expected-version",
            "1",
            "--client-event-id",
            "approve-late-cli-00001",
            "--curator-confidence",
            "0.8",
        ]
    )
    assert refused.returncode == 2 and "Traceback" not in refused.stderr
    assert "blocking findings" in refused.stderr
    inspected = js(cli(["inspect", *pipeline.dd, "--seeds-dir", str(taken), "--proposal-id", pid]))
    assert "insert_id_exists" in {f["code"] for f in inspected["findings"]}


def test_staging_an_insert_for_an_id_that_exists_is_refused_before_anything_is_stored(
    pipeline: Pipeline,
) -> None:
    assert pipeline.file_lead().returncode == 0 and pipeline.promote().returncode == 0
    taken = taken_seeds(pipeline.root, "synthetic-voyager")
    result = pipeline.stage("--seeds-dir", str(taken))
    assert result.returncode == 2
    assert [r["code"] for r in js(result)["refusals"]] == ["insert_id_exists"]


def test_a_lead_that_carries_facts_or_an_aggregator_page_is_refused(pipeline: Pipeline) -> None:
    (pipeline.inputs / "facts.yaml").write_text(
        LEAD.replace("Example Voyager card by Synthetic Bank", "Voyager has a 2,500 annual fee")
    )
    facts = pipeline.file_lead("facts.yaml")
    assert facts.returncode == 2 and "lead_carries_facts" in facts.stdout
    (pipeline.inputs / "agg.yaml").write_text(
        LEAD.replace(
            "https://www.example.invalid/synthetic/voyager", "https://leads.example.invalid/c"
        )
    )
    agg = pipeline.file_lead("agg.yaml")
    assert agg.returncode == 2 and "aggregator_domain" in agg.stdout


def test_a_lead_for_a_card_the_kb_already_has_or_filed_twice_is_a_duplicate(
    pipeline: Pipeline,
) -> None:
    (pipeline.inputs / "kb.yaml").write_text(
        LEAD.replace("Synthetic Bank", "HDFC Bank").replace("Example Voyager", "Infinia Metal")
    )
    in_kb = pipeline.file_lead("kb.yaml")
    assert (
        in_kb.returncode == 2
        and "lead_duplicate" in in_kb.stdout
        and "hdfc-infinia" in in_kb.stdout
    )
    assert pipeline.file_lead().returncode == 0
    (pipeline.inputs / "dup.yaml").write_text(LEAD.replace("lead-voyager", "lead-again"))
    again = pipeline.file_lead("dup.yaml")
    assert again.returncode == 2 and "lead_duplicate" in again.stdout


def test_a_lead_from_an_unconfigured_source_is_refused(pipeline: Pipeline) -> None:
    (pipeline.inputs / "other.yaml").write_text(LEAD.replace("SyntheticLeads", "NobodyKnows"))
    refused = pipeline.file_lead("other.yaml")
    assert refused.returncode == 2 and "lead_unknown_source" in refused.stdout


def test_promotion_needs_a_registered_curator_and_a_new_id(pipeline: Pipeline) -> None:
    assert pipeline.file_lead().returncode == 0
    existing = pipeline.promote(row_id="hdfc-infinia")
    assert existing.returncode == 2 and "insert_id_exists" in existing.stdout
    stranger = cli(
        [
            "promote-lead",
            *pipeline.dd,
            "--lead-id",
            "lead-voyager",
            "--curator-id",
            "mallory",
            "--source-policy",
            str(pipeline.inputs / "policy.yaml"),
            "--row-id",
            "x-card",
            "--out",
            str(pipeline.inputs / "t.yaml"),
        ]
    )
    assert stranger.returncode == 2 and "unknown_curator" in stranger.stdout


def test_a_promoted_target_must_trace_to_a_lead_in_this_data_directory(
    pipeline: Pipeline, tmp_path: Path
) -> None:
    assert pipeline.file_lead().returncode == 0 and pipeline.promote().returncode == 0
    elsewhere = (
        Pipeline(tmp_path / "elsewhere") if (tmp_path / "elsewhere").mkdir() is None else None
    )
    assert elsewhere is not None
    # reuse the promoted target file in a data directory that never saw the lead
    shutil.copy(pipeline.inputs / "target.yaml", elsewhere.inputs / "target.yaml")
    result = elsewhere.stage()
    assert result.returncode == 2
    assert "target_invalid" in {r["code"] for r in js(result)["refusals"]}
