"""Tests for CAR_RENTAL/DIRECT_CAR_RENTAL enums and pure core.perks valuation."""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

from core.models import (
    Channel,
    EarnRate,
    Provenance,
    RewardRule,
    SpendCategory,
    SpendLineItem,
)
from core.perks import (
    AirlineBagPerk,
    CardGrantedStatus,
    CardPerkProfile,
    RentalCarCardCandidate,
    RentalCarProtection,
    StatementCreditPerk,
    TripPerkItem,
    evaluate_rental_car_cards,
    evaluate_trip_perks,
    get_reference_perk_profile,
    reference_car_rental_programs,
    reference_card_perk_profiles,
)

TODAY = date(2026, 11, 27)


def _prov(*, verified: bool = False) -> Provenance:
    return Provenance(
        source_url="https://example.invalid/perks-test",
        source_type="manual_curation",
        last_verified=TODAY,
        verified_by="CURATOR_TEST" if verified else "UNVERIFIED",
        needs_verification=not verified,
        confidence=0.9 if verified else 0.5,
    )


def test_car_rental_enum_round_trip() -> None:
    assert SpendCategory.CAR_RENTAL.value == "car_rental"
    assert Channel.DIRECT_CAR_RENTAL.value == "direct_car_rental"

    line = SpendLineItem(
        id="rental:1",
        label="Midsize SUV 5 days",
        category=SpendCategory.CAR_RENTAL,
        amount_minor=40_000,
        currency="USD",
        available_channels=[Channel.DIRECT_CAR_RENTAL, Channel.OTA_GENERIC],
    )
    rule = RewardRule(
        id="rule-rental",
        card_id="card-1",
        description="3x on car rentals",
        earn=EarnRate(points=3, per_amount_minor=100, currency="USD"),
        categories=[SpendCategory.CAR_RENTAL],
        channels=[Channel.DIRECT_CAR_RENTAL],
        provenance=_prov(verified=True),
    )
    trip_item = TripPerkItem(
        id="item:1",
        card_id="card-1",
        category=SpendCategory.CAR_RENTAL,
        channel=Channel.DIRECT_CAR_RENTAL,
        amount_minor=40_000,
        currency="USD",
        rental_days=5,
        pickup_country="US",
    )

    assert SpendLineItem.model_validate_json(line.model_dump_json()) == line
    assert RewardRule.model_validate_json(rule.model_dump_json()) == rule
    assert TripPerkItem.model_validate_json(trip_item.model_dump_json()) == trip_item


