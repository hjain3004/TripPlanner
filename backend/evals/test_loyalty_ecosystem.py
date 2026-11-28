"""Comprehensive tests for pure deterministic backend/core/loyalty/ ecosystem bridge."""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from typing import Protocol

import pytest

from core.db import SEEDS_DIR, KnowledgeBase, load_kb, seed_database
from core.loyalty import (
    compare_direct_vs_ota_hotel,
    compute_hotel_award_stay_points,
    default_hotel_brand_rules,
    find_partner_booking_programs,
    hotel_award_stay_rule_for_program,
    load_loyalty_overlay_kb,
    load_loyalty_reference_catalog,
    match_hotel_brand,
)
from core.loyalty.contracts import HotelAwardStayRule
from core.models import (
    AwardChartEntry,
    AwardTarget,
    FxRate,
    Provenance,
    RecommendationKind,
    UserWallet,
)
from core.transfer.pathfinder import find_transfer_plans
from core.transfer.pooling import PoolingConfig, solve_pooled_transfer

LOYALTY_DIR = Path(__file__).resolve().parent.parent / "core" / "loyalty"
BOOKING_DATE = date(2026, 11, 27)
PROV = Provenance(
    source_type="manual_curation",
    last_verified=BOOKING_DATE,
    verified_by="UNVERIFIED",
    needs_verification=True,
    confidence=0.8,
)


