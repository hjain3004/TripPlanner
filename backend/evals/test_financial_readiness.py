"""Financial-data readiness for the demonstration trip: a measured view, a review packet, and the
honest refusal for a draft nobody has decided. Real SQLite and the real CLI processes; the only
documents are synthetic (``example.invalid``). Nothing here says anything about any issuer.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from core.db import SEEDS_DIR
from core.models import UserWallet
from core.optimizer import optimize
from core.optimizer.demo_data import demo_trip
from evals.test_card_bank_cli import FEE, FX, Workspace, cli, extraction, js, rec, seed_hashes

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    workspace = Workspace(tmp_path)
    workspace.register()
    workspace.write(
        "ex.yaml",
        extraction(rec("annual_fee_minor", "INR 15,000", FEE), rec("forex_markup_bp", "3.5%", FX)),
    )
    return workspace


def data(ws: Workspace) -> list[str]:
    return ["--data-dir", str(ws.data)]


# --- a draft nobody has decided cannot be bundled, and says why ------------------------------ #


def test_bundling_a_draft_awaiting_a_curator_says_so_not_an_index_error(ws: Workspace) -> None:
    staged = js(ws.stage("ex.yaml"))
    proposal_id = staged["proposals"][0]["proposal_id"]

    built = js(
        cli(
            [
                "bundle",
                *data(ws),
                "--curator-id",
                "alice",
                "--client-event-id",
                "bundle-pending-1",
                "--proposal-id",
                proposal_id,
            ]
        )
    )

    assert built["bundle"]["entries"] == []
    (refused,) = built["bundle"]["refused"]
    assert refused["proposal_id"] == proposal_id
    assert "awaiting a curator" in refused["message"]
    assert "index" not in refused["message"]


# --- the readiness view is measured, trip-specific and writes nothing ------------------------- #


def readiness(*args: str) -> dict[str, Any]:
    done = cli(["readiness", "--format", "json", *args])
    assert done.returncode == 0, done.stderr
    return js(done)


def test_readiness_on_the_real_seeds_measures_what_moves_the_demo_trip() -> None:
    before = seed_hashes()
    report = readiness()
    facts = {
        (f["table"], f["row_id"], f["field_path"]): f
        for row in report["rows"]
        for f in row["facts"]
    }

    assert report["trip"] == "demo-del-sin" and report["wallet"] == ["hdfc-infinia", "axis-atlas"]
    # facts the unchanged optimizer actually uses for this trip
    for key in (
        ("cards", "hdfc-infinia", "forex_markup_bp"),
        ("cards", "axis-atlas", "base_earn.points"),
        ("point_valuations", "infinia-portal-val", "value_micro_major_per_point"),
        ("reward_rules", "atlas-travel", "earn.points"),
    ):
        assert facts[key]["influence"] == "moves_trip_result", key
        assert facts[key]["state"] == "unverified_placeholder", key
    # and facts that are measured not to
    assert facts[("cards", "hdfc-infinia", "annual_fee_minor")]["influence"] == "no_effect_observed"
    # a text fact is varied with the other values the seeds hold: the card network decides which
    # network-restricted offers apply, so it moves the trip (it used to be reported as harmless)
    assert facts[("cards", "hdfc-infinia", "network")]["influence"] == "moves_trip_result"
    assert facts[("cards", "hdfc-infinia", "network")]["needed_for_trip"] is True
    # a list cannot be varied: it is reported as unmeasured, still in scope, never as harmless
    assert facts[("reward_rules", "atlas-travel", "channels")]["influence"] == "not_probed"
    assert facts[("reward_rules", "atlas-travel", "channels")]["needed_for_trip"] is True
    assert (
        facts[("cards", "hdfc-infinia", "lounge_intl_visits_per_year")]["needed_for_trip"] is False
    )
    # no card outside the wallet is in scope
    assert not any(row["row_id"] in {"sbi-cashback", "icici-emeralde"} for row in report["rows"])
    # every seeded fact in scope is an unverified placeholder: nothing is "ready"
    assert report["summary"] and set(report["summary"]) == {
        "needed_for_trip:unverified_placeholder"
    }
    assert seed_hashes() == before


def test_the_gaps_name_what_the_schema_and_catalogs_cannot_hold() -> None:
    gaps = {g["id"]: g for g in readiness()["gaps"]}

    assert {
        "welcome_offer_catalog_empty",
        "no_card_currency_programs",
        "no_card_to_program_link",
    } <= set(gaps)
    assert "0 offers" in gaps["welcome_offer_catalog_empty"]["detail"]
    assert "voyager-prime" in gaps["demo_balance_program_not_seeded"]["detail"]


def test_a_different_wallet_changes_the_scope() -> None:
    report = readiness("--wallet-card", "sbi-cashback")

    assert report["wallet"] == ["sbi-cashback"]
    assert {r["row_id"] for r in report["rows"] if r["table"] == "cards"} == {"sbi-cashback"}


def test_findings_are_shown_next_to_their_facts_and_unmatched_ones_are_reported(
    tmp_path: Path,
) -> None:
    path = tmp_path / "findings.yaml"
    path.write_text(
        "- {table: cards, id: hdfc-infinia, field: forex_markup_bp, verdict: not_stated_in_capture,"
        " note: 'synthetic: the document states no markup'}\n"
        "- {table: cards, id: nobody, field: x, verdict: not_stated_in_capture,"
        " note: 'matches nothing'}\n"
    )

    report = readiness("--findings", str(path))
    fact = next(
        f
        for row in report["rows"]
        for f in row["facts"]
        if f["field_path"] == "forex_markup_bp" and f["row_id"] == "hdfc-infinia"
    )

    assert fact["finding"] == "not_stated_in_capture"
    assert fact["finding_note"].startswith("synthetic")
    assert [f["id"] for f in report["unmatched_findings"]] == ["nobody"]


def test_a_findings_file_with_an_unknown_key_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "findings.yaml"
    path.write_text(
        "- {table: cards, id: hdfc-infinia, field: forex_markup_bp, verdict: ok, extra: 1}\n"
    )

    done = cli(["readiness", "--findings", str(path)])

    assert done.returncode != 0


# --- state comes from the real ingestion database, never from the seeds ----------------------- #


def test_a_staged_draft_is_awaiting_review_and_an_approval_is_not_confused_with_it(
    ws: Workspace,
) -> None:
    staged = js(ws.stage("ex.yaml"))
    proposal_id = staged["proposals"][0]["proposal_id"]

    pending = readiness(*data(ws))
    fx = {
        f["field_path"]: f
        for row in pending["rows"]
        for f in row["facts"]
        if row["row_id"] == "hdfc-infinia"
    }
    assert fx["forex_markup_bp"]["state"] == "awaiting_human_review"
    assert any("pending a curator decision" in e for e in fx["forex_markup_bp"]["evidence"])
    assert any("hdfc-infinia" in d and "Decide proposal" in d for d in pending["owner_decisions"])

    done = cli(
        [
            "decision",
            *data(ws),
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
            "approve-readiness-1",
            "--curator-confidence",
            "0.9",
        ]
    )
    assert done.returncode == 0, done.stderr
    approved = readiness(*data(ws))
    fx = {
        f["field_path"]: f
        for row in approved["rows"]
        for f in row["facts"]
        if row["row_id"] == "hdfc-infinia"
    }
    assert fx["forex_markup_bp"]["state"] == "approved_not_applied"
    # approving did not make the seed any less of a placeholder
    assert "needs_verification=True" in next(
        r["provenance"] for r in approved["rows"] if r["row_id"] == "hdfc-infinia"
    )


def test_readiness_does_not_create_state_in_a_missing_data_directory(tmp_path: Path) -> None:
    missing = tmp_path / "nothing-here"

    done = cli(["readiness", "--data-dir", str(missing), "--format", "json"])

    assert done.returncode == 0, done.stderr
    assert not (missing / "ingestion.sqlite").exists() and not (missing / "apply.sqlite").exists()


# --- the review packet ---------------------------------------------------------------------- #


def test_the_review_queue_shows_quotes_values_age_and_what_is_left_unverified(
    ws: Workspace,
) -> None:
    ws.stage("ex.yaml", extra=["--captured-at", "2026-10-31T05:40:00+00:00"])

    items = js(cli(["review-queue", *data(ws), "--format", "json"]))
    (item,) = items
    fields = {f["field_path"]: f for f in item["fields"]}

    assert item["status"] == "pending" and item["decisions"] == []
    assert item["blocked_by"] == ["D1", "D2"]
    assert (
        fields["annual_fee_minor"]["quote"] == FEE and fields["annual_fee_minor"]["quote_verified"]
    )
    assert (
        fields["annual_fee_minor"]["current"] == 1250000 and fields["annual_fee_minor"]["changed"]
    )
    assert item["capture_age_days"] >= 6
    assert (
        "network" in item["unresolved_fields"]
        and "annual_fee_minor" not in item["unresolved_fields"]
    )
    assert item["owner_actions"][1].count("<YOUR_CURATOR_ID>") == 1  # a template, never run

    markdown = cli(["review-queue", *data(ws)])
    assert markdown.returncode == 0 and "Nothing here is approved" in markdown.stdout
    assert FEE in markdown.stdout


def test_a_packet_that_quotes_captures_cannot_be_written_inside_the_repository(
    ws: Workspace,
) -> None:
    ws.stage("ex.yaml")
    inside = Path(__file__).resolve().parents[2] / "reports" / "must-not-exist.md"

    done = cli(["review-queue", *data(ws), "--out", str(inside)])

    assert done.returncode == 2 and "outside the repository" in done.stderr
    assert not inside.exists()
    ok = cli(["review-queue", *data(ws), "--out", str(ws.root / "packet.md")])
    assert ok.returncode == 0 and (ws.root / "packet.md").read_text().startswith("# Financial-data")


# --- the probe agrees with a direct run of the optimizer ------------------------------------- #


def test_the_probe_agrees_with_running_the_optimizer_directly() -> None:
    import yaml

    from core.models import FxRate
    from ingestion.readiness import _kb
    from ingestion.review_rows import SUPPORTED_TABLES, SeedRowSource

    rows = {t: SeedRowSource(SEEDS_DIR).table_rows(t) for t in SUPPORTED_TABLES}
    fx = [
        FxRate.model_validate(r) for r in yaml.safe_load((SEEDS_DIR / "fx_rates.yaml").read_text())
    ]
    wallet = UserWallet(card_ids=["hdfc-infinia"])
    base = optimize(demo_trip(), wallet, _kb(rows, fx)).forex_fees_minor
    for row in rows["cards"]:
        if row["id"] == "hdfc-infinia":
            row["forex_markup_bp"] = 400
    changed = optimize(demo_trip(), wallet, _kb(rows, fx)).forex_fees_minor

    assert changed > base  # a direct run: the markup really changes the money
    facts = {
        (r["row_id"], f["field_path"]): f
        for r in readiness()["rows"]
        for f in r["facts"]
        if r["table"] == "cards"
    }
    assert facts[("hdfc-infinia", "forex_markup_bp")]["influence"] == "moves_trip_result"


# --- reading must not change anything --------------------------------------------------------- #


def test_readiness_refuses_an_older_database_instead_of_migrating_it(ws: Workspace) -> None:
    ws.stage("ex.yaml")
    db = ws.data / "ingestion.sqlite"
    with sqlite3.connect(db) as connection:
        connection.execute("PRAGMA user_version = 3")
    before = db.read_bytes()

    done = cli(["readiness", *data(ws)])

    assert done.returncode == 2 and "never migrates" in done.stderr
    assert db.read_bytes() == before  # not one byte changed
    with sqlite3.connect(db) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3


def test_readiness_leaves_a_current_database_byte_identical(ws: Workspace) -> None:
    ws.stage("ex.yaml")
    db = ws.data / "ingestion.sqlite"
    before = db.read_bytes()

    readiness(*data(ws))

    assert db.read_bytes() == before


def test_review_queue_refuses_a_directory_with_no_database_instead_of_creating_one(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "nothing"

    done = cli(["review-queue", "--data-dir", str(missing)])

    assert done.returncode == 2 and "no ingestion database" in done.stderr
    assert not missing.exists()


def test_readiness_output_cannot_be_written_inside_the_repository_even_via_a_symlink(
    tmp_path: Path,
) -> None:
    repo = Path(__file__).resolve().parents[2]
    link = tmp_path / "into-repo"
    link.symlink_to(repo / "reports")

    for target in (link / "x.md", repo / "reports" / ".." / "reports" / "y.md"):
        done = cli(["readiness", "--out", str(target)])
        assert done.returncode == 2 and "outside the repository" in done.stderr
    assert not (repo / "reports" / "x.md").exists() and not (repo / "reports" / "y.md").exists()


# --- the ledger path: scratch apply, origin confirmation, rollback ------------------------------ #


def decide(ws: Workspace, proposal_id: str) -> None:
    done = cli(
        [
            "decision",
            *data(ws),
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
            "approve-readiness-ledger",
            "--curator-confidence",
            "0.9",
        ]
    )
    assert done.returncode == 0, done.stderr


def fact_state(report: dict[str, Any], field: str) -> str:
    return next(
        f["state"]
        for row in report["rows"]
        for f in row["facts"]
        if row["row_id"] == "hdfc-infinia" and f["field_path"] == field
    )


def test_a_scratch_apply_is_recorded_then_confirmed_then_rolled_back(
    ws: Workspace, tmp_path: Path
) -> None:
    proposal_id = js(ws.stage("ex.yaml"))["proposals"][0]["proposal_id"]
    decide(ws, proposal_id)
    scratch = tmp_path / "scratch"
    shutil.copytree(SEEDS_DIR, scratch)
    seeds = ["--seeds-dir", str(scratch)]
    bundle = js(
        cli(
            [
                "bundle",
                *data(ws),
                *seeds,
                "--curator-id",
                "alice",
                "--client-event-id",
                "bundle-ledger",
                "--proposal-id",
                proposal_id,
            ]
        )
    )["record"]["bundle_sha256"]
    applied = js(
        cli(
            [
                "apply",
                *data(ws),
                *seeds,
                "--bundle-sha256",
                bundle,
                "--curator-id",
                "alice",
                "--reason",
                "SYNTHETIC scratch apply",
                "--client-event-id",
                "apply-ledger",
            ]
        )
    )

    # evidence is recorded, but the capture's origin was never confirmed: it must not count
    recorded = readiness(*data(ws), *seeds)
    assert fact_state(recorded, "forex_markup_bp") == "evidence_recorded_origin_unconfirmed"

    confirmed = cli(
        [
            "confirm-origin",
            *data(ws),
            *seeds,
            "--proposal-id",
            proposal_id,
            "--document-class",
            "card_page",
            "--curator-id",
            "alice",
            "--statement",
            "SYNTHETIC: the fixture is the issuer page",
        ]
    )
    assert confirmed.returncode == 0, confirmed.stderr
    assert fact_state(readiness(*data(ws), *seeds), "forex_markup_bp") == "evidenced"
    # the same ledger evidence does not leak onto other seeds (it is keyed by the seeds directory)
    assert fact_state(readiness(*data(ws)), "forex_markup_bp") == "approved_not_applied"

    rolled = cli(
        [
            "rollback",
            *data(ws),
            *seeds,
            "--apply-id",
            applied["apply_id"],
            "--curator-id",
            "alice",
            "--reason",
            "SYNTHETIC rollback",
        ]
    )
    assert rolled.returncode == 0, rolled.stderr
    # a rolled-back apply's evidence no longer counts
    after = fact_state(readiness(*data(ws), *seeds), "forex_markup_bp")
    assert after == "approved_not_applied"
