"""Milestone C demonstration: controlled apply and rollback on a scratch copy of the seeds.

Runnable as ``python -m evals.card_bank_apply_demo [workdir]`` and exercised by
``evals/test_card_bank_apply_cli.py``. Every document is synthetic (``example.invalid``). Each
step is a separate ``python -m ingestion.review_server`` process with real SQLite files between
them, except the simulated power cut, which has to be injected in-process (the CLI deliberately
has no way to crash itself).

The repository's own seeds are never written: the scratch copy is the only target, and the run
ends by proving the repository seeds are byte-identical.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from core.db import SEEDS_DIR, load_kb, seed_database
from core.models import UserWallet
from core.optimizer import optimize
from core.optimizer.demo_data import demo_trip
from evals.test_card_bank_apply import (
    CARD,
    EXISTING,
    FX,
    RICH_PAGE,
    RULE,
    full_card_records,
    rec,
    rule_insert,
    rule_records,
)
from evals.test_card_bank_cli import POLICY
from ingestion.review_server import build_applier, build_runtime

BACKEND = Path(__file__).resolve().parents[1]
TARGET = f"""\
- target_id: synth-card
  url: https://www.example.invalid/card
  kind: manual_capture
  target: [{CARD}, "reward_rules:{RULE}", {EXISTING}]
  source_policy_id: synth-issuer
  check_frequency_days: 365
  backend: manual
  manual_only: true