@pytest.mark.parametrize(
    ("property_name", "expected_chain_id", "expected_program_id", "expected_brand"),
    [
        (
            "JW Marriott Hotel Singapore South Beach",
            "marriott_bonvoy",
            "marriott-bonvoy",
            "JW Marriott",
        ),
        (
            "The Ritz-Carlton, Millenia Singapore",
            "marriott_bonvoy",
            "marriott-bonvoy",
            "The Ritz-Carlton",
        ),
        ("The St. Regis Singapore", "marriott_bonvoy", "marriott-bonvoy", "St. Regis"),
        ("W Singapore - Sentosa Cove", "marriott_bonvoy", "marriott-bonvoy", "W Singapore"),
        ("W Hotels Times Square", "marriott_bonvoy", "marriott-bonvoy", "W Hotels"),
        ("The Westin Singapore", "marriott_bonvoy", "marriott-bonvoy", "Westin"),
        ("Sheraton Towers Singapore", "marriott_bonvoy", "marriott-bonvoy", "Sheraton"),
        ("Le Méridien Kuala Lumpur", "marriott_bonvoy", "marriott-bonvoy", "Le Méridien"),
        (
            "Courtyard by Marriott Singapore Novena",
            "marriott_bonvoy",
            "marriott-bonvoy",
            "Courtyard by Marriott",
        ),
        (
            "Fairfield by Marriott Bali",
            "marriott_bonvoy",
            "marriott-bonvoy",
            "Fairfield by Marriott",
        ),
        ("Residence Inn Manhattan Midtown", "marriott_bonvoy", "marriott-bonvoy", "Residence Inn"),
        ("Aloft Singapore Novena", "marriott_bonvoy", "marriott-bonvoy", "Aloft"),
        ("Moxy Tokyo Kinshicho", "marriott_bonvoy", "marriott-bonvoy", "Moxy"),
        ("The Singapore EDITION", "marriott_bonvoy", "marriott-bonvoy", "EDITION"),
        (
            "Duxton Reserve Singapore, Autograph Collection",
            "marriott_bonvoy",
            "marriott-bonvoy",
            "Autograph Collection",
        ),
        (
            "The Murray, Tribute Portfolio Hotel",
            "marriott_bonvoy",
            "marriott-bonvoy",
            "Tribute Portfolio",
        ),
        (
            "The Vagabond Club, The Luxury Collection",
            "marriott_bonvoy",
            "marriott-bonvoy",
            "The Luxury Collection",
        ),
        (
            "Four Points by Sheraton Singapore, Riverview",
            "marriott_bonvoy",
            "marriott-bonvoy",
            "Four Points by Sheraton",
        ),
        (
            "Renaissance Mumbai Convention Centre Hotel",
            "marriott_bonvoy",
            "marriott-bonvoy",
            "Renaissance Hotel",
        ),
        ("Park Hyatt Kyoto", "world_of_hyatt", "world-of-hyatt", "Park Hyatt"),
        ("Grand Hyatt Singapore", "world_of_hyatt", "world-of-hyatt", "Grand Hyatt"),
        ("Andaz Singapore", "world_of_hyatt", "world-of-hyatt", "Andaz"),
        ("Alila Villas Uluwatu", "world_of_hyatt", "world-of-hyatt", "Alila"),
        ("Thompson Hotel Austin", "world_of_hyatt", "world-of-hyatt", "Thompson Hotel"),
        ("Hyatt Regency Delhi", "world_of_hyatt", "world-of-hyatt", "Hyatt Regency"),
        ("Hyatt Place Dubai", "world_of_hyatt", "world-of-hyatt", "Hyatt Place"),
        ("Hyatt House Dallas", "world_of_hyatt", "world-of-hyatt", "Hyatt House"),
        ("Miraval Arizona Resort & Spa", "world_of_hyatt", "world-of-hyatt", "Miraval"),
        ("Caption by Hyatt Namba Osaka", "world_of_hyatt", "world-of-hyatt", "Caption by Hyatt"),
        ("Waldorf Astoria Bangkok", "hilton_honors", "hilton-honors", "Waldorf Astoria"),
        ("Conrad Singapore Marina Bay", "hilton_honors", "hilton-honors", "Conrad"),
        (
            "The Biltmore Mayfair, LXR Hotels & Resorts",
            "hilton_honors",
            "hilton-honors",
            "LXR Hotels",
        ),
        (
            "Canopy by Hilton Madrid Castellana",
            "hilton_honors",
            "hilton-honors",
            "Canopy by Hilton",
        ),
        ("Curio Collection by Hilton London", "hilton_honors", "hilton-honors", "Curio Collection"),
        ("DoubleTree by Hilton Agra", "hilton_honors", "hilton-honors", "DoubleTree by Hilton"),
        ("Embassy Suites Chicago Downtown", "hilton_honors", "hilton-honors", "Embassy Suites"),
        ("Hampton Inn & Suites Seattle", "hilton_honors", "hilton-honors", "Hampton Inn"),
        (
            "Hilton Garden Inn Singapore Serangoon",
            "hilton_honors",
            "hilton-honors",
            "Hilton Garden Inn",
        ),
        ("Homewood Suites Boston", "hilton_honors", "hilton-honors", "Homewood Suites"),
        (
            "Tapestry Collection Hotel Austin",
            "hilton_honors",
            "hilton-honors",
            "Tapestry Collection",
        ),
        ("Tru by Hilton Orlando", "hilton_honors", "hilton-honors", "Tru by Hilton"),
        ("Tempo by Hilton Times Square", "hilton_honors", "hilton-honors", "Tempo by Hilton"),
        ("InterContinental Singapore", "ihg_one_rewards", "ihg-one-rewards", "InterContinental"),
        ("Six Senses Fort Barwara", "ihg_one_rewards", "ihg-one-rewards", "Six Senses"),
        ("Regent Singapore", "ihg_one_rewards", "ihg-one-rewards", "Regent Singapore"),
        ("Kimpton Maa-Lai Bangkok", "ihg_one_rewards", "ihg-one-rewards", "Kimpton"),
        ("Hotel Indigo Singapore Katong", "ihg_one_rewards", "ihg-one-rewards", "Hotel Indigo"),
        ("Crowne Plaza Changi Airport", "ihg_one_rewards", "ihg-one-rewards", "Crowne Plaza"),
        (
            "Holiday Inn Express Singapore Clarke Quay",
            "ihg_one_rewards",
            "ihg-one-rewards",
            "Holiday Inn Express",
        ),
        ("Staybridge Suites London", "ihg_one_rewards", "ihg-one-rewards", "Staybridge Suites"),
        ("voco Orchard Singapore", "ihg_one_rewards", "ihg-one-rewards", "voco"),
        ("EVEN Hotels New York", "ihg_one_rewards", "ihg-one-rewards", "EVEN Hotels"),
        ("Raffles Singapore", "accor_all", "accor-all", "Raffles"),
        ("Fairmont Singapore", "accor_all", "accor-all", "Fairmont"),
        ("Sofitel Singapore City Centre", "accor_all", "accor-all", "Sofitel"),
        ("Pullman Singapore Hill Street", "accor_all", "accor-all", "Pullman"),
        ("Swissôtel The Stamford Singapore", "accor_all", "accor-all", "Swissôtel"),
        ("Mövenpick Heritage Hotel Sentosa", "accor_all", "accor-all", "Mövenpick"),
        ("Novotel Singapore on Stevens", "accor_all", "accor-all", "Novotel"),
        ("Mercure Singapore Bugis", "accor_all", "accor-all", "Mercure"),
        ("ibis Styles Singapore Albert", "accor_all", "accor-all", "ibis Styles"),
        ("Banyan Tree Bangkok", "accor_all", "accor-all", "Banyan Tree"),
        ("Hotel Fort Canning - MGallery Collection", "accor_all", "accor-all", "MGallery"),
        ("Shangri-La Singapore", "shangri_la_circle", "shangri-la-circle", "Shangri-La"),
        ("Pan Pacific Singapore", "gha_discovery", "gha-discovery", "Pan Pacific"),
        (
            "PARKROYAL COLLECTION Marina Bay",
            "gha_discovery",
            "gha-discovery",
            "PARKROYAL COLLECTION",
        ),
        ("Capitol Kempinski Hotel Singapore", "gha_discovery", "gha-discovery", "Kempinski"),
        ("Anantara Siam Bangkok Hotel", "gha_discovery", "gha-discovery", "Anantara"),
        (
            "The Taj Mahal Palace, Mumbai",
            "taj_innercircle",
            "taj-innercircle",
            "The Taj Mahal Palace",
        ),
        ("Vivanta Bengaluru Whitefield", "taj_innercircle", "taj-innercircle", "Vivanta"),
        ("ITC Grand Chola, Chennai", "club_itc", "club-itc", "ITC Grand"),
        ("Welcomhotel by ITC Bengaluru", "club_itc", "club-itc", "Welcomhotel"),
        ("Wyndham Grand Phuket Kalim Bay", "wyndham_rewards", "wyndham-rewards", "Wyndham Grand"),
        ("Ramada Encore by Wyndham Bali", "wyndham_rewards", "wyndham-rewards", "Ramada Encore"),
        ("Comfort Inn Manhattan", "choice_privileges", "choice-privileges", "Comfort Inn"),
        (
            "Radisson Blu Plaza Delhi Airport",
            "radisson_rewards",
            "radisson-rewards",
            "Radisson Blu",
        ),
    ],
)
def test_hotel_brand_matcher_positive_coverage(
    property_name: str,
    expected_chain_id: str,
    expected_program_id: str,
    expected_brand: str,
) -> None:
    match = match_hotel_brand(property_name)
    assert match is not None
    assert match.chain_id == expected_chain_id
    assert match.program_id == expected_program_id
    assert match.matched_brand == expected_brand
    assert match.provenance.needs_verification is True
    assert match.provenance.verified_by == "UNVERIFIED"


