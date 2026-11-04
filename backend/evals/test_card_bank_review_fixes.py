"""Regressions for the independent review of Milestone B (each was reproduced before the fix)."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.db import SEEDS_DIR
from evals.test_card_bank_cli import POLICY
from evals.test_card_bank_insert_cli import LEAD, SOURCES
from evals.test_card_bank_inserts import InsertEnv, approve, card_insert, rec
from ingestion.activation import ActivationBundle, ActivationBundleRecord
from ingestion.config_loaders import (
    ConfigValidationError,
    host_of,
    is_aggregator_host,
    load_discovery_candidate,
    load_discovery_sources,
)
from ingestion.contracts import ChangeProposal
from ingestion.review_html import render_proposal
from ingestion.review_server import main

SOURCES_PATH_NAME = "discovery_sources.yaml"


@pytest.fixture
def env(tmp_path: Path) -> InsertEnv:
    return InsertEnv(tmp_path)


def _sources(tmp_path: Path) -> Any:
    path = tmp_path / SOURCES_PATH_NAME
    path.write_text(SOURCES)
    return load_discovery_sources(path, today=date(2026, 11, 4))


def _lead(tmp_path: Path, **over: str) -> Path:
    data = yaml.safe_load(LEAD)
    data.update(over)
    path = tmp_path / "lead.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return path


# ------------------------------------------------------------------ 1. reviewer visibility


def test_the_review_page_shows_every_value_and_flags_those_nobody_evidenced(
    env: InsertEnv,
) -> None:
    outcome = env.put(inserts=[card_insert(name="Totally Different Name", forex_markup_tax_bp=0)])
    (staged,) = outcome.proposals
    service, _ = env.runtime()
    ctx = service.context(staged.proposal_id)
    flagged = {f.field_path for f in ctx.computed_findings if f.code.value == "unevidenced_field"}
    assert {"name", "forex_markup_tax_bp", "issuer", "network"} <= flagged
    assert "annual_fee_minor" not in flagged  # that one has a quote
    page = render_proposal(ctx, csrf_token="c", client_event_id="e")
    for needle in ("Totally Different Name", "Synthetic Bank", "forex_markup_tax_bp", "visa"):
        assert needle in page
    assert "typed by curator" in page and "quoted evidence" in page
    # the decision records that the reviewer was told
    decision = approve(service, staged.proposal_id)
    assert decision.attestation is not None
    assert "unevidenced_field" in decision.attestation.computed_finding_codes


def test_an_update_review_page_is_unchanged_by_the_insert_table(env: InsertEnv) -> None:
    outcome = env.stage(
        [
            rec(
                "cards",
                "hdfc-infinia",
                "forex_markup_bp",
                "3.5%",
                "Foreign currency markup is 3.5% on every international transaction.",
            )
        ],
        target=env.target(target_fact_ids=("hdfc-infinia",)),
    )
    service, _ = env.runtime()
    ctx = service.context(outcome.proposals[0].proposal_id)
    page = render_proposal(ctx, csrf_token="c", client_event_id="e")
    assert "Proposed row" not in page
    assert all(f.code.value != "unevidenced_field" for f in ctx.computed_findings)


# ------------------------------------------------------------------ 2. lead restriction


@pytest.mark.parametrize(
    "field,value",
    [
        ("claim_summary", "Earns five percent cashback on dining and no annual fee"),
        ("claim_summary", "Annual fee of ٢٥٠٠ for this card"),  # Arabic-Indic
        ("claim_summary", "Annual fee of ２５００ for this card"),  # fullwidth
        ("claim_summary", "Costs ¥ per year"),
        ("claim_summary", "Pays 5٪ back"),
        ("product_guess", "Voyager 5% cashback, 2500 INR annual fee, 10X points"),
        ("issuer_guess", "Synthetic Bank 2500"),
        ("product_guess", "x" * 81),
    ],
)
def test_a_manual_only_lead_cannot_carry_facts_in_any_field_or_script(
    tmp_path: Path, field: str, value: str
) -> None:
    with pytest.raises(ConfigValidationError) as error:
        load_discovery_candidate(_lead(tmp_path, **{field: value}), sources=_sources(tmp_path))
    assert any(i.code == "lead_carries_facts" for i in error.value.issues)


def test_a_plain_name_only_lead_is_still_accepted(tmp_path: Path) -> None:
    lead = load_discovery_candidate(_lead(tmp_path), sources=_sources(tmp_path))
    assert lead.id == "lead-voyager"


# ------------------------------------------------------------------ 5. host spelling


@pytest.mark.parametrize(
    "url",
    [
        "https://www.bankbazaar。com/card",  # ideographic full stop
        "https://www.bankbazaar．com/card",  # fullwidth full stop
        "https://www.bank​bazaar.com/card",  # zero-width space
        "https://WWW.BankBazaar.COM./card",
    ],
)
def test_an_aggregator_cannot_hide_behind_an_odd_spelling(url: str) -> None:
    assert is_aggregator_host(host_of(url)), host_of(url)


# ------------------------------------------------------------------ 3/4. add-lead and promote-lead


class Cli:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.data = root / "data"
        self.inputs = root / "in"
        self.inputs.mkdir()
        (self.inputs / SOURCES_PATH_NAME).write_text(SOURCES)
        (self.inputs / "policy.yaml").write_text(POLICY)
        (self.inputs / "lead.yaml").write_text(LEAD)

    def run(self, *args: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
        rc = main([*args, "--data-dir", str(self.data)], env={})
        captured = capsys.readouterr()
        return rc, captured.out, captured.err

    def curator(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert (
            self.run("add-curator", "--curator-id", "alice", "--display-name", "A", capsys=capsys)[
                0
            ]
            == 0
        )

    def add_lead(self, name: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
        return self.run(
            "add-lead",
            "--lead",
            str(self.inputs / name),
            "--discovery-sources",
            str(self.inputs / SOURCES_PATH_NAME),
            capsys=capsys,
        )

    def promote(self, capsys: pytest.CaptureFixture[str], **over: str) -> tuple[int, str, str]:
        args = {
            "--lead-id": "lead-voyager",
            "--curator-id": "alice",
            "--source-policy": str(self.inputs / "policy.yaml"),
            "--discovery-sources": str(self.inputs / SOURCES_PATH_NAME),
            "--row-id": "synthetic-voyager",
            "--out": str(self.inputs / "target.yaml"),
        }
        args.update(over)
        flat = [x for pair in args.items() for x in pair]
        return self.run("promote-lead", *flat, capsys=capsys)


def test_a_duplicate_lead_cannot_hide_behind_spacing_or_a_card_suffix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = Cli(tmp_path)
    assert cli.add_lead("lead.yaml", capsys)[0] == 0
    for index, variant in enumerate(
        ["Example  Voyager", "example voyager", "Example Voyager Card", " Example\tVoyager "]
    ):
        data = yaml.safe_load(LEAD)
        data.update(id=f"lead-dup-{index}", product_guess=variant)
        (cli.inputs / f"dup{index}.yaml").write_text(yaml.safe_dump(data))
        rc, _, err = cli.add_lead(f"dup{index}.yaml", capsys)
        assert rc == 2 and "lead_duplicate" in err, (variant, err)


def test_the_knowledge_base_duplicate_check_ignores_spacing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = Cli(tmp_path)
    data = yaml.safe_load(LEAD)
    data.update(issuer_guess="HDFC  Bank", product_guess="infinia metal")
    (cli.inputs / "kb.yaml").write_text(yaml.safe_dump(data))
    rc, _, err = cli.add_lead("kb.yaml", capsys)
    assert rc == 2 and "lead_duplicate" in err


@pytest.mark.parametrize(
    "over,code",
    [
        ({"--table": "nonsense"}, "unsupported_target_table"),
        ({"--row-id": "Bad ID!"}, "invalid_row_id"),
        ({"--out": "/no/such/directory/target.yaml"}, "output_directory_missing"),
    ],
)
def test_promote_lead_refuses_bad_arguments_before_storing_anything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], over: dict[str, str], code: str
) -> None:
    cli = Cli(tmp_path)
    cli.curator(capsys)
    assert cli.add_lead("lead.yaml", capsys)[0] == 0
    rc, _, err = cli.promote(capsys, **over)
    assert rc == 2 and f"refused: {code}" in err
    # nothing was stored, so the lead can still be promoted correctly
    rc, out, err = cli.promote(capsys)
    assert rc == 0, err
    assert json.loads(out.splitlines()[-1])["aggregator_url_carried"] is False
    assert not list(cli.inputs.glob(".*.tmp"))


# ------------------------------------------------------------------ 6. offer references


def test_an_offer_pointing_at_a_card_that_does_not_exist_is_not_consistent(
    env: InsertEnv,
) -> None:
    # The knowledge-base-wide check: an offers row referencing an unknown card.
    seeds = env.root / "seeds"
    import shutil

    shutil.copytree(SEEDS_DIR, seeds)
    offers = yaml.safe_load((seeds / "offers.yaml").read_text())
    offers[0]["card_ids"] = ["no-such-card"]
    (seeds / "offers.yaml").write_text(yaml.safe_dump(offers, sort_keys=False))
    _, planner = env.runtime(seeds)
    record, _ = planner.build(
        proposal_ids=(), curator_id="alice", client_event_id="bundle-empty-ref-01"
    )
    report = planner.dry_run(record.bundle_sha256)
    assert "unknown card reference: no-such-card" in report.reference_errors
    assert not report.kb_constructs and not report.dry_run_consistent


def test_the_shipped_offers_all_reference_real_cards() -> None:
    cards = {c["id"] for c in yaml.safe_load((SEEDS_DIR / "cards.yaml").read_text())}
    for offer in yaml.safe_load((SEEDS_DIR / "offers.yaml").read_text()):
        assert set(offer.get("card_ids") or []) <= cards


# ------------------------------------------------------------------ 10. frozen bytes


def test_an_update_proposal_and_bundle_shape_are_byte_frozen() -> None:
    from evals.test_card_bank_inserts import _update_proposal

    payload = _update_proposal().model_dump_json()
    assert hashlib.sha256(payload.encode()).hexdigest() == FROZEN_UPDATE_PROPOSAL_SHA
    assert ChangeProposal.model_validate_json(payload).model_dump_json() == payload
    assert "operation" not in ActivationBundle.model_fields
    assert set(ActivationBundleRecord.model_fields) == {"bundle_sha256", "artifact", "proposal_ids"}


# Measured at 4a24fe3, before insert proposals existed.
FROZEN_UPDATE_PROPOSAL_SHA = "1ab436d7d30879c1eb918b4ad85a0c9776d3a15410f0e4e44cd5e7575a162033"  # noqa: E501
