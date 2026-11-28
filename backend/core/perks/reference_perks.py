"""Unverified read-only reference catalog for rental-car loyalty programs and card perks.

All records carry ``verified_by="UNVERIFIED"`` and ``needs_verification=True``.
Strictly separated from ``backend/core/seeds/*.yaml``.
"""

from __future__ import annotations

from datetime import date

from core.models import Channel, Provenance, SpendCategory
from core.perks.contracts import (
    AirlineBagPerk,
    CardGrantedStatus,
    CardPerkProfile,
    ReferenceRentalProgram,
    RentalCarProtection,
    StatementCreditPerk,
)

_REF_DATE = date(2026, 11, 27)


def _unverified_prov(source_url: str, notes: str) -> Provenance:
    return Provenance(
        source_url=source_url,
        source_type="manual_curation",
        last_verified=_REF_DATE,
        verified_by="UNVERIFIED",
        needs_verification=True,
        confidence=0.5,
        notes=notes,
    )


def reference_car_rental_programs() -> list[ReferenceRentalProgram]:
    """Reference car-rental loyalty programs (read-only, UNVERIFIED)."""
    return [
        ReferenceRentalProgram(
            id="national-emerald",
            name="National Car Rental Emerald Club (Reference)",
            booking_url="https://www.nationalcar.com/en/emerald-club.html",
            provenance=_unverified_prov(
                "https://www.nationalcar.com/en/emerald-club.html",
                "Reference car rental loyalty program; UNVERIFIED.",
            ),
        ),
        ReferenceRentalProgram(
            id="hertz-gold",
            name="Hertz Gold Plus Rewards (Reference)",
            booking_url="https://www.hertz.com/rentacar/emember/join/overview.do",
            provenance=_unverified_prov(
                "https://www.hertz.com/rentacar/emember/join/overview.do",
                "Reference car rental loyalty program; UNVERIFIED.",
            ),
        ),
        ReferenceRentalProgram(
            id="avis-preferred",
            name="Avis Preferred (Reference)",
            booking_url="https://www.avis.com/en/loyalty-profile/avis-preferred",
            provenance=_unverified_prov(
                "https://www.avis.com/en/loyalty-profile/avis-preferred",
                "Reference car rental loyalty program; UNVERIFIED.",
            ),
        ),
        ReferenceRentalProgram(
            id="sixt-status",
            name="Sixt Status (Reference)",
            booking_url="https://www.sixt.com/plus/",
            provenance=_unverified_prov(
                "https://www.sixt.com/plus/",
                "Reference car rental loyalty program; UNVERIFIED.",
            ),
        ),
    ]


