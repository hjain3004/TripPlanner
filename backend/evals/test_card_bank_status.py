"""``status``: reopen every stored proposal and say whether its approval still applies.

An operator coming back after a restart does not remember proposal ids, and an approval is only
reusable while the exact proposal, evidence and base row it attested still hold. Found with a
real pilot database: the only way to find proposals was SQL, and an unknown id printed a raw
traceback. Synthetic documents only; real CLI processes and real SQLite.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from core.db import SEEDS_DIR
from evals.test_card_bank_cli import (
    FEE,
    FX,
    Workspace,
    cli,
    extraction,
    js,
    rec,
    seed_hashes,
)


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    workspace = Workspace(tmp_path)
    workspace.register()
    workspace.write(
        "ex.yaml",
        extraction(rec("annual_fee_minor", "INR 15,000", FEE), rec("forex_markup_bp", "3.5%", FX)),
    )
    return workspace


def approve(ws: Workspace, proposal_id: str, event: str = "approve-status-0001") -> None:
    done = cli(
        [
            "decision",
            "--data-dir",
            str(ws.data),
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
            event,
            "--curator-confidence",
            "0.9",
        ]
    )
    assert done.returncode == 0, done.stderr


def status(ws: Workspace, *extra: str) -> dict[str, Any]:
    done = cli(["status", "--data-dir", str(ws.data), *extra])
    assert done.returncode == 0, done.stderr
    return js(done)


def test_status_lists_a_pending_proposal_with_its_capture_and_no_approval(ws: Workspace) -> None:
    staged = js(ws.stage("ex.yaml", extra=["--captured-at", "2026-10-31T05:40:00+00:00"]))
    report = status(ws)
    (item,) = report["proposals"]
    assert item["proposal_id"] == staged["proposals"][0]["proposal_id"]
    assert (item["target_table"], item["target_id"]) == ("cards", "hdfc-infinia")
    assert item["review_status"] == "pending" and item["decisions"] == []
    assert item["approval_applies"] is False and "no approved decision" in item["approval_note"]
    assert item["field_paths"] == ["annual_fee_minor", "forex_markup_bp"]
    assert item["snapshot_captured_at"] == "2026-10-31T05:40:00Z"
    assert item["page_kind"] == "manual_capture" and item["source_policy_id"] == "synth-issuer"
    assert item["extractor_version"] == "curator-authored-v1"


def test_status_shows_an_approval_that_still_applies_after_a_fresh_process(ws: Workspace) -> None:
    before = seed_hashes()
    proposal_id = js(ws.stage("ex.yaml"))["proposals"][0]["proposal_id"]
    approve(ws, proposal_id)
    (item,) = status(ws)["proposals"]
    assert item["review_status"] == "approved"
    (decision,) = item["decisions"]
    assert decision["reviewer_id"] == "alice" and decision["status"] == "approved"
    assert decision["client_event_id"] == "approve-status-0001"
    assert item["approval_applies"] is True and item["approval_note"] is None
    assert seed_hashes() == before


def test_an_approval_stops_applying_when_the_base_row_changed(
    ws: Workspace, tmp_path: Path
) -> None:
    proposal_id = js(ws.stage("ex.yaml"))["proposals"][0]["proposal_id"]
    approve(ws, proposal_id)
    scratch = tmp_path / "other-seeds"
    shutil.copytree(SEEDS_DIR, scratch)
    cards = scratch / "cards.yaml"
    text = cards.read_text(encoding="utf-8")
    start = text.index("id: hdfc-infinia")
    changed = text[start:].replace("annual_fee_minor: 1250000", "annual_fee_minor: 1260000", 1)
    cards.write_text(text[:start] + changed, encoding="utf-8")
    (item,) = status(ws, "--seeds-dir", str(scratch))["proposals"]
    assert item["review_status"] == "approved" and len(item["decisions"]) == 1
    assert item["approval_applies"] is False
    assert "stale" in item["approval_note"]


def test_a_new_staging_of_the_same_values_is_a_new_proposal_without_the_old_approval(
    ws: Workspace,
) -> None:
    first = js(ws.stage("ex.yaml"))["proposals"][0]["proposal_id"]
    approve(ws, first)
    renamed = (ws.inputs / "target.yaml").read_text().replace("synth-card", "synth-card-2")
    ws.write("other-target.yaml", renamed)
    second = js(ws.stage("ex.yaml", target="other-target.yaml"))["proposals"][0]["proposal_id"]
    assert second != first
    by_id = {p["proposal_id"]: p for p in status(ws)["proposals"]}
    assert by_id[first]["approval_applies"] is True
    assert by_id[second]["decisions"] == [] and by_id[second]["approval_applies"] is False


def test_an_unknown_proposal_id_is_a_one_line_refusal_not_a_traceback(ws: Workspace) -> None:
    for command in ("inspect", "reopen"):
        done = cli([command, "--data-dir", str(ws.data), "--proposal-id", "proposal:none"])
        assert done.returncode == 2, command
        assert done.stderr.startswith("refused: unknown proposal"), done.stderr
        assert "Traceback" not in done.stderr