def test_primary_cdw_beats_higher_points_card_and_respects_exclusions() -> None:
    # 5-day $400 USD rental in US:
    # Card A ("high-earn-secondary"): 5x points @ $0.01/pt = $20 (2000 minor), secondary CDW -> $0
    # Card B ("primary-cdw-card"): 2x @ $0.01/pt ($8) + $25/day * 5 ($125 CDW) -> $133
    secondary_profile = CardPerkProfile(
        card_id="high-earn-secondary",
        rental_protection=RentalCarProtection(
            card_id="high-earn-secondary",
            coverage_type="secondary_cdw",
            max_coverage_minor=5_000_000,
            currency="USD",
            max_rental_days=31,
            excluded_countries=[],
            requires_full_payment_on_card=True,
            counter_cdw_avoided_per_day_minor=2_500,
            provenance=_prov(verified=False),
        ),
    )
    primary_profile = CardPerkProfile(
        card_id="primary-cdw-card",
        rental_protection=RentalCarProtection(
            card_id="primary-cdw-card",
            coverage_type="primary_cdw",
            max_coverage_minor=7_500_000,
            currency="USD",
            max_rental_days=31,
            excluded_countries=["IE", "IL", "JM"],
            requires_full_payment_on_card=True,
            counter_cdw_avoided_per_day_minor=2_500,
            provenance=_prov(verified=False),
        ),
    )

    candidates = [
        RentalCarCardCandidate(
            card_id="high-earn-secondary",
            earn_rate=EarnRate(points=5, per_amount_minor=100, currency="USD"),
            point_value_micro=10_000,  # $0.01/pt = 10,000 micro-major
            perk_profile=secondary_profile,
        ),
        RentalCarCardCandidate(
            card_id="primary-cdw-card",
            earn_rate=EarnRate(points=2, per_amount_minor=100, currency="USD"),
            point_value_micro=10_000,
            perk_profile=primary_profile,
        ),
    ]

    us_res = evaluate_rental_car_cards(
        rental_cost_minor=40_000,
        rental_days=5,
        rental_currency="USD",
        pickup_country="US",
        home_currency="USD",
        fx_rates={},
        candidates=candidates,
    )
    assert us_res.recommended_card_id == "primary-cdw-card"
    by_id = {b.card_id: b for b in us_res.candidates}
    assert by_id["primary-cdw-card"].primary_cdw_applied is True
    assert by_id["primary-cdw-card"].primary_cdw_savings_minor == 12_500
    assert by_id["primary-cdw-card"].net_total_value_minor == 13_300
    assert by_id["high-earn-secondary"].primary_cdw_applied is False
    assert by_id["high-earn-secondary"].primary_cdw_savings_minor == 0
    assert by_id["high-earn-secondary"].cdw_disqualification_reason == "secondary_cdw_not_primary"
    assert any("Secondary CDW" in line for line in by_id["high-earn-secondary"].explanation)
    assert "rental_protection:primary-cdw-card:needs_verification" in us_res.provenance_warnings

    # Disqualified in excluded country (Ireland / IE): high-earn card wins on points alone
    ie_res = evaluate_rental_car_cards(
        rental_cost_minor=40_000,
        rental_days=5,
        rental_currency="USD",
        pickup_country="Ireland",
        home_currency="USD",
        fx_rates={},
        candidates=candidates,
    )
    assert ie_res.recommended_card_id == "high-earn-secondary"
    ie_by_id = {b.card_id: b for b in ie_res.candidates}
    assert ie_by_id["primary-cdw-card"].primary_cdw_applied is False
    assert ie_by_id["primary-cdw-card"].primary_cdw_savings_minor == 0
    assert ie_by_id["primary-cdw-card"].cdw_disqualification_reason == "excluded_country"

    # Disqualified when rental duration exceeds 31-day policy max
    long_res = evaluate_rental_car_cards(
        rental_cost_minor=240_000,
        rental_days=35,
        rental_currency="USD",
        pickup_country="US",
        home_currency="USD",
        fx_rates={},
        candidates=candidates,
    )
    assert long_res.recommended_card_id == "high-earn-secondary"
    long_by_id = {b.card_id: b for b in long_res.candidates}
    assert long_by_id["primary-cdw-card"].primary_cdw_applied is False
    assert long_by_id["primary-cdw-card"].cdw_disqualification_reason == "exceeds_max_rental_days"

    # Disqualified if rental is NOT paid in full on the card (e.g. points/split)
    split_candidates = [
        RentalCarCardCandidate(
            card_id="primary-cdw-card",
            paid_in_full_on_card=False,
            points_value_minor=0,
            perk_profile=primary_profile,
        )
    ]
    unpaid_res = evaluate_rental_car_cards(
        rental_cost_minor=40_000,
        rental_days=5,
        rental_currency="USD",
        pickup_country="US",
        home_currency="USD",
        fx_rates={},
        candidates=split_candidates,
    )
    assert unpaid_res.candidates[0].primary_cdw_applied is False
    assert (
        unpaid_res.candidates[0].cdw_disqualification_reason
        == "requires_full_payment_on_card"
    )


