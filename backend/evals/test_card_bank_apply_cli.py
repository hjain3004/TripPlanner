"""Milestone C acceptance: the whole controlled-apply storyline through the real CLI.

Separate ``review_server`` processes with real SQLite files between them, on a scratch copy of the
seeds, with synthetic documents. See ``evals/card_bank_apply_demo.py`` for the narrated version
(``python -m evals.card_bank_apply_demo``).
"""

from __future__ import annotations

from pathlib import Path

from evals.card_bank_apply_demo import run
from evals.test_card_bank_apply import CARD, EXISTING, RULE


def test_the_full_apply_rollback_and_recovery_storyline(tmp_path: Path) -> None:
    facts = run(tmp_path / "demo", echo=lambda _line: None)
    assert facts["repo_seeds_refused"] is True
    assert facts["apply_status"] == "committed"
    assert facts["changed"] == ["cards.yaml", "reward_rules.yaml"]
    rows = {r["row_id"]: r for r in facts["plan_rows"]}
    # the fully evidenced, origin-confirmed insert is the only row allowed to clear the flag
    assert rows[CARD]["needs_verification"] is False
    assert rows[RULE]["needs_verification"] is True  # 5 template values nobody quoted
    assert rows[EXISTING]["needs_verification"] is True  # an update to a placeholder row
    # the applied seeds really drive the existing deterministic optimizer
    assert facts["dining_points"] == 2000  # Rs20,000 dining at 10 points per Rs100
    assert facts["forex_after"] > facts["forex_before"]  # 2.00% -> 3.50% markup on the update
    assert facts["coverage"][CARD]["d1_satisfied"] is True
    assert facts["coverage"][EXISTING]["d1_satisfied"] is False
    assert facts["stale_refused"] is True
    assert facts["rollback_identical"] is True
    assert facts["card_gone_after_rollback"] is True
    assert facts["mixed_after_crash"] is True
    assert facts["blocked_until_recovered"] is True
    assert [r["outcome"] for r in facts["recovery"]] == ["rolled_back_by_recovery"]
    assert facts["restored_after_recovery"] is True
    assert facts["apply_after_recovery"] == "committed"
    assert facts["repo_seeds_unchanged"] is True
