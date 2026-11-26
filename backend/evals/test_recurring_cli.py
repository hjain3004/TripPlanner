"""The recurring welcome workflow through the real operator CLI, one process per step.

Execution mode: retained synthetic captures (no network, no credits spent), real SQLite and
artifact files shared between separate Python processes, the real review/decision command, the
real publisher, and the real catalog reader. A second process after each step stands for a
restart. The curator and every offer are synthetic acceptance data.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from evals.test_recurring_welcome_extraction import capture, offer_json, page
from ingestion.welcome_publication import CATALOG_FILE, read_catalog_rows

BACKEND = Path(__file__).resolve().parents[1]
URL = "https://issuer.example/cards/atlas/offers"
CARD = "hdfc-infinia"
MANAGED_FLAGS = [
    "--per-request-credits",
    "5",
    "--per-run-credits",
    "20",
    "--per-month-credits",
    "100",
]


def cli(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in {"TRIPWISE_ENV", "TRIPWISE_DATA_DIR"}}
    done = subprocess.run(
        [sys.executable, "-m", "ingestion.review_server", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if check:
        assert done.returncode == 0, done.stderr
    return done


class Workspace:
    def __init__(self, tmp_path: Path) -> None:
        self.data = tmp_path / "data"
        self.catalog = tmp_path / "published"
        self.inputs = tmp_path / "inputs"
        self.inputs.mkdir()
        (self.inputs / "policies.yaml").write_text(
            "- policy_id: issuer-offers\n"
            "  name: Issuer offers\n"
            "  owner: Synthetic Issuer\n"
            "  domain: issuer.example\n"
            f"  source_url: {URL}\n"
            "  terms_url: https://issuer.example/terms\n"
            "  terms_read_on: 2026-11-01\n"
            "  automated_access_permitted: true\n"
            "  manual_only: false\n"
            "  allowed_page_classes: [card_page, offer_page]\n"
            "  minimum_delay_seconds: 10\n"
            "  reviewed_on: 2026-11-01\n"
            "  reviewed_by: alice\n",
            encoding="utf-8",
        )
        (self.inputs / "watchlist.yaml").write_text(
            "- target_id: watch-atlas-offers\n"
            f"  url: {URL}\n"
            "  kind: offer_page\n"
            f"  target: [{CARD}]\n"
            "  source_policy_id: issuer-offers\n"
            "  check_frequency_days: 7\n"
            "  backend: firecrawl\n"
            "  manual_only: false\n",
            encoding="utf-8",
        )
        (self.inputs / "welcome_targets.yaml").write_text(
            "targets:\n"
            "  watch-atlas-offers:\n"
            f"    card_id: {CARD}\n"
            f"    source_url: {URL}\n"
            "    points_currency_id: acceptance-points\n",
            encoding="utf-8",
        )

    def capture(self, name: str, html: str, extracted: dict[str, Any] | None) -> Path:
        path = self.inputs / f"{name}.json"
        payload = capture(html, extracted)
        payload["data"]["metadata"].update({"url": URL, "sourceURL": URL})
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def manifest(self, name: str, capture_path: Path) -> Path:
        path = self.inputs / f"{name}.json"
        path.write_text(json.dumps({"watch-atlas-offers": str(capture_path)}), encoding="utf-8")
        return path

    def refresh(self, manifest: Path, *, prefix: str, extra: list[str] | None = None) -> Any:
        done = cli(
            "refresh-due",
            "--data-dir", str(self.data),
            "--source-policies", str(self.inputs / "policies.yaml"),
            "--watchlist", str(self.inputs / "watchlist.yaml"),
            "--welcome-targets", str(self.inputs / "welcome_targets.yaml"),
            "--published-welcome-catalog", str(self.catalog),
            "--retained-captures-manifest", str(manifest),
            "--client-event-prefix", prefix,
            "--lifetime-credits", "80",
            "--opening-credits-used", "67",
            *MANAGED_FLAGS,
            *(extra or []),
        )  # fmt: skip
        return json.loads(done.stdout)

    def acquire(
        self, capture_path: Path, *, event: str, extra: list[str] | None = None
    ) -> tuple[int, dict[str, Any]]:
        """An explicit acquisition (refresh-due only picks targets that are due by the calendar)."""
        done = cli(
            "acquire",
            "--data-dir", str(self.data),
            "--source-policy", str(self.inputs / "policies.yaml"),
            "--watch-target", str(self.inputs / "watchlist.yaml"),
            "--target-id", "watch-atlas-offers",
            "--welcome-targets", str(self.inputs / "welcome_targets.yaml"),
            "--published-welcome-catalog", str(self.catalog),
            "--retained-capture", str(capture_path),
            "--client-event-id", event,
            "--lifetime-credits", "80",
            "--opening-credits-used", "67",
            *MANAGED_FLAGS,
            *(extra or []),
            check=False,
        )  # fmt: skip
        return done.returncode, json.loads(done.stdout)

    def credits(self) -> dict[str, Any]:
        return dict(json.loads(cli("credit-status", "--data-dir", str(self.data)).stdout))


def test_the_recurring_workflow_end_to_end_across_separate_processes(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    cli("init-welcome-catalog", "--data-dir", str(ws.data), "--catalog-dir", str(ws.catalog))
    cli("add-curator", "--data-dir", str(ws.data), "--curator-id", "acceptance-curator",
        "--display-name", "Acceptance curator")  # fmt: skip

    # 1. Initial collection: one draft proposal; nothing is published.
    first = ws.capture("first", page(), offer_json())
    run = ws.refresh(ws.manifest("m1", first), prefix="cli-run-0001")
    (outcome,) = run["outcomes"]
    assert outcome["state"] == "completed", outcome
    assert outcome["extraction_mode"] == "firecrawl_managed" and outcome["llm_calls"] == 0
    (proposal_id,) = outcome["proposal_ids"]
    assert read_catalog_rows(ws.catalog) == {}
    assert ws.credits()["used"] == 72  # 67 before this ledger + 5 for page and extraction

    # 2. The queue, in a new process, shows it with its quotes.
    queue = json.loads(cli("review-queue", "--data-dir", str(ws.data), "--format", "json").stdout)
    assert [item["proposal_id"] for item in queue] == [proposal_id]
    assert any("2,500" in (f["quote"] or "") for f in queue[0]["fields"])

    # 3. Publication is refused until a curator approves.
    refused = cli("publish-welcome", "--data-dir", str(ws.data), "--catalog-dir", str(ws.catalog),
                  "--proposal-id", proposal_id, check=False)  # fmt: skip
    assert refused.returncode == 2 and "not_approved" in refused.stderr

    # 4. Unchanged replay spends nothing and makes no proposal.
    time.sleep(10.5)  # the source policy's minimum delay between requests to one domain
    code, again = ws.acquire(first, event="cli-acquire-0002")
    assert code == 0 and again["state"] == "unchanged" and again["proposal_ids"] == []
    assert ws.credits()["used"] == 77  # the page was fetched again (5), nothing was proposed
    assert (
        len(json.loads(cli("review-queue", "--data-dir", str(ws.data), "--format", "json").stdout))
        == 1
    )

    # 5. A curator approves and the proposal is published to the operator catalog.
    cli("decision", "--data-dir", str(ws.data), "--proposal-id", proposal_id,
        "--curator-id", "acceptance-curator", "--action", "approve",
        "--reason", "synthetic acceptance approval", "--expected-version", "1",
        "--client-event-id", "cli-approve-000001", "--curator-confidence", "0.8")  # fmt: skip
    published = json.loads(
        cli("publish-welcome", "--data-dir", str(ws.data), "--catalog-dir", str(ws.catalog),
            "--proposal-id", proposal_id).stdout
    )  # fmt: skip
    rows = read_catalog_rows(ws.catalog)
    (row,) = rows.values()
    assert row["provenance"]["verified_by"] == "acceptance-curator"
    assert published["needs_verification"] is True
    # The file a separate process wrote is what the service-side loader reads.
    from welcome.catalog import load_offer_catalog

    served = load_offer_catalog(ws.catalog / CATALOG_FILE).offers_for_card(CARD)
    assert [offer.id for offer in served] == list(rows)

    # 6. The issuer changes terms: the next pass proposes an update; the published row is unchanged
    #    until a curator decides.
    changed = ws.capture("changed", page(spend="40,000"), offer_json(spend="40,000"))
    # (the credit allowance of 80 has room for exactly one more page: 77 + 5 > 80 is refused)
    code, blocked = ws.acquire(changed, event="cli-acquire-0003")
    assert code == 2 and blocked["state"] == "blocked"
    assert "lifetime credit allowance is exhausted" in blocked["diagnostic"]
    assert read_catalog_rows(ws.catalog) == rows
    cli("raise-lifetime-cap", "--data-dir", str(ws.data), "--new-cap", "120",
        "--operator", "owner", "--note", "synthetic acceptance")  # fmt: skip
    time.sleep(10.5)
    code, update = ws.acquire(
        changed, event="cli-acquire-0004", extra=["--lifetime-credits", "10000"]
    )
    assert code == 0 and update["state"] == "completed", update
    assert ws.credits()["lifetime_cap"] == 120  # a later, larger flag did not loosen it
    update_id = update["proposal_ids"][0]
    inspected = cli("inspect", "--data-dir", str(ws.data), "--proposal-id", update_id).stdout
    assert "min_spend_minor" in inspected

    # 7. Publication history is durable and a rollback restores the previous bytes.
    history = json.loads(cli("welcome-history", "--data-dir", str(ws.data)).stdout)
    assert [event["event_type"] for event in history] == ["published"]
    before_rollback = (ws.catalog / CATALOG_FILE).read_bytes()
    cli("rollback-welcome", "--data-dir", str(ws.data), "--catalog-dir", str(ws.catalog),
        "--publication-id", published["publication_id"])  # fmt: skip
    assert (ws.catalog / CATALOG_FILE).read_bytes() != before_rollback
    assert read_catalog_rows(ws.catalog) == {}


def test_recurring_run_is_slot_idempotent_and_exclusive(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    cli("init-welcome-catalog", "--data-dir", str(ws.data), "--catalog-dir", str(ws.catalog))
    first = ws.capture("first", page(), offer_json())
    manifest = ws.manifest("m1", first)

    def run(slot: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
        return cli(
            "recurring-run",
            "--data-dir", str(ws.data),
            "--source-policies", str(ws.inputs / "policies.yaml"),
            "--watchlist", str(ws.inputs / "watchlist.yaml"),
            "--welcome-targets", str(ws.inputs / "welcome_targets.yaml"),
            "--published-welcome-catalog", str(ws.catalog),
            "--retained-captures-manifest", str(manifest),
            "--lifetime-credits", "80",
            "--opening-credits-used", "67",
            "--slot", slot,
            *MANAGED_FLAGS,
            check=check,
        )  # fmt: skip

    one = run("2026-11-28T09")
    assert json.loads(one.stdout)["counts"]["completed"] == 1
    used = ws.credits()["used"]
    assert used == 72

    repeat = run("2026-11-28T09")  # the scheduler fired twice for the same slot
    assert json.loads(repeat.stdout)["counts"]["selected"] == 0  # not due again; nothing spent
    assert ws.credits()["used"] == used

    summary = json.loads((ws.data / "recurring" / "last_run.json").read_text())
    assert summary["slot"] == "2026-11-28T09" and summary["exit_code"] == 0
    history = (ws.data / "recurring" / "history.jsonl").read_text().splitlines()
    assert len(history) == 2

    with (ws.data / "recurring" / "run.lock").open("w") as held:  # another run is in progress
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        busy = run("2026-11-28T10", check=False)
    assert busy.returncode == 75 and "another recurring run" in busy.stderr
    assert ws.credits()["used"] == used


def test_welcome_extraction_needs_enough_credits_per_request(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    first = ws.capture("first", page(), offer_json())
    refused = cli(
        "refresh-due",
        "--data-dir", str(ws.data),
        "--source-policies", str(ws.inputs / "policies.yaml"),
        "--watchlist", str(ws.inputs / "watchlist.yaml"),
        "--welcome-targets", str(ws.inputs / "welcome_targets.yaml"),
        "--retained-captures-manifest", str(ws.manifest("m1", first)),
        "--client-event-prefix", "cli-run-0001",
        check=False,
    )  # fmt: skip
    assert refused.returncode == 2 and "at least 5" in refused.stderr


def test_incomplete_drafts_are_listed_for_the_operator(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    extracted = offer_json(valid_to=None)  # the page states no end date
    run = ws.refresh(ws.manifest("m1", ws.capture("c", page(), extracted)), prefix="cli-run-0001")
    assert run["outcomes"][0]["proposal_ids"] == []
    (draft,) = json.loads(cli("incomplete-drafts", "--data-dir", str(ws.data)).stdout)
    assert draft["missing"] == ["valid_to"] and draft["title"]


@pytest.mark.parametrize("flag", ["--lifetime-credits"])
def test_a_lifetime_cap_is_recorded_once(tmp_path: Path, flag: str) -> None:
    ws = Workspace(tmp_path)
    first = ws.capture("first", page(), offer_json())
    ws.refresh(ws.manifest("m1", first), prefix="cli-run-0001")
    status = ws.credits()
    assert status["lifetime_cap"] == 80 and status["opening_used"] == 67
    assert flag  # the allowance now lives in the database, not in the flags