@pytest.mark.parametrize(
    "independent_name",
    [
        "",
        "Grand Hotel Independent",
        "Park View Inn",
        "WXYZ Hostel",
        "Limited Edition Boutique",
        "W Street Hostel Singapore",
        "Regent View Inn",
        "Evening Star Hostel",
        "Crown Plaza Independent",
        "Parkway Guesthouse",
        "Taj View Homestay Agra",
        "Taj Mahal View Guest House",
        "Raffles Place Boutique Hostel",
        "Hotel A to W",
        "The Boutique Fullerton Heritage Stay",
    ],
)
def test_hotel_brand_matcher_rejects_generic_false_positives(independent_name: str) -> None:
    assert match_hotel_brand(independent_name) is None


def test_hotel_brand_matcher_tokyo_edition_ginza_and_contextual_priority() -> None:
    ed1 = match_hotel_brand("The Tokyo EDITION, Ginza")
    assert ed1 is not None
    assert ed1.chain_id == "marriott_bonvoy"
    assert ed1.matched_brand == "EDITION"

    ed2 = match_hotel_brand("The Singapore EDITION by Marriott")
    assert ed2 is not None
    assert ed2.chain_id == "marriott_bonvoy"
    assert ed2.matched_brand == "EDITION"


def test_hotel_award_stay_fifth_and_fourth_night_free_math() -> None:
    marriott_rule = hotel_award_stay_rule_for_program("marriott-bonvoy")
    hilton_rule = hotel_award_stay_rule_for_program("hilton-honors")
    ihg_rule = hotel_award_stay_rule_for_program("ihg-one-rewards")
    hyatt_rule = hotel_award_stay_rule_for_program("world-of-hyatt")
    assert marriott_rule and hilton_rule and ihg_rule and hyatt_rule

    # 3 nights & 4 nights (<5): zero free nights for 5th-night-free.
    for count in (3, 4):
        calc = compute_hotel_award_stay_points([50_000] * count, marriott_rule, True)
        assert calc.free_nights_count == 0
        assert calc.points_saved == 0
        assert calc.net_points == 50_000 * count

    # 5 nights varying pricing: lowest night in block (40,000 at index 1) waived.
    five = compute_hotel_award_stay_points(
        [50_000, 40_000, 60_000, 45_000, 55_000], marriott_rule, True
    )
    assert five.free_nights_count == 1
    assert five.free_night_indices == (1,)
    assert five.points_saved == 40_000
    assert five.net_points == 210_000

    # 8 nights under Hilton (eligible vs ineligible).
    eight_eligible = compute_hotel_award_stay_points(
        [50_000, 40_000, 60_000, 45_000, 55_000, 70_000, 65_000, 60_000], hilton_rule, True
    )
    assert eight_eligible.free_nights_count == 1
    assert eight_eligible.points_saved == 40_000
    assert eight_eligible.net_points == 405_000

    eight_ineligible = compute_hotel_award_stay_points(
        [50_000, 40_000, 60_000, 45_000, 55_000, 70_000, 65_000, 60_000], hilton_rule, False
    )
    assert eight_ineligible.free_nights_count == 0
    assert eight_ineligible.net_points == 445_000

    # 10 nights Marriott: two 5-night blocks waive two cheapest nights (indices 1 and 8).
    ten = compute_hotel_award_stay_points(
        [50_000, 40_000, 60_000, 45_000, 55_000, 70_000, 65_000, 60_000, 35_000, 75_000],
        marriott_rule,
        True,
    )
    assert ten.free_nights_count == 2
    assert ten.free_night_indices == (1, 8)
    assert ten.points_saved == 75_000
    assert ten.net_points == 480_000

    # 8 nights IHG co-branded card 4th-night-free waives indices 3 and 7.
    ihg_eight = compute_hotel_award_stay_points(
        [30_000, 32_000, 34_000, 36_000, 40_000, 42_000, 44_000, 46_000], ihg_rule, True
    )
    assert ihg_eight.free_nights_count == 2
    assert ihg_eight.free_night_indices == (3, 7)
    assert ihg_eight.points_saved == 36_000 + 46_000
    assert ihg_eight.net_points == 222_000

    # Hyatt has no Nth-night-free rule.
    hyatt_five = compute_hotel_award_stay_points([25_000] * 5, hyatt_rule, True)
    assert hyatt_five.free_nights_count == 0
    assert hyatt_five.net_points == 125_000

    # Defensive input check.
    bad_rule = HotelAwardStayRule(program_id="test", free_night_every_n=4, provenance=PROV)
    with pytest.raises(ValueError):
        compute_hotel_award_stay_points([10_000, -1, 10_000, 10_000], bad_rule, True)