def reference_card_perk_profiles() -> dict[str, CardPerkProfile]:
    """Representative unverified card perk profiles (never treated as verified KB facts)."""
    sapphire_reserve = CardPerkProfile(
        card_id="chase-sapphire-reserve-ref",
        rental_protection=RentalCarProtection(
            card_id="chase-sapphire-reserve-ref",
            coverage_type="primary_cdw",
            max_coverage_minor=7_500_000,  # $75,000
            currency="USD",
            max_rental_days=31,
            excluded_countries=["IE", "IL", "JM"],
            requires_full_payment_on_card=True,
            counter_cdw_avoided_per_day_minor=2_500,  # $25/day reference estimate
            provenance=_unverified_prov(
                "https://creditcards.chase.com/rewards-credit-cards/sapphire/reserve",
                "Primary CDW reference estimate ($25/day counter CDW avoided); UNVERIFIED.",
            ),
        ),
        granted_statuses=[
            CardGrantedStatus(
                card_id="chase-sapphire-reserve-ref",
                program_id="national-emerald",
                program_kind="car_rental",
                tier_name="Emerald Club Executive",
                estimated_value_per_event_minor=3_000,  # $30 reference aisle upgrade estimate
                currency="USD",
                requires_enrollment=True,
                perks_summary=["Executive Area aisle access", "Priority counter service"],
                provenance=_unverified_prov(
                    "https://creditcards.chase.com/rewards-credit-cards/sapphire/reserve",
                    "Reference Emerald Club Executive perk; UNVERIFIED.",
                ),
            )
        ],
        statement_credits=[
            StatementCreditPerk(
                id="csr-annual-travel-credit",
                card_id="chase-sapphire-reserve-ref",
                description="$300 annual travel statement credit",
                categories=[
                    SpendCategory.FLIGHTS,
                    SpendCategory.HOTELS,
                    SpendCategory.CAR_RENTAL,
                    SpendCategory.TRANSIT,
                ],
                channels=None,
                max_credit_minor=30_000,
                remaining_credit_minor=30_000,
                currency="USD",
                period="annual",
                provenance=_unverified_prov(
                    "https://creditcards.chase.com/rewards-credit-cards/sapphire/reserve",
                    "Reference $300 annual travel credit; UNVERIFIED.",
                ),
            )
        ],
        bag_perks=[],
    )

    venture_x = CardPerkProfile(
        card_id="capital-one-venture-x-ref",
        rental_protection=RentalCarProtection(
            card_id="capital-one-venture-x-ref",
            coverage_type="primary_cdw",
            max_coverage_minor=7_500_000,
            currency="USD",
            max_rental_days=15,  # domestic 15 / intl 31 conservative bound
            excluded_countries=["IL", "JM", "IE"],
            requires_full_payment_on_card=True,
            counter_cdw_avoided_per_day_minor=2_500,
            provenance=_unverified_prov(
                "https://www.capitalone.com/credit-cards/venture-x/",
                "Primary CDW reference estimate; UNVERIFIED.",
            ),
        ),
        granted_statuses=[
            CardGrantedStatus(
                card_id="capital-one-venture-x-ref",
                program_id="hertz-gold",
                program_kind="car_rental",
                tier_name="Hertz President's Circle",
                estimated_value_per_event_minor=3_500,
                currency="USD",
                requires_enrollment=True,
                perks_summary=["Guaranteed car-class upgrade", "Ultimate Choice aisle"],
                provenance=_unverified_prov(
                    "https://www.capitalone.com/credit-cards/venture-x/",
                    "Hertz President's Circle granted status; UNVERIFIED.",
                ),
            )
        ],
        statement_credits=[
            StatementCreditPerk(
                id="vx-portal-travel-credit",
                card_id="capital-one-venture-x-ref",
                description="$300 annual portal travel credit",
                categories=[
                    SpendCategory.FLIGHTS,
                    SpendCategory.HOTELS,
                    SpendCategory.CAR_RENTAL,
                ],
                channels=[Channel.BANK_PORTAL],
                max_credit_minor=30_000,
                remaining_credit_minor=30_000,
                currency="USD",
                period="annual",
                provenance=_unverified_prov(
                    "https://www.capitalone.com/credit-cards/venture-x/",
                    "Capital One Travel $300 portal credit; UNVERIFIED.",
                ),
            )
        ],
        bag_perks=[],
    )

    amex_platinum = CardPerkProfile(
        card_id="amex-platinum-ref",
        rental_protection=RentalCarProtection(
            card_id="amex-platinum-ref",
            coverage_type="secondary_cdw",
            max_coverage_minor=7_500_000,
            currency="USD",
            max_rental_days=30,
            excluded_countries=["AU", "IT", "NZ"],
            requires_full_payment_on_card=True,
            counter_cdw_avoided_per_day_minor=0,
            provenance=_unverified_prov(
                "https://www.americanexpress.com/us/credit-cards/card/platinum/",
                "Standard included rental coverage is secondary CDW; UNVERIFIED.",
            ),
        ),
        granted_statuses=[
            CardGrantedStatus(
                card_id="amex-platinum-ref",
                program_id="marriott-bonvoy",
                program_kind="hotel",
                tier_name="Marriott Bonvoy Gold Elite",
                estimated_value_per_event_minor=2_500,
                currency="USD",
                requires_enrollment=True,
                perks_summary=["2pm late checkout when available", "Enhanced room upgrade"],
                provenance=_unverified_prov(
                    "https://www.americanexpress.com/us/credit-cards/card/platinum/",
                    "Hotel status benefit estimate; UNVERIFIED.",
                ),
            ),
            CardGrantedStatus(
                card_id="amex-platinum-ref",
                program_id="national-emerald",
                program_kind="car_rental",
                tier_name="Emerald Club Executive",
                estimated_value_per_event_minor=3_000,
                currency="USD",
                requires_enrollment=True,
                perks_summary=["Executive aisle access"],
                provenance=_unverified_prov(
                    "https://www.americanexpress.com/us/credit-cards/card/platinum/",
                    "Rental status benefit estimate; UNVERIFIED.",
                ),
            ),
            CardGrantedStatus(
                card_id="amex-platinum-ref",
                program_id="avis-preferred",
                program_kind="car_rental",
                tier_name="Avis Preferred Plus",
                estimated_value_per_event_minor=2_000,
                currency="USD",
                requires_enrollment=True,
                perks_summary=["One-car-class upgrade subject to availability"],
                provenance=_unverified_prov(
                    "https://www.americanexpress.com/us/credit-cards/card/platinum/",
                    "Avis Preferred Plus status estimate; UNVERIFIED.",
                ),
            ),
        ],
        statement_credits=[
            StatementCreditPerk(
                id="amex-plat-monthly-uber",
                card_id="amex-platinum-ref",
                description="$15 monthly Uber Cash credit",
                categories=[SpendCategory.TRANSIT],
                channels=None,
                max_credit_minor=1_500,
                remaining_credit_minor=1_500,
                currency="USD",
                period="monthly",
                provenance=_unverified_prov(
                    "https://www.americanexpress.com/us/credit-cards/card/platinum/",
                    "Monthly Uber Cash statement credit; UNVERIFIED.",
                ),
            ),
            StatementCreditPerk(
                id="amex-plat-semi-annual-hotel",
                card_id="amex-platinum-ref",
                description="$300 semi-annual prepaid FHR/THC hotel credit",
                categories=[SpendCategory.HOTELS],
                channels=[Channel.BANK_PORTAL],
                max_credit_minor=30_000,
                remaining_credit_minor=30_000,
                currency="USD",
                period="semi_annual",
                provenance=_unverified_prov(
                    "https://www.americanexpress.com/us/credit-cards/card/platinum/",
                    "Semi-annual FHR/THC portal hotel credit; UNVERIFIED.",
                ),
            ),
        ],
        bag_perks=[],
    )

    hilton_aspire = CardPerkProfile(
        card_id="hilton-aspire-ref",
        rental_protection=None,
        granted_statuses=[
            CardGrantedStatus(
                card_id="hilton-aspire-ref",
                program_id="hilton-honors",
                program_kind="hotel",
                tier_name="Hilton Honors Diamond",
                estimated_value_per_event_minor=5_000,
                currency="USD",
                requires_enrollment=False,
                perks_summary=["Executive lounge access", "Space-available upgrades", "Breakfast"],
                provenance=_unverified_prov(
                    "https://www.americanexpress.com/us/credit-cards/card/hilton-honors-aspire/",
                    "Automatic Hilton Diamond status estimate; UNVERIFIED.",
                ),
            )
        ],
        statement_credits=[
            StatementCreditPerk(
                id="aspire-airline-quarterly",
                card_id="hilton-aspire-ref",
                description="$50 quarterly airline flight credit",
                categories=[SpendCategory.FLIGHTS],
                channels=[Channel.DIRECT_AIRLINE],
                max_credit_minor=5_000,
                remaining_credit_minor=5_000,
                currency="USD",
                period="annual",
                provenance=_unverified_prov(
                    "https://www.americanexpress.com/us/credit-cards/card/hilton-honors-aspire/",
                    "Flight credit estimate; UNVERIFIED.",
                ),
            )
        ],
        bag_perks=[
            AirlineBagPerk(
                card_id="hilton-aspire-ref",
                airline_iata="UA",
                free_checked_bags=1,
                estimated_value_per_bag_minor=3_500,
                currency="USD",
                requires_payment_on_card=True,
                provenance=_unverified_prov(
                    "https://example.invalid/bag-perk-ref",
                    "Representative checked bag perk; UNVERIFIED.",
                ),
            )
        ],
    )

    return {
        "chase-sapphire-reserve-ref": sapphire_reserve,
        "capital-one-venture-x-ref": venture_x,
        "amex-platinum-ref": amex_platinum,
        "hilton-aspire-ref": hilton_aspire,
    }


def get_reference_perk_profile(card_id: str) -> CardPerkProfile | None:
    """Return a copy of the unverified reference perk profile if defined."""
    return reference_card_perk_profiles().get(card_id)