def test_trip_perks_enforces_credit_caps_and_values_status_and_bags() -> None:
    unverified = _prov(verified=False)
    profile = CardPerkProfile(
        card_id="travel-elite",
        rental_protection=RentalCarProtection(
            card_id="travel-elite",
            coverage_type="primary_cdw",
            max_coverage_minor=7_500_000,
            currency="USD",
            max_rental_days=31,
            excluded_countries=[],
            requires_full_payment_on_card=True,
            counter_cdw_avoided_per_day_minor=2_500,
            provenance=unverified,
        ),
        granted_statuses=[
            CardGrantedStatus(
                card_id="travel-elite",
                program_id="national-emerald",
                program_kind="car_rental",
                tier_name="Emerald Executive",
                estimated_value_per_event_minor=3_000,
                currency="USD",
                requires_enrollment=True,
                perks_summary=["Executive aisle upgrade"],
                provenance=unverified,
            ),
            CardGrantedStatus(
                card_id="travel-elite",
                program_id="hilton-honors",
                program_kind="hotel",
                tier_name="Hilton Gold",
                estimated_value_per_event_minor=4_000,
                currency="USD",
                requires_enrollment=True,
                perks_summary=["Breakfast & upgrade"],
                provenance=unverified,
            ),
        ],
        statement_credits=[
            StatementCreditPerk(
                id="annual-travel-300",
                card_id="travel-elite",
                description="$300 annual travel credit",
                categories=[SpendCategory.HOTELS, SpendCategory.CAR_RENTAL],
                channels=None,
                max_credit_minor=30_000,
                remaining_credit_minor=30_000,
                currency="USD",
                period="annual",
                provenance=unverified,
            )
        ],
        bag_perks=[
            AirlineBagPerk(
                card_id="travel-elite",
                airline_iata="UA",
                free_checked_bags=1,
                estimated_value_per_bag_minor=3_500,
                currency="USD",
                requires_payment_on_card=True,
                provenance=unverified,
            )
        ],
    )

    items = [
        TripPerkItem(
            id="hotel-1",
            card_id="travel-elite",
            category=SpendCategory.HOTELS,
            channel=Channel.DIRECT_HOTEL,
            amount_minor=22_000,  # uses $220 of $300 credit, $80 left
            currency="USD",
            hotel_program_id="hilton-honors",
            hotel_stays_count=1,
        ),
        TripPerkItem(
            id="rental-1",
            card_id="travel-elite",
            category=SpendCategory.CAR_RENTAL,
            channel=Channel.DIRECT_CAR_RENTAL,
            amount_minor=25_000,  # uses remaining $80 credit, NEVER $250
            currency="USD",
            rental_days=4,  # 4 * $25 = $100 CDW
            pickup_country="US",
            rental_program_id="national-emerald",
        ),
        TripPerkItem(
            id="flight-1",
            card_id="travel-elite",
            category=SpendCategory.FLIGHTS,
            channel=Channel.DIRECT_AIRLINE,
            amount_minor=50_000,
            currency="USD",
            airline_iata="UA",
            checked_bags_count=2,  # 1 bag covered = $35
        ),
    ]

    val = evaluate_trip_perks(items, {"travel-elite": profile}, {}, "USD")
    assert val.total_statement_credit_minor == 30_000
    assert val.remaining_credit_balances_minor["annual-travel-300"] == 0
    assert val.total_primary_cdw_savings_minor == 10_000
    assert val.total_status_perk_value_minor == 7_000  # 4000 hotel + 3000 rental
    assert val.total_bag_perk_value_minor == 3_500
    assert val.total_perks_value_minor == 50_500
    assert "statement_credit:annual-travel-300:needs_verification" in val.provenance_warnings
    assert "rental_protection:travel-elite:needs_verification" in val.provenance_warnings
    status_warn = "card_granted_status:travel-elite:hilton-honors:needs_verification"
    assert status_warn in val.provenance_warnings


def test_reference_perks_catalog_is_unverified_and_complete() -> None:
    programs = reference_car_rental_programs()
    assert {p.id for p in programs} == {
        "national-emerald",
        "hertz-gold",
        "avis-preferred",
        "sixt-status",
    }
    for prog in programs:
        assert prog.provenance.verified_by == "UNVERIFIED"
        assert prog.provenance.needs_verification is True

    profiles = reference_card_perk_profiles()
    assert "chase-sapphire-reserve-ref" in profiles
    assert "capital-one-venture-x-ref" in profiles
    assert "amex-platinum-ref" in profiles
    assert "hilton-aspire-ref" in profiles
    assert get_reference_perk_profile("chase-sapphire-reserve-ref") is not None


def test_core_perks_ast_isolation_and_no_float_money_math() -> None:
    perks_dir = Path(__file__).resolve().parent.parent / "core" / "perks"
    banned_modules = {"gateway", "agents", "api", "requests", "httpx", "socket", "mcp", "urllib"}

    for py_file in perks_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in banned_modules
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in banned_modules
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "float", f"float() forbidden in {py_file.name}"
            elif isinstance(node, ast.Constant) and isinstance(node.value, float):
                # Only non-money provenance confidence allowed inside reference_perks.py
                assert py_file.name == "reference_perks.py" and node.value == 0.5
