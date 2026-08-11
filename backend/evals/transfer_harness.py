from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from core.db import KnowledgeBase
from core.models import (
    AwardChartEntry,
    AwardTarget,
    FxRate,
    LoyaltyProgram,
    TransferBonus,
    TransferEdge,
    UserWallet,
)
from core.transfer import find_transfer_plans

GOLDEN_DIR = Path(__file__).parent / "golden"


def _prov(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("provenance") or {
        "source_type": "manual_curation",
        "last_verified": "2026-07-24",
        "verified_by": "UNVERIFIED",
        "needs_verification": True,
        "confidence": 1.0,
    }


def _as_date(value: object) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError(f"expected date or ISO date string, got {type(value).__name__}")


def run_transfer_case(case: dict[str, Any]):
    def with_prov(row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "provenance": _prov(row)}

    kb = KnowledgeBase.from_models(
        cards=[],
        reward_rules=[],
        offers=[],
        point_valuations=[],
        fx_rates=[FxRate.model_validate(with_prov(row)) for row in case.get("fx_rates", [])],
        loyalty_programs=[
            LoyaltyProgram.model_validate(with_prov(row)) for row in case.get("programs", [])
        ],
        transfer_edges=[
            TransferEdge.model_validate(with_prov(row)) for row in case.get("edges", [])
        ],
        transfer_bonuses=[
            TransferBonus.model_validate(with_prov(row)) for row in case.get("bonuses", [])
        ],
        award_chart_entries=[
            AwardChartEntry.model_validate(with_prov(row)) for row in case.get("awards", [])
        ],
    )
    return find_transfer_plans(
        target=AwardTarget.model_validate(case["target"]),
        wallet=UserWallet.model_validate(case["wallet"]),
        kb=kb,
        baseline_valuations=case["baseline_valuations"],
        cash_price_minor=case["cash_price_minor"],
        on_date=_as_date(case["on_date"]),
    )
