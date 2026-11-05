"""Run the existing deterministic optimizer against two seed directories and compare.

The financial consequence of a controlled apply is the difference it makes to the optimizer, so
this runs ``optimize`` (unchanged; no money arithmetic lives here) on the demo trip for the same
wallet against a baseline and a candidate seed directory and reports whether the full results
are identical::

    python -m evals.card_bank_optimizer_compare --baseline SEEDS_A --candidate SEEDS_B \
        --card-id hdfc-infinia

Both directories are read; nothing is written except two temporary SQLite files, removed on exit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from core.db import load_kb, seed_database
from core.models import UserWallet
from core.optimizer import optimize
from core.optimizer.demo_data import demo_trip

SUMMARY_FIELDS = (
    "gross_minor",
    "discounts_minor",
    "rewards_value_minor",
    "forex_fees_minor",
    "effective_cost_minor",
    "cash_outlay_now_minor",
    "deferred_value_minor",
    "savings_pct_bp",
)


def run_optimizer(seeds_dir: Path, card_ids: Sequence[str]) -> dict[str, Any]:
    """The optimizer result for the demo trip and wallet, as a summary plus a full-result hash."""
    with tempfile.TemporaryDirectory(prefix="tripwise-optimizer-compare-") as scratch:
        db_path = Path(scratch) / "kb.db"
        seed_database(seeds_dir, db_path)
        result = optimize(demo_trip(), UserWallet(card_ids=list(card_ids)), load_kb(db_path))
    full = json.dumps(result.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return {
        "summary": {name: getattr(result, name) for name in SUMMARY_FIELDS},
        "assignments": len(result.assignments),
        "confidence": result.confidence,
        "result_sha256": hashlib.sha256(full.encode()).hexdigest(),
    }


def compare(baseline: Path, candidate: Path, card_ids: Sequence[str]) -> dict[str, Any]:
    before = run_optimizer(baseline, card_ids)
    after = run_optimizer(candidate, card_ids)
    return {
        "trip": "demo_trip (DEL to SIN)",
        "card_ids": list(card_ids),
        "baseline": before,
        "candidate": after,
        "identical": before["result_sha256"] == after["result_sha256"],
        "changed_summary_fields": [
            name for name in SUMMARY_FIELDS if before["summary"][name] != after["summary"][name]
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.card_bank_optimizer_compare")
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--card-id", action="append", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(compare(args.baseline, args.candidate, args.card_id), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
