"""The optimizer comparison reports "unchanged" only when the results really are identical."""

from __future__ import annotations

import shutil
from pathlib import Path

from core.db import SEEDS_DIR
from evals.card_bank_optimizer_compare import compare


def test_identical_seed_directories_give_an_identical_result(tmp_path: Path) -> None:
    copy = tmp_path / "seeds"
    shutil.copytree(SEEDS_DIR, copy)
    report = compare(SEEDS_DIR, copy, ["hdfc-infinia"])
    assert report["identical"] is True and report["changed_summary_fields"] == []
    assert report["baseline"]["summary"]["gross_minor"] > 0


def test_a_changed_forex_markup_is_reported_as_a_real_difference(tmp_path: Path) -> None:
    # Guard against a vacuous comparison: a different fact must show up in the result.
    copy = tmp_path / "seeds"
    shutil.copytree(SEEDS_DIR, copy)
    cards = copy / "cards.yaml"
    text = cards.read_text(encoding="utf-8")
    start = text.index("id: hdfc-infinia")
    changed = text[start:].replace("forex_markup_bp: 200", "forex_markup_bp: 350", 1)
    assert changed != text[start:]
    cards.write_text(text[:start] + changed, encoding="utf-8")
    report = compare(SEEDS_DIR, copy, ["hdfc-infinia"])
    assert report["identical"] is False
    assert "forex_fees_minor" in report["changed_summary_fields"]
    assert (
        report["candidate"]["summary"]["forex_fees_minor"]
        > report["baseline"]["summary"]["forex_fees_minor"]
    )
