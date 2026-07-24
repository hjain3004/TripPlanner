"""The canonical worked example from spec 02 §8 as in-memory models.

Fictional cards so the math is self-contained. This is the single Python source
for `python -m core.optimizer demo`; the golden fixture
``evals/golden/demo_trip.yaml`` mirrors it verbatim for the parametrized tests.
"""

from __future__ import annotations

from datetime import date

from core.db import KnowledgeBase
from core.models import (
    Card,
    Channel,
    CostedTrip,
    EarnRate,
    Offer,
    OfferKind,
    PointValuation,
    Provenance,
    RedemptionPath,
    RewardCap,
    RewardRule,
    SpendCategory,
    SpendLineItem,
    UserWallet,
)

_PROV = Provenance(
    source_type="manual_curation",
    last_verified=date(2026, 7, 7),
    verified_by="UNVERIFIED",
    needs_verification=True,
    confidence=0.5,
    notes="fictional worked-example card (spec 02 §8)",
)


def _cards() -> list[Card]:
    return [
        Card(
            id="voyager-prime",
            issuer="Voyager Bank",
            network="visa",
            country="IN",
            name="Voyager Prime",
            annual_fee_minor=0,
            fee_currency="INR",
            forex_markup_bp=350,
            forex_markup_tax_bp=1800,
            base_earn=EarnRate(points=2, per_amount_minor=10000, currency="INR"),
            provenance=_PROV,
        ),
        Card(
            id="globesaver",
            issuer="Globe Bank",
            network="mastercard",
            country="IN",
            name="Globesaver",
            annual_fee_minor=0,
            fee_currency="INR",
            forex_markup_bp=100,
            forex_markup_tax_bp=1800,
            base_earn=EarnRate(points=1, per_amount_minor=10000, currency="INR"),
            provenance=_PROV,
        ),
    ]


def _rules() -> list[RewardRule]:
    return [
        RewardRule(
            id="R1",
            card_id="voyager-prime",
            description="10 pts per Rs100 on flights & hotels via bank portal (shared cap)",
            earn=EarnRate(points=10, per_amount_minor=10000, currency="INR"),
            categories=[SpendCategory.FLIGHTS, SpendCategory.HOTELS],
            channels=[Channel.BANK_PORTAL],
            cap=RewardCap(max_points=4000, period="statement_cycle", shared_cap_group="portal"),
            provenance=_PROV,
        ),
        RewardRule(
            id="R2",
            card_id="globesaver",
            description="5 pts per Rs100 on dining & general forex (any channel)",
            earn=EarnRate(points=5, per_amount_minor=10000, currency="INR"),
            categories=[SpendCategory.DINING, SpendCategory.FOREX_GENERAL],
            cap=RewardCap(max_points=2500, period="calendar_month"),
            provenance=_PROV,
        ),
    ]


def _valuations() -> list[PointValuation]:
    return [
        PointValuation(
            id="voyager-portal-val",
            card_id="voyager-prime",
            path=RedemptionPath.PORTAL_FLIGHTS,
            value_micro_major_per_point=1_000_000,  # Rs1.00/pt
            currency="INR",
            provenance=_PROV,
        ),
        PointValuation(
            id="globesaver-cashback-val",
            card_id="globesaver",
            path=RedemptionPath.CASHBACK,
            value_micro_major_per_point=500_000,  # Rs0.50/pt
            currency="INR",
            provenance=_PROV,
        ),
    ]


def _offers() -> list[Offer]:
    return [
        Offer(
            id="O1",
            title="10% instant off Agoda hotels",
            kind=OfferKind.INSTANT_DISCOUNT,
            card_ids=["globesaver"],
            merchant="Agoda",
            channels=[Channel.OTA_GENERIC],
            categories=[SpendCategory.HOTELS],
            discount_bp=1000,
            max_discount_minor=300000,
            min_txn_minor=1500000,
            currency="INR",
            valid_to=date(2026, 12, 31),
            stacking_class="bank_offer",
            provenance=_PROV,
        ),
        Offer(
            id="O2",
            title="5% instant off Klook",
            kind=OfferKind.INSTANT_DISCOUNT,
            networks=["visa"],
            merchant="Klook",
            channels=[Channel.OTA_GENERIC],
            categories=[SpendCategory.ATTRACTIONS],
            discount_bp=500,
            max_discount_minor=50000,
            currency="INR",
            valid_to=date(2026, 12, 31),
            stacking_class="bank_offer",
            provenance=_PROV,
        ),
    ]


def demo_kb() -> KnowledgeBase:
    return KnowledgeBase.from_models(
        cards=_cards(),
        reward_rules=_rules(),
        offers=_offers(),
        point_valuations=_valuations(),
    )


def demo_trip() -> CostedTrip:
    return CostedTrip(
        id="demo-del-sin",
        origin="DEL",
        destination="SIN",
        home_currency="INR",
        booking_date=date(2026, 7, 24),
        trip_start_date=date(2026, 8, 15),
        lines=[
            SpendLineItem(
                id="flights",
                label="Round-trip flights DEL->SIN x2",
                category=SpendCategory.FLIGHTS,
                amount_minor=5600000,
                currency="INR",
                available_channels=[
                    Channel.DIRECT_AIRLINE,
                    Channel.OTA_GENERIC,
                    Channel.BANK_PORTAL,
                ],
            ),
            SpendLineItem(
                id="hotel",
                label="Hotel 4 nights (Agoda)",
                category=SpendCategory.HOTELS,
                amount_minor=4800000,
                currency="INR",
                available_channels=[
                    Channel.OTA_GENERIC,
                    Channel.BANK_PORTAL,
                    Channel.DIRECT_HOTEL,
                ],
                merchant_hint="Agoda",
            ),
            SpendLineItem(
                id="attractions",
                label="Attractions basket (Klook)",
                category=SpendCategory.ATTRACTIONS,
                amount_minor=1400000,
                currency="INR",
                available_channels=[Channel.OTA_GENERIC],
                merchant_hint="Klook",
            ),
            SpendLineItem(
                id="dining",
                label="Dining in Singapore",
                category=SpendCategory.DINING,
                amount_minor=2000000,
                currency="INR",
                available_channels=[Channel.POS_ABROAD],
            ),
            SpendLineItem(
                id="misc_forex",
                label="Misc forex spend",
                category=SpendCategory.FOREX_GENERAL,
                amount_minor=1500000,
                currency="INR",
                available_channels=[Channel.POS_ABROAD],
            ),
        ],
    )


def demo_wallet() -> UserWallet:
    return UserWallet(card_ids=["voyager-prime", "globesaver"])
