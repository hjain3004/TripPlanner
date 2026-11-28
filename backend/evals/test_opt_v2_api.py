"""API integration tests for Optimization Engine v2 (OPT-1, OPT-2, OPT-3, OPT-4)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.acquisition import router as _acq_router  # noqa: F401
from api.main import app
from api.opt_v2 import get_kb as get_opt_kb
from api.opt_v2 import get_opt_date
from api.welcome import get_as_of
from core.db import KnowledgeBase
from core.models import (
    AwardChartEntry,
    Card,
    Channel,
    EarnRate,
    FxRate,
    LoyaltyProgram,
    PointValuation,
    Provenance,
    RedemptionPath,
    RewardCap,
    RewardRule,
    SpendCategory,
    TransferEdge,
)
from core.optimizer.demo_data import demo_kb, demo_trip, demo_wallet
from evals.a4_support import csrf
from evals.welcome_support import (
    plan_and_save,
    request_acquisition_assessment,
    synthetic_offer,
    use_catalog,
)

AS_OF = date(2026, 10, 24)
TODAY = date(2026, 11, 27)


@pytest.fixture(autouse=True)
def _clean_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _prov(verified_by: str = "CURATOR_TEST") -> Provenance:
    return Provenance(
        source_url="https://example.invalid/opt-v2-api-test",
        source_type="manual_curation",
        last_verified=TODAY,
        verified_by=verified_by,
        needs_verification=False,
        confidence=0.95,
    )


def _pooling_kb() -> KnowledgeBase:
    p = _prov()
    return KnowledgeBase.from_models(
        cards=[],
        reward_rules=[],
        offers=[],
        point_valuations=[],
        fx_rates=[
            FxRate(
                base="USD",
                quote="INR",
                rate_micro=84_000_000,
                as_of=TODAY,
                provenance=p,
            )
        ],
        loyalty_programs=[
            LoyaltyProgram(id="chase-ur", kind="card_currency", name="Chase UR", provenance=p),
            LoyaltyProgram(id="amex-mr", kind="card_currency", name="Amex MR", provenance=p),
            LoyaltyProgram(
                id="avios",
                kind="airline",
                name="British Airways Avios",
                booking_url="https://example.invalid/avios",
                provenance=p,
            ),
        ],
        transfer_edges=[
            TransferEdge(
                id="E_CHASE_AVIOS",
                from_id="chase-ur",
                to_id="avios",
                ratio_from=1,
                ratio_to=1,
                min_transfer=1_000,
                increment=1_000,
                transfer_time_hours_typical=1,
                transfer_time_hours_max=4,
                provenance=p,
            ),
            TransferEdge(
                id="E_AMEX_AVIOS",
                from_id="amex-mr",
                to_id="avios",
                ratio_from=1,
                ratio_to=1,
                min_transfer=1_000,
                increment=1_000,
                transfer_time_hours_typical=12,
                transfer_time_hours_max=24,
                provenance=p,
            ),
        ],
        transfer_bonuses=[],
        award_chart_entries=[
            AwardChartEntry(
                id="AW_DEL_SIN_AVIOS",
                program_id="avios",
                origin="DEL",
                destination="SIN",
                cabin="business",
                trip_type="round_trip",
                miles_cost=50_000,
                fees_minor=500_000,
                fees_currency="INR",
                provenance=p,
            )
        ],
    )


def _milestone_and_robust_kb() -> KnowledgeBase:
    p = _prov()
    cards = [
        Card(
            id="card-high",
            issuer="BankA",
            network="visa",
            country="IN",
            name="High Variance Card",
            annual_fee_minor=0,
            fee_currency="INR",
            forex_markup_bp=0,
            forex_markup_tax_bp=0,
            base_earn=EarnRate(points=10, per_amount_minor=10_000, currency="INR"),
            provenance=p,
        ),
        Card(
            id="card-safe",
            issuer="BankB",
            network="mastercard",
            country="IN",
            name="Stable Floor Card",
            annual_fee_minor=0,
            fee_currency="INR",
            forex_markup_bp=0,
            forex_markup_tax_bp=0,
            base_earn=EarnRate(points=8, per_amount_minor=10_000, currency="INR"),
            provenance=p,
        ),
    ]
    vals = [
        PointValuation(
            id="v-high",
            card_id="card-high",
            path=RedemptionPath.TRANSFER_AIRLINE,
            value_micro_major_per_point=1_000_000,  # nominal ₹1.00/pt -> 10%
            currency="INR",
            provenance=p,
        ),
        PointValuation(
            id="v-safe",
            card_id="card-safe",
            path=RedemptionPath.CASHBACK,
            value_micro_major_per_point=900_000,  # nominal ₹0.90/pt -> 7.2%
            currency="INR",
            provenance=p,
        ),
    ]
    shared_cap = RewardRule(
        id="r-shared",
        card_id="card-high",
        description="Shared monthly portal cap",
        earn=EarnRate(points=20, per_amount_minor=10_000, currency="INR"),
        categories=[SpendCategory.HOTELS, SpendCategory.DINING],
        channels=[Channel.BANK_PORTAL, Channel.POS_DOMESTIC],
        cap=RewardCap(max_points=1_000, period="calendar_month", shared_cap_group="portal-shared"),
        provenance=p,
    )
    return KnowledgeBase.from_models(
        cards=cards,
        reward_rules=[shared_cap],
        offers=[],
        point_valuations=vals,
    )


# --------------------------------------------------------------------------- #
# OPT-1: Zero-Bias Top-m Acquisition Retrieval via Case B endpoint             #
# --------------------------------------------------------------------------- #


def test_opt1_acquisition_top_m_and_backwards_compatible_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, body, _entry_ids = plan_and_save(
        tmp_path, monkeypatch, cards=[("sbi-cashback", date(2026, 10, 1))]
    )
    trip_id = body["trip"]["id"]
    app.dependency_overrides[get_as_of] = lambda: AS_OF

    offers = [
        synthetic_offer(
            id="off-atlas",
            card_id="axis-atlas",
            bonus_points=None,
            bonus_currency_id=None,
            bonus_flat_minor=3_000_000,
            min_spend_minor=1_000_000,
            spend_window_days=90,
            expected_approval_days=5,
            expected_card_in_hand_days=5,
            annual_fee_minor=500_000,
        ),
        synthetic_offer(
            id="off-emeralde",
            card_id="icici-emeralde",
            bonus_points=None,
            bonus_currency_id=None,
            bonus_flat_minor=4_000_000,
            min_spend_minor=1_000_000,
            spend_window_days=90,
            expected_approval_days=5,
            expected_card_in_hand_days=5,
            annual_fee_minor=500_000,
        ),
    ]
    use_catalog(offers, as_of=AS_OF)

    pt = {"booking_date": "2026-10-24", "first_bookable_spend_date": "2026-11-20"}

    # 1. Backwards-compatible default (top_m omitted) returns all eligible candidates
    baseline = request_acquisition_assessment(client, trip_id, payment_timing=pt)
    assert baseline.status_code == 200, baseline.text
    assert len(baseline.json()["suggestions"]) == 2

    # 2. OPT-1 top_m=1 & home_country & closed_card_ids pass-through
    opt1_resp = client.post(
        f"/account/acquisition/trips/{trip_id}/revisions/1",
        headers=csrf(client),
        json={
            "payment_timing": pt,
            "top_m": 1,
            "home_country": "IN",
            "closed_card_ids": ["hdfc-infinia"],
        },
    )
    assert opt1_resp.status_code == 200, opt1_resp.text
    top1 = opt1_resp.json()["suggestions"]
    assert len(top1) == 1
    assert top1[0]["card_id"] == "icici-emeralde"


# --------------------------------------------------------------------------- #
# OPT-2: Multi-Currency Pooled Transfer Planning                              #
# --------------------------------------------------------------------------- #


def test_opt2_pooled_transfers_endpoint_combines_currencies_with_verify_step() -> None:
    app.dependency_overrides[get_opt_kb] = _pooling_kb
    app.dependency_overrides[get_opt_date] = lambda: TODAY
    client = TestClient(app)

    resp = client.post(
        "/opt/transfers/pooled",
        json={
            "target": {
                "origin": "DEL",
                "destination": "SIN",
                "cabin": "business",
                "trip_type": "round_trip",
                "travelers": 1,
                "home_currency": "INR",
            },
            "points_balances": {"chase-ur": 30_000, "amex-mr": 20_000},
            "baseline_valuations": {"chase-ur": 500_000, "amex-mr": 500_000},
            "cash_price_minor": 15_000_000,
            "on_date": TODAY.isoformat(),
            "pooling_config": {
                "deadline_hours": 48,
                "max_transfers": 3,
                "grouped_caps": [
                    {
                        "group_id": "group-chase",
                        "edge_ids": ["E_CHASE_AVIOS"],
                        "max_source_points": 30_000,
                    }
                ],
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recommendation"]["kind"] == "REDEEM"
    assert len(body["plans"]) >= 1
    plan = body["plans"][0]
    assert plan["points_consumed"] == 50_000
    assert len(plan["steps"]) == 2
    assert {s["from_id"] for s in plan["steps"]} == {"chase-ur", "amex-mr"}
    assert plan["checklist_steps"][0].startswith("VERIFY (blocking):")


# --------------------------------------------------------------------------- #
# OPT-3: Spend Milestones, Gamma-Robustness & Execution Order                 #
# --------------------------------------------------------------------------- #


def test_opt3_optimize_v2_milestones_and_gamma_robustness() -> None:
    app.dependency_overrides[get_opt_kb] = _milestone_and_robust_kb
    client = TestClient(app)

    trip = {
        "id": "t-opt3",
        "origin": "DEL",
        "destination": "SIN",
        "home_currency": "INR",
        "booking_date": TODAY.isoformat(),
        "trip_start_date": TODAY.isoformat(),
        "lines": [
            {
                "id": "hotel:1",
                "label": "Hotel",
                "category": "hotels",
                "amount_minor": 500_000,
                "currency": "INR",
                "available_channels": ["bank_portal"],
                "splittable": False,
            },
            {
                "id": "dining:1",
                "label": "Dining",
                "category": "dining",
                "amount_minor": 500_000,
                "currency": "INR",
                "available_channels": ["pos_domestic"],
                "splittable": False,
            },
        ],
    }
    wallet = {"card_ids": ["card-high", "card-safe"], "points_balances": {}}

    # 0. Frozen kernel mode when milestones=[] and gamma=0
    frozen_resp = client.post(
        "/opt/optimize-v2",
        json={"trip": trip, "wallet": wallet, "gamma": 0},
    )
    assert frozen_resp.status_code == 200, frozen_resp.text
    f_body = frozen_resp.json()
    assert f_body["mode"] == "kernel_frozen"
    assert f_body["status"] == "frozen_deterministic"
    assert f_body["optimizer_result"] is not None

    # 1. Fail closed (HTTP 422) when gamma > 0 omits valuation_floors_micro
    missing_floors = client.post(
        "/opt/optimize-v2",
        json={"trip": trip, "wallet": wallet, "gamma": 1},
    )
    assert missing_floors.status_code == 422

    # 2. Gamma = 1 with explicit downside floor favors stable card-safe over zero-floor card-high
    robust_resp = client.post(
        "/opt/optimize-v2",
        json={
            "trip": trip,
            "wallet": wallet,
            "gamma": 1,
            "valuation_floors_micro": {
                "card-high": 100_000,  # collapses to ₹0.10/pt under devaluation
                "card-safe": 850_000,  # resilient ₹0.85/pt floor
            },
        },
    )
    assert robust_resp.status_code == 200, robust_resp.text
    r_body = robust_resp.json()
    assert r_body["mode"] == "opt3_milp"
    assert r_body["status"] == "optimal"
    assert r_body["gamma"] == 1
    assert all(a["card_id"] == "card-safe" for a in r_body["assignments"])
    assert len(r_body["execution_order"]) == 2

    # 3. Milestone fee-waiver unlocks card-high when spend crosses threshold
    ms_resp = client.post(
        "/opt/optimize-v2",
        json={
            "trip": trip,
            "wallet": wallet,
            "milestones": [
                {
                    "card_id": "card-high",
                    "threshold_minor": 1_000_000,
                    "fee_waiver_minor": 200_000,
                    "eligible_categories": ["hotels", "dining"],
                    "period_type": "annual",
                    "prior_spend_minor": 0,
                    "provenance": _prov().model_dump(mode="json"),
                }
            ],
            "gamma": 0,
        },
    )
    assert ms_resp.status_code == 200, ms_resp.text
    m_body = ms_resp.json()
    assert m_body["mode"] == "opt3_milp"
    assert m_body["achieved_milestone_indices"] == [0]
    assert len(m_body["achieved_milestones"]) == 1


# --------------------------------------------------------------------------- #
# OPT-4: Always-On Counterfactuals, XAIOR Audit & QUICKXPLAIN Infeasibility   #
# --------------------------------------------------------------------------- #


def test_opt4_explain_audit_determinism_and_attestations() -> None:
    app.dependency_overrides[get_opt_kb] = demo_kb
    client = TestClient(app)

    payload: dict[str, Any] = {
        "trip": demo_trip().model_dump(mode="json"),
        "wallet": demo_wallet().model_dump(mode="json"),
        "milestones": [
            {
                "id": "waiver-4l",
                "card_id": "voyager-prime",
                "description": "Annual fee waiver",
                "threshold_minor": 40_000_000,
                "prior_spend_minor": 24_000_000,
                "reward_kind": "fee_waiver",
                "fee_waiver_minor": 1_000_000,
                "currency": "INR",
                "provenance": _prov().model_dump(mode="json"),
            }
        ],
    }

    r1 = client.post("/opt/explain-audit", json=payload)
    r2 = client.post("/opt/explain-audit", json=payload)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    b1 = r1.json()
    b2 = r2.json()

    assert b1 == b2
    cert = b1["audit_certificate"]
    assert len(cert["catalog_snapshot_hash"]) == 64
    assert len(cert["trip_snapshot_hash"]) == 64
    assert len(cert["result_hash"]) == 64
    assert cert["zero_affiliate_weight"] is True
    assert cert["zero_paid_promotion"] is True
    assert cert["revolver_apr_excluded"] is True
    assert "0% revolving APR" in cert["transactor_apr_warning"]

    exp = b1["explanation"]
    assert any(entry["binding"] for entry in exp["cap_ledger"])
    assert len(exp["milestone_deltas"]) == 1
    assert len(exp["valuation_breakevens"]) >= 1


def test_opt4_diagnose_infeasibility_returns_minimal_core_and_relaxation() -> None:
    app.dependency_overrides[get_opt_kb] = _pooling_kb
    app.dependency_overrides[get_opt_date] = lambda: TODAY
    client = TestClient(app)

    resp = client.post(
        "/opt/diagnose-infeasibility",
        json={
            "kind": "transfer",
            "target_program_id": "avios",
            "required_miles": 60_000,
            "wallet": {
                "card_ids": [],
                "points_balances": {"chase-ur": 30_000, "amex-mr": 20_000},
            },
            "on_date": TODAY.isoformat(),
            "max_transfer_hours": 24,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_feasible"] is False
    core_ids = {c["constraint_id"] for c in body["conflict_core"]}
    assert core_ids == {"goal:avios", "balance:chase-ur", "balance:amex-mr"}
    rel_by_id = {r["constraint_id"]: r for r in body["relaxations"]}
    assert rel_by_id["goal:avios"]["delta"] == 10_000
    assert rel_by_id["balance:chase-ur"]["delta"] == 10_000
    assert rel_by_id["balance:amex-mr"]["delta"] == 10_000

    # Milestone infeasibility branch via the same discriminated endpoint
    app.dependency_overrides[get_opt_kb] = demo_kb
    ms_resp = client.post(
        "/opt/diagnose-infeasibility",
        json={
            "kind": "milestone",
            "trip": demo_trip().model_dump(mode="json"),
            "wallet": demo_wallet().model_dump(mode="json"),
            "milestones": [
                {
                    "id": "impossible-vp",
                    "card_id": "voyager-prime",
                    "description": "High target",
                    "threshold_minor": 50_000_000,
                    "prior_spend_minor": 0,
                    "reward_kind": "fee_waiver",
                    "fee_waiver_minor": 1_000_000,
                    "currency": "INR",
                }
            ],
        },
    )
    assert ms_resp.status_code == 200, ms_resp.text
    ms_body = ms_resp.json()
    assert ms_body["is_feasible"] is False
    assert [c["constraint_id"] for c in ms_body["conflict_core"]] == [
        "milestone:voyager-prime:impossible-vp"
    ]