"""


def file_hashes(directory: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.glob("*.yaml"))
    }


def short(hashes: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:16]


class Crash(RuntimeError):
    pass


def run(root: Path, echo: Callable[[str], None] = print) -> dict[str, Any]:
    """The whole storyline; returns the facts the acceptance test asserts."""
    data, inputs, scratch = root / "data", root / "in", root / "scratch_seeds"
    inputs.mkdir(parents=True)
    shutil.copytree(SEEDS_DIR, scratch)
    repo_before, pristine = file_hashes(SEEDS_DIR), file_hashes(scratch)
    facts: dict[str, Any] = {}

    def cli(*args: str) -> subprocess.CompletedProcess[str]:
        done = subprocess.run(
            [sys.executable, "-m", "ingestion.review_server", *args],
            cwd=BACKEND,
            capture_output=True,
            text=True,
            timeout=180,
        )
        echo(f"$ review_server {args[0]} ...  [exit {done.returncode}]")
        return done

    def say(text: str) -> None:
        echo(f"    {text}")

    dd = ["--data-dir", str(data)]
    sd = ["--seeds-dir", str(scratch)]
    (inputs / "policy.yaml").write_text(POLICY)
    (inputs / "target.yaml").write_text(TARGET)
    (inputs / "capture.html").write_text(RICH_PAGE)
    extraction = {
        "schema": "tripwise.curator-extraction/v1",
        "curator_id": "alice",
        "change_summary": "SYNTHETIC: a new card, its dining rule, and one existing-card update",
        "inserts": [
            {"table": "cards", "id": CARD, "row": {}},
            rule_insert(),
        ],
        "records": [
            *full_card_records(),
            *rule_records(),
            rec("cards", EXISTING, "forex_markup_bp", "3.5%", FX),
        ],
    }
    (inputs / "extraction.yaml").write_text(yaml.safe_dump(extraction, sort_keys=False))

    echo("== 1. stage a synthetic capture: 2 inserts + 1 update (scratch seeds, no network)")
    assert (
        cli("add-curator", *dd, "--curator-id", "alice", "--display-name", "Alice").returncode == 0
    )
    staged = cli(
        "stage-capture",
        *dd,
        *sd,
        "--capture",
        str(inputs / "capture.html"),
        "--source-policy",
        str(inputs / "policy.yaml"),
        "--watch-target",
        str(inputs / "target.yaml"),
        "--extraction",
        str(inputs / "extraction.yaml"),
        "--document-class",
        "card_page",
    )
    outcome = json.loads(staged.stdout)
    proposals = {p["target_id"]: p["proposal_id"] for p in outcome["proposals"]}
    say(
        f"staged {sorted(proposals)} (llm_calls={outcome['llm_calls']}, "
        f"network_calls={outcome['network_calls']})"
    )

    echo("== 2. curator review: approve all three")
    for index, pid in enumerate(proposals.values()):
        done = cli(
            "decision",
            *dd,
            *sd,
            "--proposal-id",
            pid,
            "--curator-id",
            "alice",
            "--action",
            "approve",
            "--reason",
            "synthetic row reviewed",
            "--expected-version",
            "1",
            "--client-event-id",
            f"demo-approve-event-{index:04d}",
            "--curator-confidence",
            "0.8",
        )
        assert done.returncode == 0, done.stderr

    echo("== 3. bundle + dry-run (still no authorization to apply)")
    bundled = cli(
        "bundle",
        *dd,
        *sd,
        "--curator-id",
        "alice",
        "--client-event-id",
        "demo-bundle-event-0001",
        *[x for pid in proposals.values() for x in ("--proposal-id", pid)],
    )
    sha = json.loads(bundled.stdout)["record"]["bundle_sha256"]
    dry = json.loads(cli("dry-run", *dd, *sd, "--bundle-sha256", sha).stdout)
    say(f"entries={[(e['target_id'], e['status']) for e in dry['entries']]}")
    say(
        f"dry_run_consistent={dry['dry_run_consistent']} "
        f"activation_authorized={dry['activation_authorized']}"
    )

    echo("== 4. the repository's own seeds are refused as a destination")
    refused = cli(
        "apply",
        *dd,
        "--seeds-dir",
        str(SEEDS_DIR),
        "--bundle-sha256",
        sha,
        "--curator-id",
        "alice",
        "--reason",
        "trying the real seeds",
        "--client-event-id",
        "demo-apply-event-real",
    )
    say(refused.stderr.strip())
    facts["repo_seeds_refused"] = "protected_seeds" in refused.stderr

    echo("== 5. KB before any apply (scratch): optimizer with the existing HDFC card")
    before_db = root / "before.db"
    seed_database(scratch, before_db)
    before = optimize(demo_trip(), UserWallet(card_ids=[EXISTING]), load_kb(before_db))
    say(f"forex fees with {EXISTING}: {before.forex_fees_minor} minor units")

    echo("== 6. confirm the origin (D2), then apply to the scratch seeds")
    done = cli(
        "confirm-origin",
        *dd,
        *sd,
        "--proposal-id",
        proposals[CARD],
        "--document-class",
        "card_page",
        "--curator-id",
        "alice",
        "--statement",
        "I opened the capture and it is the issuer's own synthetic page",
    )
    assert done.returncode == 0, done.stderr
    applied = cli(
        "apply",
        *dd,
        *sd,
        "--bundle-sha256",
        sha,
        "--curator-id",
        "alice",
        "--reason",
        "apply the synthetic bundle to scratch seeds",
        "--client-event-id",
        "demo-apply-event-0001",
    )
    record = json.loads(applied.stdout)
    after_apply = file_hashes(scratch)
    changed = sorted(n for n in after_apply if after_apply[n] != pristine[n])
    say(f"apply {record['apply_id']}: {record['status']}; files changed: {changed}")
    for row in record["plan"]["rows"]:
        say(
            f"{row['table']}/{row['row_id']} ({row['operation']}): needs_verification="
            f"{row['needs_verification']}, D1 satisfied={row['d1']['satisfied']} "
            f"(missing={len(row['d1']['missing'])}), D2={row['d2']}"
        )
    facts.update(apply_status=record["status"], changed=changed, plan_rows=record["plan"]["rows"])

    echo("== 7. the resulting seeds load and the existing deterministic optimizer runs on them")
    after_db = root / "after.db"
    seed_database(scratch, after_db)
    kb = load_kb(after_db)
    new = optimize(demo_trip(), UserWallet(card_ids=[CARD]), kb)
    dining = next(a for a in new.assignments if a.line.id == "dining")
    changed_hdfc = optimize(demo_trip(), UserWallet(card_ids=[EXISTING]), kb)
    say(f"new card {CARD}: dining line earns {dining.points_earned} points")
    say(f"{EXISTING} forex fees: {before.forex_fees_minor} -> {changed_hdfc.forex_fees_minor}")
    facts.update(
        dining_points=dining.points_earned,
        forex_before=before.forex_fees_minor,
        forex_after=changed_hdfc.forex_fees_minor,
    )

    echo("== 8. coverage from the ledger")
    cov = json.loads(cli("coverage", *dd, *sd).stdout)
    mine = {r["row_id"]: r for r in cov if r["row_id"] in {CARD, RULE, EXISTING}}
    for row_id, r in mine.items():
        say(
            f"{row_id}: needs_verification={r['needs_verification']} d1_satisfied="
            f"{r['d1_satisfied']} evidenced={r['evidenced']} missing={r['missing']}"
        )
    facts["coverage"] = mine

    echo("== 9. a stale bundle is refused (the same bundle, after the seeds moved on)")
    stale = cli(
        "apply",
        *dd,
        *sd,
        "--bundle-sha256",
        sha,
        "--curator-id",
        "alice",
        "--reason",
        "applying the same bundle again",
        "--client-event-id",
        "demo-apply-event-0002",
    )
    say(stale.stderr.strip())
    facts["stale_refused"] = "stale_bundle" in stale.stderr

    echo("== 10. rollback restores the exact prior bytes")
    rolled = cli(
        "rollback",
        *dd,
        *sd,
        "--apply-id",
        record["apply_id"],
        "--curator-id",
        "alice",
        "--reason",
        "demonstration rollback of the synthetic apply",
    )
    restored = file_hashes(scratch)
    say(
        f"status={json.loads(rolled.stdout)['status']}; byte-identical to before apply: "
        f"{restored == pristine} ({short(restored)} == {short(pristine)})"
    )
    facts["rollback_identical"] = restored == pristine
    seed_database(scratch, after_db)
    facts["card_gone_after_rollback"] = not load_kb(after_db).has_card(CARD)
    say(
        "new card present in the reloaded KB after rollback: "
        f"{not facts['card_gone_after_rollback']}"
    )

    echo("== 11. a power cut half-way through the writes, then recovery")
    store, _, _ = build_runtime(data, scratch, now=lambda: datetime.now(UTC))

    def cut_after_first_file(step: str) -> None:
        if step == "replaced:1":
            raise Crash(step)

    try:
        build_applier(data, store, now=lambda: datetime.now(UTC)).apply(
            bundle_sha256=sha,
            seeds_dir=scratch,
            curator_id="alice",
            reason="apply that will be interrupted",
            client_event_id="demo-apply-event-0003",
            checkpoint=cut_after_first_file,
        )
    except Crash:
        say("simulated power cut after the first seed file was replaced")
    mixed = file_hashes(scratch)
    say(
        f"seeds are now a MIXED set: {sorted(n for n in mixed if mixed[n] != pristine[n])} "
        "changed, the rest not"
    )
    blocked = cli(
        "apply",
        *dd,
        *sd,
        "--bundle-sha256",
        sha,
        "--curator-id",
        "alice",
        "--reason",
        "try to carry on regardless",
        "--client-event-id",
        "demo-apply-event-0004",
    )
    say(blocked.stderr.strip())
    recovered = json.loads(cli("recover", *dd, *sd).stdout)
    say(f"recover: {recovered}")
    facts.update(
        mixed_after_crash=mixed != pristine,
        blocked_until_recovered="incomplete_apply" in blocked.stderr,
        recovery=recovered,
        restored_after_recovery=file_hashes(scratch) == pristine,
    )
    say(f"byte-identical after recovery: {facts['restored_after_recovery']}")
    again = cli(
        "apply",
        *dd,
        *sd,
        "--bundle-sha256",
        sha,
        "--curator-id",
        "alice",
        "--reason",
        "apply again after recovery",
        "--client-event-id",
        "demo-apply-event-0005",
    )
    say(f"apply after recovery: {json.loads(again.stdout)['status']}")
    facts["apply_after_recovery"] = json.loads(again.stdout)["status"]

    facts["repo_seeds_unchanged"] = file_hashes(SEEDS_DIR) == repo_before
    echo(f"== repository seeds byte-identical: {facts['repo_seeds_unchanged']}")
    return facts


if __name__ == "__main__":
    target = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="apply-demo-"))
    )
    run(target / "demo" if len(sys.argv) > 1 else target / "demo")
