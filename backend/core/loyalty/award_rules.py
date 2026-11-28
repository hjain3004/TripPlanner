"""Deterministic integer arithmetic for hotel award stays, partner edges, and direct vs OTA."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from core.loyalty.contracts import (
    AlliancePartnerEdge,
    DirectVsOtaLoyaltyComparison,
    HotelAwardStayCalculation,
    HotelAwardStayRule,
    HotelChainBrandRule,
)
from core.models import Provenance
from core.transfer.arithmetic import BASIS_POINTS, FX_RATE_MICRO

# Currencies with zero decimal minor units vs three-decimal minor units (ISO 4217).
_ZERO_DECIMAL_CURRENCIES: frozenset[str] = frozenset(
    {
        "BIF",
        "CLP",
        "DJF",
        "GNF",
        "ISK",
        "JPY",
        "KMF",
        "KRW",
        "PYG",
        "RWF",
        "UGX",
        "VND",
        "VUV",
        "XAF",
        "XOF",
        "XPF",
    }
)
_THREE_DECIMAL_CURRENCIES: frozenset[str] = frozenset(
    {"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"}
)


def _minor_units_per_major(currency: str) -> int:
    if currency in _ZERO_DECIMAL_CURRENCIES:
        return 1
    if currency in _THREE_DECIMAL_CURRENCIES:
        return 1000
    return 100


def _require_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer (not bool), got {value!r}")
    return value


def _require_nonneg_int(value: int, name: str) -> int:
    checked = _require_int(value, name)
    if checked < 0:
        raise ValueError(f"{name} must be non-negative, got {checked}")
    return checked


def compute_hotel_award_stay_points(
    nightly_points: Sequence[int],
    rule: HotelAwardStayRule,
    user_has_eligibility: bool,
) -> HotelAwardStayCalculation:
    """Compute exact integer net award points under 4th/5th-night-free stay rules.

    For each complete non-overlapping block of ``n = rule.free_night_every_n`` consecutive
    nights, waives either the lowest-cost night in the block (``"lowest_in_block"``, used by
    Marriott Bonvoy and Hilton Honors) or the exact Nth night of the block
    (``"fourth_night_exact"`` / ``"last_in_block"``, used by IHG co-branded card 4th-night-free).
    """
    validated_nights: list[int] = []
    for idx, pts in enumerate(nightly_points):
        if isinstance(pts, bool) or pts < 0:
            raise ValueError(f"nightly_points[{idx}] must be a non-negative integer, got {pts!r}")
        validated_nights.append(pts)

    nights = len(validated_nights)
    gross_points = sum(validated_nights)
    every_n = rule.free_night_every_n

    if not user_has_eligibility or every_n is None or nights < every_n:
        if every_n is None:
            reason = f"{rule.program_id} has no Nth-night-free benefit."
        elif not user_has_eligibility:
            req = rule.requires_status_or_card or "program eligibility"
            reason = f"Ineligible ({req}); {nights} nights priced at full gross points."
        else:
            reason = (
                f"Stay is {nights} nights (< {every_n} required for free night); "
                "no free night waived."
            )
        return HotelAwardStayCalculation(
            program_id=rule.program_id,
            nights=nights,
            gross_points=gross_points,
            free_nights_count=0,
            points_saved=0,
            net_points=gross_points,
            free_night_indices=(),
            eligibility_applied=False,
            explanation=reason,
            provenance=rule.provenance,
        )

    waived_indices: list[int] = []
    points_saved = 0
    for block_start in range(0, nights - every_n + 1, every_n):
        block_end = block_start + every_n
        if rule.free_night_selection == "lowest_in_block":
            waived_idx = min(
                range(block_start, block_end),
                key=lambda i: (validated_nights[i], i),
            )
        elif rule.free_night_selection == "fourth_night_exact":
            if every_n != 4:
                raise ValueError(
                    f"fourth_night_exact requires free_night_every_n == 4, got {every_n}"
                )
            waived_idx = block_start + 3
        else:
            waived_idx = block_end - 1
        waived_indices.append(waived_idx)
        points_saved += validated_nights[waived_idx]

    net_points = gross_points - points_saved
    explanation = (
        f"Applied {every_n}th-night-free ({rule.free_night_selection}): "
        f"{len(waived_indices)} free night(s) saved {points_saved} points "
        f"across {nights} nights ({net_points} net)."
    )
    return HotelAwardStayCalculation(
        program_id=rule.program_id,
        nights=nights,
        gross_points=gross_points,
        free_nights_count=len(waived_indices),
        points_saved=points_saved,
        net_points=net_points,
        free_night_indices=tuple(waived_indices),
        eligibility_applied=True,
        explanation=explanation,
        provenance=rule.provenance,
    )


def find_partner_booking_programs(
    operating_carrier_iata: str,
    partner_edges: Sequence[AlliancePartnerEdge] | None = None,
) -> list[AlliancePartnerEdge]:
    """Return all loyalty programs able to ticket flights operated by ``operating_carrier_iata``."""
    target = operating_carrier_iata.strip().upper()
    if not target:
        return []

    edges: Sequence[AlliancePartnerEdge]
    if partner_edges is None:
        from core.loyalty.catalog_loader import default_alliance_partner_edges

        edges = default_alliance_partner_edges()
    else:
        edges = partner_edges

    matched = [edge for edge in edges if edge.operating_carrier_iata.strip().upper() == target]
    return sorted(
        matched,
        key=lambda edge: (edge.booking_program_id, edge.alliance_or_bilateral),
    )


def compare_direct_vs_ota_hotel(
    *,
    direct_cash_minor: int,
    ota_cash_minor: int,
    currency: str,
    chain_rule: HotelChainBrandRule | None = None,
    direct_card_points_value_minor: int = 0,
    ota_card_points_value_minor: int = 0,
    ota_card_bonus_delta_minor: int = 0,
    elite_bonus_bp: int = 0,
    hotel_point_value_micro_major: int = 0,
    status_perks_value_minor: int = 0,
    fx_usd_to_booking_currency_micro: int | None = None,
    direct_pre_tax_minor: int | None = None,
    ota_cash_back_or_discount_minor: int = 0,
    ota_earns_chain_loyalty: bool = False,
    direct_provenance: Provenance | None = None,
) -> DirectVsOtaLoyaltyComparison:
    """Deterministically compare direct hotel booking vs an OTA or bank travel portal.

    Every value is computed in integer minor units of ``currency``. Direct hotel loyalty earn
    scales USD-denominated base earn (per 100 USD minor units) by ``1 + elite_bonus_bp / 10_000``
    and values the earned hotel points at ``hotel_point_value_micro_major`` micro-major units per
    point in ``currency``.
    """
    direct_cash = _require_nonneg_int(direct_cash_minor, "direct_cash_minor")
    ota_cash = _require_nonneg_int(ota_cash_minor, "ota_cash_minor")
    direct_card_val = _require_nonneg_int(
        direct_card_points_value_minor, "direct_card_points_value_minor"
    )
    ota_card_val = _require_nonneg_int(ota_card_points_value_minor, "ota_card_points_value_minor")
    card_bonus_delta = _require_int(ota_card_bonus_delta_minor, "ota_card_bonus_delta_minor")
    elite_bp = _require_nonneg_int(elite_bonus_bp, "elite_bonus_bp")
    point_val_micro = _require_nonneg_int(
        hotel_point_value_micro_major, "hotel_point_value_micro_major"
    )
    status_perks = _require_nonneg_int(status_perks_value_minor, "status_perks_value_minor")
    ota_discount = _require_nonneg_int(
        ota_cash_back_or_discount_minor, "ota_cash_back_or_discount_minor"
    )
    if ota_discount > ota_cash:
        raise ValueError("ota_cash_back_or_discount_minor cannot exceed ota_cash_minor")
    norm_ccy = currency.strip().upper()
    if len(norm_ccy) != 3:
        raise ValueError(f"currency must be a 3-letter ISO code, got {currency!r}")

    eligible_base_minor = (
        direct_cash
        if direct_pre_tax_minor is None
        else _require_nonneg_int(direct_pre_tax_minor, "direct_pre_tax_minor")
    )

    minor_per_major = _minor_units_per_major(norm_ccy)
    direct_points = 0
    if chain_rule is not None and chain_rule.base_points_per_usd_minor_or_unit > 0:
        if norm_ccy == "USD":
            effective_fx = FX_RATE_MICRO
        elif fx_usd_to_booking_currency_micro is not None:
            effective_fx = _require_nonneg_int(
                fx_usd_to_booking_currency_micro, "fx_usd_to_booking_currency_micro"
            )
            if effective_fx <= 0:
                raise ValueError("fx_usd_to_booking_currency_micro must be > 0")
        else:
            raise ValueError(
                f"fx_usd_to_booking_currency_micro (> 0) is required when currency is {norm_ccy}"
            )
        # Single integer floor division avoids double-truncation across FX conversion + earn.
        direct_points = (
            eligible_base_minor
            * FX_RATE_MICRO
            * chain_rule.base_points_per_usd_minor_or_unit
            * (BASIS_POINTS + elite_bp)
        ) // (minor_per_major * effective_fx * BASIS_POINTS)

    direct_loyalty_value = (direct_points * point_val_micro * minor_per_major) // FX_RATE_MICRO
    forfeited_loyalty_value = (
        0 if ota_earns_chain_loyalty else (direct_loyalty_value + status_perks)
    )

    net_card_advantage_ota = ota_card_val - direct_card_val + card_bonus_delta
    effective_ota_cash = ota_cash - ota_discount

    # Effective OTA net cost minus effective direct net cost: positive means direct wins.
    net_direct_advantage_minor = (
        (effective_ota_cash - direct_cash) + forfeited_loyalty_value - net_card_advantage_ota
    )

    recommendation: Literal["BOOK_DIRECT", "BOOK_OTA", "TIE"]
    if net_direct_advantage_minor > 0:
        recommendation = "BOOK_DIRECT"
    elif net_direct_advantage_minor < 0:
        recommendation = "BOOK_OTA"
    else:
        recommendation = "TIE"

    factors: list[str] = [
        f"Direct cash: {direct_cash} {norm_ccy} vs effective OTA cash: "
        f"{effective_ota_cash} {norm_ccy}.",
        f"Direct hotel earn: {direct_points} pts worth {direct_loyalty_value} {norm_ccy}; "
        f"elite perks: {status_perks} {norm_ccy}.",
        f"OTA card points delta vs direct: {net_card_advantage_ota} {norm_ccy}; "
        f"forfeited loyalty on OTA: {forfeited_loyalty_value} {norm_ccy}.",
    ]
    warnings: list[str] = []
    if chain_rule is not None and chain_rule.provenance.needs_verification:
        warnings.append(f"hotel_chain_rule:{chain_rule.chain_id}:needs_verification")
    if direct_provenance is not None and direct_provenance.needs_verification:
        warnings.append("hotel_direct_quote:needs_verification")
    if status_perks > 0:
        warnings.append("elite_perks_value_user_or_rule_estimated:verify_benefit_terms")

    return DirectVsOtaLoyaltyComparison(
        direct_cash_minor=direct_cash,
        ota_cash_minor=ota_cash,
        currency=norm_ccy,
        direct_loyalty_points_earned=direct_points,
        direct_loyalty_value_minor=direct_loyalty_value,
        status_perks_value_minor=status_perks,
        forfeited_loyalty_value_minor=forfeited_loyalty_value,
        net_direct_advantage_minor=net_direct_advantage_minor,
        recommendation=recommendation,
        explanation_factors=factors,
        provenance_warnings=warnings,
    )