def test_compare_direct_vs_ota_hotel_both_directions() -> None:
    rules_by_id = {rule.chain_id: rule for rule in default_hotel_brand_rules()}
    hyatt_rule = rules_by_id["world_of_hyatt"]
    marriott_rule = rules_by_id["marriott_bonvoy"]

    # Case A: Direct ($400) beats 10x portal ($400, +$28 card delta) with Hyatt perks/points.
    direct_wins = compare_direct_vs_ota_hotel(
        direct_cash_minor=40_000,
        ota_cash_minor=40_000,
        currency="USD",
        chain_rule=hyatt_rule,
        ota_card_bonus_delta_minor=2_800,
        elite_bonus_bp=3_000,  # +30% Globalist bonus -> 2,600 pts on $400
        hotel_point_value_micro_major=17_000,  # $0.017/pt -> $44.20 (4,420 cents)
        status_perks_value_minor=6_000,  # $60 breakfast + late checkout
    )
    assert direct_wins.recommendation == "BOOK_DIRECT"
    assert direct_wins.direct_loyalty_points_earned == 2_600
    assert direct_wins.direct_loyalty_value_minor == 4_420
    assert direct_wins.forfeited_loyalty_value_minor == 10_420
    assert direct_wins.net_direct_advantage_minor == 7_620
    assert any("needs_verification" in w for w in direct_wins.provenance_warnings)

    # Case B: Deep OTA discount on INR stay beats forfeited base points for non-elite guest.
    ota_wins = compare_direct_vs_ota_hotel(
        direct_cash_minor=3_200_000,  # INR 32,000
        ota_cash_minor=2_400_000,  # INR 24,000 (INR 8,000 cheaper)
        currency="INR",
        chain_rule=marriott_rule,
        fx_usd_to_booking_currency_micro=80_000_000,  # 80 INR/USD -> $400 -> 4,000 Marriott pts
        hotel_point_value_micro_major=500_000,  # INR 0.50/pt -> INR 2,000 (200,000 paise)
        status_perks_value_minor=0,
    )
    assert ota_wins.recommendation == "BOOK_OTA"
    assert ota_wins.direct_loyalty_points_earned == 4_000
    assert ota_wins.direct_loyalty_value_minor == 200_000
    assert ota_wins.net_direct_advantage_minor == -600_000

    # Non-USD without FX rate fails closed cleanly, as do bool inputs & zero-decimal JPY precision.
    with pytest.raises(ValueError, match="fx_usd_to_booking_currency_micro"):
        compare_direct_vs_ota_hotel(
            direct_cash_minor=1_000_000,
            ota_cash_minor=1_000_000,
            currency="SGD",
            chain_rule=marriott_rule,
        )
    with pytest.raises(ValueError, match="integer"):
        compare_direct_vs_ota_hotel(
            direct_cash_minor=True,
            ota_cash_minor=10_000,
            currency="USD",
        )
    jpy_cmp = compare_direct_vs_ota_hotel(
        direct_cash_minor=15_000,  # 15,000 JPY = $100 at 150 JPY/USD
        ota_cash_minor=15_000,
        currency="JPY",
        chain_rule=marriott_rule,
        fx_usd_to_booking_currency_micro=150_000_000,
        hotel_point_value_micro_major=1_000_000,  # 1 JPY/pt -> 1,000 JPY
    )
    assert jpy_cmp.direct_loyalty_points_earned == 1_000
    assert jpy_cmp.direct_loyalty_value_minor == 1_000
    assert jpy_cmp.recommendation == "BOOK_DIRECT"


