"""The stage-capture operator workflow through the real CLI, one process per step.

stage capture -> inspect -> approve -> reopen -> bundle -> dry-run, with real SQLite files
carrying state between processes. Inputs are synthetic (``example.invalid``); the seeds are
the repository's and must come out byte-identical.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from core.db import SEEDS_DIR

BACKEND = Path(__file__).resolve().parents[1]
POLICY = """\
- policy_id: synth-issuer
  name: SYNTHETIC issuer (fixture)
  owner: fixture
  domain: example.invalid
  source_url: https://www.example.invalid/card
  terms_url: https://www.example.invalid/terms
  terms_read_on: 2026-11-01
  automated_access_permitted: false
  manual_only: true
  allowed_page_classes: [card_page, tnc_pdf]
  reviewed_on: 2026-11-01
  reviewed_by: alice
"""
TARGET = """\
- target_id: synth-card
  url: https://www.example.invalid/card
  kind: manual_capture
  target: [hdfc-infinia]
  source_policy_id: synth-issuer
  check_frequency_days: 365
  backend: manual
  manual_only: true
"""
PAGE = (
    "<html><body><main><p>SYNTHETIC FIXTURE.</p><p>The annual fee is INR 15,000 per year.</p>"
    "<p>Foreign currency markup is 3.5% on every international transaction.</p>"
    "</main></body></html>"
)
FEE = "The annual fee is INR 15,000 per year."
FX = "Foreign currency markup is 3.5% on every international transaction."


def extraction(*records: str, curator: str = "alice") -> str:
    body = "\n".join(f"  - {record}" for record in records)
    return f"schema: tripwise.curator-extraction/v1\ncurator_id: {curator}\nrecords:\n{body}\n"


def rec(field: str, raw: str, quote: str, extra: str = "") -> str:
    return (
        f'{{table: cards, id: hdfc-infinia, field_path: {field}, raw_value: "{raw}", '
        f'quote: "{quote}"{extra}}}'
    )


def cli(args: list[str], **env: str) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if k not in {"TRIPWISE_ENV", "TRIPWISE_DATA_DIR"}}
    return subprocess.run(
        [sys.executable, "-m", "ingestion.review_server", *args],
        cwd=BACKEND,
        env={**clean, **env},
        capture_output=True,
        text=True,
        timeout=180,
    )


def seed_hashes() -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in SEEDS_DIR.glob("*.yaml")}


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.data = root / "data"
        self.inputs = root / "in"
        self.inputs.mkdir()
        (self.inputs / "policy.yaml").write_text(POLICY)
        (self.inputs / "target.yaml").write_text(TARGET)
        (self.inputs / "capture.html").write_text(PAGE)

    def write(self, name: str, text: str) -> Path:
        path = self.inputs / name
        path.write_text(text)
        return path

    def stage(
        self,
        extraction_name: str,
        *,
        capture: str = "capture.html",
        doc: str = "card_page",
        target: str = "target.yaml",
        extra: list[str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return cli(
            [
                "stage-capture",
                "--data-dir",
                str(self.data),
                "--capture",
                str(self.inputs / capture),
                "--source-policy",
                str(self.inputs / "policy.yaml"),
                "--watch-target",
                str(self.inputs / target),
                "--extraction",
                str(self.inputs / extraction_name),
                "--document-class",
                doc,
                *(extra or []),
            ]
        )

    def register(self) -> None:
        done = cli(
            [
                "add-curator",
                "--data-dir",
                str(self.data),
                "--curator-id",
                "alice",
                "--display-name",
                "Alice",
            ]
        )
        assert done.returncode == 0, done.stderr


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    workspace = Workspace(tmp_path)
    workspace.register()
    return workspace


def js(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return json.loads(result.stdout)  # type: ignore[no-any-return]


def test_stage_inspect_approve_reopen_bundle_and_dry_run_across_processes(ws: Workspace) -> None:
    before = seed_hashes()
    ws.write(
        "ex.yaml",
        extraction(rec("annual_fee_minor", "INR 15,000", FEE), rec("forex_markup_bp", "3.5%", FX)),
    )
    staged = ws.stage("ex.yaml")
    assert staged.returncode == 0, staged.stderr
    out = js(staged)
    assert out["status"] == "staged" and out["extraction"] == "curator-authored"
    assert out["llm_calls"] == 0 and out["network_calls"] == 0
    proposal_id = out["proposals"][0]["proposal_id"]
    data = ["--data-dir", str(ws.data)]

    # a second, separate process: identical input changes nothing
    again = js(ws.stage("ex.yaml"))
    assert again["proposals"][0]["state"] == "already_stored" and again["snapshot_state"] == (
        "already_stored"
    )

    inspected = js(cli(["inspect", *data, "--proposal-id", proposal_id]))
    changed = {
        d["field_path"]: (d["current"], d["proposed"])
        for d in inspected["field_diffs"]
        if d["changed"]
    }
    assert changed == {"annual_fee_minor": (1250000, 1500000), "forex_markup_bp": (200, 350)}
    assert all(e["verified"] for e in inspected["evidence"])
    assert [f["code"] for f in inspected["findings"]] == ["manual_capture"]

    approved = cli(
        [
            "decision",
            *data,
            "--proposal-id",
            proposal_id,
            "--curator-id",
            "alice",
            "--action",
            "approve",
            "--reason",
            "SYNTHETIC fixture reviewed",
            "--expected-version",
            "1",
            "--client-event-id",
            "approve-card-bank-0001",
            "--curator-confidence",
            "0.9",
        ]
    )
    assert approved.returncode == 0, approved.stderr
    reopened = js(cli(["reopen", *data, "--proposal-id", proposal_id]))
    assert reopened["proposal"]["status"] == "approved" and len(reopened["decisions"]) == 1

    # re-staging after approval returns the stored, now-approved proposal; it never reopens it
    replay = js(ws.stage("ex.yaml"))
    assert replay["proposals"][0]["review_status"] == "approved"

    bundle = js(
        cli(
            [
                "bundle",
                *data,
                "--curator-id",
                "alice",
                "--client-event-id",
                "bundle-card-bank-0001",
                "--proposal-id",
                proposal_id,
            ]
        )
    )
    assert bundle["bundle"]["activation_authorized"] is False
    assert bundle["bundle"]["unresolved_decisions"] == ["D1", "D2"]
    (entry,) = bundle["bundle"]["entries"]
    assert entry["evidenced_fields"] == ["annual_fee_minor", "forex_markup_bp"]
    assert entry["blocked_by"] == ["D1", "D2"]

    dry = js(cli(["dry-run", *data, "--bundle-sha256", bundle["record"]["bundle_sha256"]]))
    assert dry["dry_run_consistent"] is True and dry["kb_constructs"] is True
    assert dry["seed_files_unchanged"] is True and dry["activation_authorized"] is False
    assert [(e["status"], len(e["field_changes"])) for e in dry["entries"]] == [("would_update", 2)]
    assert seed_hashes() == before


def test_a_refusal_prints_typed_json_and_one_line_and_stores_no_proposal(ws: Workspace) -> None:
    ws.write(
        "bad.yaml",
        extraction(
            rec("annual_fee_minor", "INR 15,000", "The annual fee is INR 16,000 per year."),
            rec("forex_markup_bp", "3,5%", FX),
        ),
    )
    result = ws.stage("bad.yaml")
    assert result.returncode == 2
    out = js(result)
    assert out["status"] == "refused" and out["proposals"] == []
    assert [r["code"] for r in out["refusals"]] == ["quote_not_found", "value_unresolved"]
    assert result.stderr.startswith("refused: quote_not_found") and "(+1 more)" in result.stderr
    assert "Traceback" not in result.stderr
    listing = cli(["inspect", "--data-dir", str(ws.data), "--proposal-id", "proposal:none"])
    assert listing.returncode != 0  # nothing was stored under any proposal id


def test_a_malformed_input_file_is_a_typed_config_refusal(ws: Workspace) -> None:
    ws.write(
        "typo.yaml", "schema: tripwise.curator-extraction/v1\ncurator_id: alice\nrecordz: []\n"
    )
    result = ws.stage("typo.yaml")
    assert result.returncode == 2 and "Traceback" not in result.stderr
    out = js(result)
    assert out["kind"] == "config" and out["status"] == "refused"
    assert {i["code"] for i in out["issues"]} == {"config_invalid_entry"}
    assert all(i["file"].endswith("typo.yaml") for i in out["issues"])


def test_an_aggregator_page_is_refused_at_the_watch_target(ws: Workspace) -> None:
    ws.write(
        "agg_target.yaml",
        TARGET.replace("https://www.example.invalid/card", "https://www.cardexpert.in/some-card"),
    )
    ws.write("ex.yaml", extraction(rec("annual_fee_minor", "INR 15,000", FEE)))
    out = js(ws.stage("ex.yaml", target="agg_target.yaml"))
    assert out["kind"] == "config"
    assert "aggregator_domain" in {i["code"] for i in out["issues"]}


def test_a_multi_entry_file_needs_an_explicit_selection(ws: Workspace) -> None:
    ws.write("two.yaml", TARGET + TARGET.replace("synth-card", "synth-card-2"))
    ws.write("ex.yaml", extraction(rec("annual_fee_minor", "INR 15,000", FEE)))
    ambiguous = js(ws.stage("ex.yaml", target="two.yaml"))
    assert [i["code"] for i in ambiguous["issues"]] == ["config_ambiguous_selection"]
    chosen = ws.stage("ex.yaml", target="two.yaml", extra=["--target-id", "synth-card-2"])
    assert chosen.returncode == 0, chosen.stderr


def test_check_config_validates_files_without_a_data_directory_or_network(
    tmp_path: Path,
) -> None:
    (tmp_path / "p.yaml").write_text(POLICY)
    (tmp_path / "w.yaml").write_text(TARGET)
    (tmp_path / "d.yaml").write_text(
        "- {name: SyntheticLead, url: 'https://www.cardexpert.in/', corridor: IN,"
        " tos_url: 'https://www.cardexpert.in/terms-of-use/', tos_read_on: 2026-11-01,"
        " automated_access_permitted: false, manual_only: true}\n"
    )
    ok = cli(
        [
            "check-config",
            "--source-policies",
            str(tmp_path / "p.yaml"),
            "--watchlist",
            str(tmp_path / "w.yaml"),
            "--discovery-sources",
            str(tmp_path / "d.yaml"),
        ]
    )
    assert ok.returncode == 0, ok.stderr
    out = js(ok)
    assert out["network_calls"] == 0 and out["discovery_sources"][0]["access"] == "manual_only"
    (tmp_path / "w.yaml").write_text(TARGET.replace("synth-issuer", "missing-policy"))
    bad = cli(
        [
            "check-config",
            "--source-policies",
            str(tmp_path / "p.yaml"),
            "--watchlist",
            str(tmp_path / "w.yaml"),
        ]
    )
    assert bad.returncode == 2 and "config_policy_missing" in bad.stdout


def test_the_production_guard_still_covers_the_new_commands(ws: Workspace) -> None:
    ws.write("ex.yaml", extraction(rec("annual_fee_minor", "INR 15,000", FEE)))
    guarded = cli(
        [
            "stage-capture",
            "--data-dir",
            str(ws.root / "other"),
            "--capture",
            "x",
            "--source-policy",
            "x",
            "--watch-target",
            "x",
            "--extraction",
            "x",
            "--document-class",
            "card_page",
        ],
        TRIPWISE_ENV="production",
    )
    assert guarded.returncode == 2 and "disabled in production" in guarded.stderr
    assert not (ws.root / "other").exists()


def test_a_malformed_decision_argument_is_a_one_line_refusal_not_a_traceback(
    ws: Workspace,
) -> None:
    result = cli(
        [
            "decision",
            "--data-dir",
            str(ws.data),
            "--proposal-id",
            "p",
            "--curator-id",
            "alice",
            "--action",
            "approve",
            "--reason",
            "x",
            "--expected-version",
            "1",
            "--client-event-id",
            "short",
        ]
    )
    assert result.returncode == 2 and "Traceback" not in result.stderr
    assert result.stderr.startswith("refused: invalid input: client_event_id")


# ------------------------------------------------------------------ real pdfplumber

_REAL_PDF = importlib.util.find_spec("pdfplumber") is not None
needs_pdfplumber = pytest.mark.skipif(
    not _REAL_PDF,
    reason=(
        "real pdfplumber is not installed in this interpreter; run this module with an "
        "environment that has the declared optional dependency (pdfplumber>=0.11,<1)"
    ),
)


@needs_pdfplumber
def test_a_pdf_capture_is_staged_with_page_cited_evidence_using_the_real_parser(
    ws: Workspace,
) -> None:
    from evals.test_pdf_real_library_compatibility import build_pdf

    pages = [["SYNTHETIC MITC page one", FX], ["SYNTHETIC MITC page two", FX, FEE]]
    (ws.inputs / "mitc.pdf").write_bytes(build_pdf(pages))
    ws.write("pdf_target.yaml", TARGET.replace("synth-card", "synth-mitc"))
    pdf = {"doc": "tnc_pdf", "capture": "mitc.pdf", "target": "pdf_target.yaml"}

    ws.write("no_page.yaml", extraction(rec("forex_markup_bp", "3.5%", FX)))
    assert [r["code"] for r in js(ws.stage("no_page.yaml", **pdf))["refusals"]] == ["page_required"]

    ws.write("ambiguous.yaml", extraction(rec("forex_markup_bp", "3.5%", FX, ", page: 2")))
    ambiguous = js(ws.stage("ambiguous.yaml", **pdf))
    assert [r["code"] for r in ambiguous["refusals"]] == ["quote_ambiguous"]
    # each candidate says which page it is on, so the right occurrence is easy to choose
    assert "(page 1)" in ambiguous["refusals"][0]["message"]
    assert "(page 2)" in ambiguous["refusals"][0]["message"]

    ws.write("wrong_page.yaml", extraction(rec("annual_fee_minor", "INR 15,000", FEE, ", page: 1")))
    wrong = js(ws.stage("wrong_page.yaml", **pdf))
    assert [r["code"] for r in wrong["refusals"]] == ["page_offset_mismatch"]
    assert "on page 2, not page 1" in wrong["refusals"][0]["message"]

    # the quote is on both pages: occurrence 1 is on page 1, so citing page 2 must be refused
    # (the offset would highlight page 1's text under a page-2 label)
    ws.write(
        "disagree.yaml", extraction(rec("forex_markup_bp", "3.5%", FX, ", occurrence: 1, page: 2"))
    )
    disagree = js(ws.stage("disagree.yaml", **pdf))
    assert [r["code"] for r in disagree["refusals"]] == ["page_offset_mismatch"]
    assert disagree["proposals"] == []

    ws.write(
        "ok.yaml",
        extraction(
            rec("forex_markup_bp", "3.5%", FX, ", occurrence: 2, page: 2"),
            rec("annual_fee_minor", "INR 15,000", FEE, ", page: 2"),
        ),
    )
    staged = ws.stage("ok.yaml", **pdf)
    assert staged.returncode == 0, staged.stderr
    out = js(staged)
    assert out["artifact_kind"] == "pdf" and out["proposals"][0]["state"] == "stored"
    inspected = js(
        cli(
            [
                "inspect",
                "--data-dir",
                str(ws.data),
                "--proposal-id",
                out["proposals"][0]["proposal_id"],
            ]
        )
    )
    pages_cited = {e["span"]["page_number"] for e in inspected["evidence"]}
    assert pages_cited == {2} and all(e["verified"] for e in inspected["evidence"])
    # a PDF can not be declared a card page
    mismatch = js(ws.stage("ok.yaml", **{**pdf, "doc": "card_page"}))
    assert [r["code"] for r in mismatch["refusals"]] == ["document_class_mismatch"]


def test_a_bad_edits_argument_is_a_one_line_refusal(ws: Workspace) -> None:
    result = cli(
        [
            "decision", "--data-dir", str(ws.data), "--proposal-id", "p",
            "--curator-id", "alice", "--action", "edit", "--reason", "x",
            "--expected-version", "1", "--client-event-id", "edit-card-bank-00001",
            "--edits-json", "not json",
        ]
    )  # fmt: skip
    assert result.returncode == 2 and "Traceback" not in result.stderr
    assert result.stderr.startswith("refused: invalid input:")


def test_a_validation_error_from_inside_the_tool_is_not_dressed_up_as_bad_input(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the operator's own arguments are reported as invalid input; a validation error
    raised from deeper in the code is a bug and must keep its traceback."""
    from pydantic import BaseModel, ValidationError

    from ingestion import review_server
    from ingestion.review import ReviewService

    class Probe(BaseModel):
        n: int

    def broken(*_: Any, **__: Any) -> None:
        Probe(n="not an int")  # type: ignore[arg-type]

    monkeypatch.setattr(ReviewService, "decide", broken)
    with pytest.raises(ValidationError):
        review_server.main(
            [
                "decision", "--data-dir", str(ws.data), "--proposal-id", "p",
                "--curator-id", "alice", "--action", "approve", "--reason", "x",
                "--expected-version", "1", "--client-event-id", "approve-card-bank-0009",
                "--curator-confidence", "0.9",
            ],
            env={},
        )  # fmt: skip
