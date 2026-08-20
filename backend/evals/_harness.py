"""Golden-file harness (spec 04 §1).

Loads a self-contained golden YAML (inline KB fixture + wallet + prefs + lines +
expected values), runs ``optimize``, and returns both. Default provenance is
injected onto inline facts so golden files stay focused on the math (Tier-V test
convenience; see DEVIATIONS re: point_valuations in the kb block).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from core.db import KnowledgeBase
from core.models import (
    Card,
    CostedTrip,
    Offer,
    OptimizationPrefs,
    PointValuation,
    RewardRule,
    SpendLineItem,
    UserWallet,
)
from core.optimizer import optimize

GOLDEN_DIR = Path(__file__).parent / "golden"

_DEFAULT_PROV: dict[str, Any] = {
    "source_type": "manual_curation",
    "last_verified": "2026-07-07",
    "verified_by": "UNVERIFIED",
    "needs_verification": True,
    "confidence": 1.0,
}


def _with_prov(row: dict[str, Any]) -> dict[str, Any]:
    if "provenance" not in row:
        row = {**row, "provenance": dict(_DEFAULT_PROV)}
    return row


def golden_files() -> list[Path]:
    out: list[Path] = []
    for path in sorted(GOLDEN_DIR.glob("*.yaml")):
        spec = yaml.safe_load(path.read_text()) or {}
        if "kb" in spec and "lines" in spec:
            out.append(path)
    return out


def build_kb(kb_spec: dict[str, Any]) -> KnowledgeBase:
    cards = [Card.model_validate(_with_prov(c)) for c in kb_spec.get("cards", [])]
    rules = [RewardRule.model_validate(_with_prov(r)) for r in kb_spec.get("reward_rules", [])]
    offers = [Offer.model_validate(_with_prov(o)) for o in kb_spec.get("offers", [])]
    vals = [
        PointValuation.model_validate(_with_prov(v)) for v in kb_spec.get("point_valuations", [])
    ]
    return KnowledgeBase.from_models(
        cards=cards, reward_rules=rules, offers=offers, point_valuations=vals
    )


def load_case(path: Path) -> dict[str, Any]:
    spec: dict[str, Any] = yaml.safe_load(path.read_text())
    kb = build_kb(spec["kb"])
    lines = [SpendLineItem.model_validate(line) for line in spec["lines"]]
    booking = spec.get("booking_date", "2026-07-24")
    trip_start = spec.get("trip_start_date", booking)
    trip = CostedTrip(
        booking_date=date.fromisoformat(str(booking)),
        trip_start_date=date.fromisoformat(str(trip_start)),
        lines=lines,
    )
    wallet = UserWallet(**spec["wallet"])
    prefs = OptimizationPrefs(**spec.get("prefs", {}))
    result = optimize(trip, wallet, kb, prefs)
    return {"name": spec["name"], "expect": spec["expect"], "result": result}