def test_partner_award_lookup_covers_alliances_and_bilaterals() -> None:
    sq_partners = find_partner_booking_programs(" sq ")
    sq_programs = {edge.booking_program_id for edge in sq_partners}
    assert {
        "krisflyer",
        "aeroplan",
        "united-mileageplus",
        "avianca-lifemiles",
        "virgin-australia",
    }.issubset(sq_programs)

    ek_partners = find_partner_booking_programs("EK")
    assert {e.booking_program_id for e in ek_partners} == {
        "aeroplan",
        "emirates-skywards",
        "qantas-ff",
    }

    nh_partners = find_partner_booking_programs("NH")
    assert "virgin-atlantic" in {e.booking_program_id for e in nh_partners}
    qr_partners = find_partner_booking_programs("QR")
    assert {"qatar-avios", "ba-avios", "cathay-asia-miles"}.issubset(
        {e.booking_program_id for e in qr_partners}
    )


def test_reference_catalog_unverified_and_overlay_works_with_opt2_pooling(tmp_path: Path) -> None:
    catalog = load_loyalty_reference_catalog()
    prog_ids = {p.id for p in catalog.programs}
    expected_programs = {
        "krisflyer",
        "aeroplan",
        "united-mileageplus",
        "ba-avios",
        "qatar-avios",
        "flying-blue",
        "virgin-atlantic",
        "emirates-skywards",
        "turkish-miles-smiles",
        "cathay-asia-miles",
        "ana-mileage-club",
        "jal-mileage-bank",
        "maharaja-club",
        "marriott-bonvoy",
        "world-of-hyatt",
        "hilton-honors",
        "ihg-one-rewards",
        "accor-all",
        "chase-ur",
        "amex-mr-us",
        "capital-one-miles",
        "citi-typ",
        "bilt-rewards",
        "hdfc-infinia",
        "axis-magnus",
        "axis-atlas",
        "amex-mr-in",
        "emirates-nbd",
        "adcb-touchpoints",
        "fab-rewards",
    }
    assert expected_programs.issubset(prog_ids)

    class _HasProvenance(Protocol):
        @property
        def provenance(self) -> Provenance: ...

    all_entries: tuple[_HasProvenance, ...] = (
        *catalog.programs,
        *catalog.transfer_edges,
        *catalog.hotel_brand_rules,
        *catalog.hotel_award_stay_rules,
        *catalog.alliance_partner_edges,
    )
    for item in all_entries:
        assert item.provenance.verified_by == "UNVERIFIED"
        assert item.provenance.needs_verification is True

    db_path = tmp_path / "tripwise.sqlite"
    seed_database(SEEDS_DIR, db_path)
    base_kb = load_kb(db_path)
    base_programs_before = [p.id for p in base_kb.programs()]
    base_edges_before = [e.id for e in base_kb._transfer_edges]

    overlay_kb = load_loyalty_overlay_kb(base_kb)
    # base_kb remains completely unmodified.
    assert [p.id for p in base_kb.programs()] == base_programs_before
    assert [e.id for e in base_kb._transfer_edges] == base_edges_before
    assert "aeroplan" not in {p.id for p in base_kb.programs()}
    assert "aeroplan" in {p.id for p in overlay_kb.programs()}

    # Inject a USD->INR FX rate + ephemeral SFO->SIN Aeroplan award onto a second in-memory KB
    # and verify end-to-end OPT-2 pooled transfer across Chase UR + Amex MR US!
    award = AwardChartEntry(
        id="live-sfo-sin-aeroplan-biz",
        program_id="aeroplan",
        origin="SFO",
        destination="SIN",
        cabin="business",
        trip_type="one_way",
        miles_cost=75_000,
        fees_minor=6_500,  # $65 USD
        fees_currency="USD",
        provenance=PROV,
    )
    kb_with_award = KnowledgeBase.from_models(
        cards=overlay_kb.cards(),
        reward_rules=overlay_kb.rules_for_cards([c.id for c in overlay_kb.cards()]),
        offers=list(overlay_kb._offers),
        point_valuations=[
            val
            for cid in (c.id for c in overlay_kb.cards())
            for val in overlay_kb.valuations_for_card(cid)
        ],
        fx_rates=[
            *overlay_kb._fx.values(),
            FxRate(base="INR", quote="USD", rate_micro=12_000, as_of=BOOKING_DATE, provenance=PROV),
        ],
        loyalty_programs=overlay_kb.programs(),
        transfer_edges=list(overlay_kb._transfer_edges),
        award_chart_entries=[award],
    )
    wallet = UserWallet(
        card_ids=[],
        points_balances={"chase-ur": 40_000, "amex-mr-us": 35_000},
    )
    baselines = {"chase-ur": 15_000, "amex-mr-us": 15_000}  # $0.015/pt

    pooled = solve_pooled_transfer(
        award=award,
        target=AwardTarget(
            origin="SFO",
            destination="SIN",
            cabin="business",
            trip_type="one_way",
            travelers=1,
            home_currency="USD",
        ),
        program=kb_with_award.program("aeroplan"),
        wallet=wallet,
        edges=kb_with_award.edges_from(["chase-ur", "amex-mr-us"]),
        bonuses=[],
        baseline_valuations=baselines,
        award_total_fees_minor=6_500,
        cash_price_minor=350_000,  # $3,500 USD
        config=PoolingConfig(),
    )
    assert pooled is not None
    assert pooled.consumed_by_currency == {"amex-mr-us": 35_000, "chase-ur": 40_000}
    assert pooled.plan.points_consumed == 75_000
    assert pooled.plan.checklist_steps[0].startswith("VERIFY (blocking):")

    advice = find_transfer_plans(
        AwardTarget(
            origin="SFO",
            destination="SIN",
            cabin="business",
            trip_type="one_way",
            travelers=1,
            home_currency="USD",
        ),
        wallet,
        kb_with_award,
        baselines,
        350_000,
        BOOKING_DATE,
        allow_pooling=True,
    )
    assert advice.recommendation.kind == RecommendationKind.REDEEM
    assert advice.plans[0].checklist_steps[0].startswith("VERIFY (blocking):")


def test_core_loyalty_ast_isolation_and_no_float_money_math() -> None:
    forbidden_prefixes = (
        "gateway",
        "api",
        "agents",
        "accounts",
        "ingestion",
        "planning",
        "welcome",
        "socket",
        "subprocess",
        "urllib",
        "http",
        "httpx",
        "requests",
        "asyncio",
    )
    for py_path in sorted(LOYALTY_DIR.glob("*.py")):
        tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not any(
                        alias.name == prefix or alias.name.startswith(f"{prefix}.")
                        for prefix in forbidden_prefixes
                    ), f"Forbidden import {alias.name} in {py_path.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not any(
                    node.module == prefix or node.module.startswith(f"{prefix}.")
                    for prefix in forbidden_prefixes
                ), f"Forbidden import {node.module} in {py_path.name}"

        if py_path.name in {"award_rules.py", "catalog_loader.py"}:
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    assert node.func.id != "float", f"float() forbidden in {py_path.name}"
                elif isinstance(node, ast.Constant) and isinstance(node.value, float):
                    raise AssertionError(
                        f"Unexpected float literal {node.value!r} in {py_path.name}"
                    )
