"""Pure deterministic integer evaluators for rental-car benefits and trip card perks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from core.models import Channel, Provenance, SpendCategory
from core.perks.contracts import (
    CardGrantedStatus,
    CardPerkProfile,
    RentalCarCardBreakdown,
    RentalCarCardCandidate,
    RentalCarCardComparison,
    RentalCarProtection,
    StatementCreditPerk,
    TripItemPerkBreakdown,
    TripPerkItem,
    TripPerksValuation,
)

FX_RATE_MICRO = 1_000_000
MICRO_MAJOR_PER_MINOR = 10_000
BASIS_POINTS_SQUARE = 100_000_000

_COUNTRY_ALIASES: dict[str, frozenset[str]] = {
    "ie": frozenset({"ie", "ireland"}),
    "ireland": frozenset({"ie", "ireland"}),
    "il": frozenset({"il", "israel"}),
    "israel": frozenset({"il", "israel"}),
    "jm": frozenset({"jm", "jamaica"}),
    "jamaica": frozenset({"jm", "jamaica"}),
    "it": frozenset({"it", "italy"}),
    "italy": frozenset({"it", "italy"}),
    "au": frozenset({"au", "australia"}),
    "australia": frozenset({"au", "australia"}),
    "nz": frozenset({"nz", "new zealand"}),
    "new zealand": frozenset({"nz", "new zealand"}),
}


def _convert_minor(
    amount_minor: int,
    from_currency: str,
    to_currency: str,
    fx_rates: Mapping[tuple[str, str], int],
) -> int:
    src = from_currency.strip().upper()
    dst = to_currency.strip().upper()
    if src == dst or amount_minor == 0:
        return amount_minor
    rate_micro = fx_rates.get((src, dst))
    if rate_micro is None:
        raise ValueError(f"Missing FX rate for {src}->{dst}")
    if rate_micro < 0:
        raise ValueError(f"Invalid negative FX rate for {src}->{dst}: {rate_micro}")
    return (amount_minor * rate_micro) // FX_RATE_MICRO


def _country_tokens(raw: str) -> frozenset[str]:
    key = raw.strip().casefold()
    return _COUNTRY_ALIASES.get(key, frozenset({key}))


def _is_country_excluded(pickup_country: str, excluded_countries: Sequence[str]) -> bool:
    pickup_tokens = _country_tokens(pickup_country)
    for ex in excluded_countries:
        if pickup_tokens & _country_tokens(ex):
            return True
    return False


def _prov_warning(kind: str, ident: str, prov: Provenance) -> str | None:
    if prov.needs_verification:
        return f"{kind}:{ident}:needs_verification"
    return None


def _evaluate_cdw(
    *,
    protection: RentalCarProtection | None,
    rental_days: int,
    pickup_country: str | None,
    paid_in_full_on_card: bool,
    home_currency: str,
    fx_rates: Mapping[tuple[str, str], int],
) -> tuple[int, bool, str | None, list[str], list[str]]:
    if protection is None or protection.coverage_type == "none":
        return (
            0,
            False,
            "no_cdw_coverage",
            ["Card offers no rental-car CDW coverage."],
            [],
        )

    warnings: list[str] = []
    warn = _prov_warning("rental_protection", protection.card_id, protection.provenance)
    if warn:
        warnings.append(warn)

    if protection.coverage_type == "secondary_cdw":
        return (
            0,
            False,
            "secondary_cdw_not_primary",
            [
                "Secondary CDW provides 0 avoided counter-CDW savings "
                "(requires filing with personal auto insurance first; primary CDW required "
                "to waive counter CDW)."
            ],
            warnings,
        )

    # primary_cdw checks
    if rental_days <= 0:
        return (
            0,
            False,
            "nonpositive_rental_days",
            ["Primary CDW savings require rental_days > 0."],
            warnings,
        )
    if protection.requires_full_payment_on_card and not paid_in_full_payment(paid_in_full_on_card):
        return (
            0,
            False,
            "requires_full_payment_on_card",
            ["Primary CDW disqualified: card requires paying the rental in full on the card."],
            warnings,
        )
    if rental_days > protection.max_rental_days:
        return (
            0,
            False,
            "exceeds_max_rental_days",
            [
                f"Primary CDW disqualified: {rental_days} days exceeds "
                f"{protection.max_rental_days}-day policy limit."
            ],
            warnings,
        )
    if pickup_country is not None and _is_country_excluded(
        pickup_country, protection.excluded_countries
    ):
        return (
            0,
            False,
            "excluded_country",
            [
                f"Primary CDW disqualified: pickup country {pickup_country!r} is in "
                "card excluded_countries."
            ],
            warnings,
        )

    avoided_raw = protection.counter_cdw_avoided_per_day_minor * rental_days
    avoided_home = _convert_minor(avoided_raw, protection.currency, home_currency, fx_rates)
    return (
        avoided_home,
        True,
        None,
        [
            f"Primary CDW applied ({rental_days} days x "
            f"{protection.counter_cdw_avoided_per_day_minor} {protection.currency}/day minor -> "
            f"{avoided_home} {home_currency} minor avoided counter CDW)."
        ],
        warnings,
    )


def paid_in_full_payment(paid: bool) -> bool:
    return paid


def _best_status_for_item(
    *,
    statuses: Sequence[CardGrantedStatus],
    program_kind: str,
    target_program_id: str | None,
    multiplier: int,
    home_currency: str,
    fx_rates: Mapping[tuple[str, str], int],
) -> tuple[int, list[str], list[str]]:
    if multiplier <= 0:
        return 0, [], []
    matching = [
        s
        for s in statuses
        if s.program_kind == program_kind
        and (target_program_id is None or s.program_id == target_program_id)
    ]
    if not matching:
        return 0, [], []

    best_val = -1
    best_status: CardGrantedStatus | None = None
    for s in sorted(matching, key=lambda row: row.program_id):
        val = (
            _convert_minor(
                s.estimated_value_per_event_minor, s.currency, home_currency, fx_rates
            )
            * multiplier
        )
        if val > best_val:
            best_val = val
            best_status = s

    assert best_status is not None
    notes = [
        f"Granted status {best_status.program_id} ({best_status.tier_name}) "
        f"adds {best_val} {home_currency} minor."
    ]
    if best_status.requires_enrollment:
        notes.append(f"Requires advance enrollment for {best_status.tier_name}.")
    warnings: list[str] = []
    warn = _prov_warning(
        "card_granted_status",
        f"{best_status.card_id}:{best_status.program_id}",
        best_status.provenance,
    )
    if warn:
        warnings.append(warn)
    return best_val, notes, warnings


def _apply_statement_credits(
    *,
    credits: Sequence[StatementCreditPerk],
    remaining_by_id: dict[str, int],
    category: SpendCategory,
    channel: Channel,
    item_amount_minor: int,
    item_currency: str,
    home_currency: str,
    fx_rates: Mapping[tuple[str, str], int],
) -> tuple[int, list[str], list[str], list[str]]:
    eligible = [
        c
        for c in sorted(credits, key=lambda row: row.id)
        if category in c.categories
        and (c.channels is None or channel in c.channels)
        and remaining_by_id.get(c.id, 0) > 0
    ]
    if not eligible or item_amount_minor <= 0:
        return 0, [], [], []

    remaining_item_home = _convert_minor(
        item_amount_minor, item_currency, home_currency, fx_rates
    )
    total_credit_home = 0
    applied_ids: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []

    for c in eligible:
        if remaining_item_home <= 0:
            break
        rem_credit_ccy = remaining_by_id[c.id]
        if rem_credit_ccy <= 0:
            continue
        uncovered_in_credit_ccy = _convert_minor(
            remaining_item_home, home_currency, c.currency, fx_rates
        )
        used_credit_ccy = min(rem_credit_ccy, uncovered_in_credit_ccy)
        if used_credit_ccy <= 0:
            continue
        used_home = min(
            remaining_item_home,
            _convert_minor(used_credit_ccy, c.currency, home_currency, fx_rates),
        )
        if used_home <= 0:
            continue
        remaining_by_id[c.id] = rem_credit_ccy - used_credit_ccy
        remaining_item_home -= used_home
        total_credit_home += used_home
        applied_ids.append(c.id)
        notes.append(
            f"Statement credit {c.id} ({c.period}) applied {used_home} {home_currency} minor "
            f"({remaining_by_id[c.id]} {c.currency} minor remaining)."
        )
        warn = _prov_warning("statement_credit", c.id, c.provenance)
        if warn:
            warnings.append(warn)

    return total_credit_home, applied_ids, notes, warnings


def evaluate_rental_car_cards(
    rental_cost_minor: int,
    rental_days: int,
    rental_currency: str,
    pickup_country: str,
    home_currency: str,
    fx_rates: Mapping[tuple[str, str], int],
    candidates: Sequence[RentalCarCardCandidate],
) -> RentalCarCardComparison:
    """Rank rental-car cards by deterministic integer net benefit across points and perks."""
    if rental_cost_minor < 0 or rental_days < 0:
        raise ValueError("rental_cost_minor and rental_days must be nonnegative")

    norm_rental_ccy = rental_currency.strip().upper()
    norm_home_ccy = home_currency.strip().upper()
    rental_home_minor = _convert_minor(
        rental_cost_minor, norm_rental_ccy, norm_home_ccy, fx_rates
    )

    breakdowns: list[RentalCarCardBreakdown] = []
    all_warnings: set[str] = set()

    for cand in candidates:
        profile = cand.perk_profile
        notes: list[str] = []
        warnings: set[str] = set()

        # 1. Points value
        if cand.points_value_minor is not None:
            pts_val_home = cand.points_value_minor
        elif cand.earn_rate is not None and cand.earn_rate.per_amount_minor > 0:
            earn_base = _convert_minor(
                rental_home_minor,
                norm_home_ccy,
                cand.earn_rate.currency.strip().upper(),
                fx_rates,
            )
            pts = (earn_base // cand.earn_rate.per_amount_minor) * cand.earn_rate.points
            pts_val_home = (pts * cand.point_value_micro) // MICRO_MAJOR_PER_MINOR
        else:
            pts_val_home = 0
        notes.append(f"Card earn value: {pts_val_home} {norm_home_ccy} minor.")

        # 2. Forex fee
        if cand.forex_cost_minor is not None:
            forex_home = cand.forex_cost_minor
        elif norm_rental_ccy != norm_home_ccy and cand.forex_markup_bp > 0:
            forex_home = (
                rental_home_minor
                * cand.forex_markup_bp
                * (10_000 + cand.forex_markup_tax_bp)
                // BASIS_POINTS_SQUARE
            )
        else:
            forex_home = 0
        if forex_home > 0:
            notes.append(f"Forex fee: -{forex_home} {norm_home_ccy} minor.")

        # 3. Primary vs secondary rental CDW
        protection = profile.rental_protection if profile is not None else None
        cov_type = protection.coverage_type if protection is not None else "none"
        cdw_savings, cdw_applied, cdw_reason, cdw_notes, cdw_warns = _evaluate_cdw(
            protection=protection,
            rental_days=rental_days,
            pickup_country=pickup_country,
            paid_in_full_on_card=cand.paid_in_full_on_card,
            home_currency=norm_home_ccy,
            fx_rates=fx_rates,
        )
        notes.extend(cdw_notes)
        warnings.update(cdw_warns)

        # 4. Applicable statement credits
        credit_val = 0
        if profile is not None and profile.statement_credits:
            rem_map = {c.id: c.remaining_credit_minor for c in profile.statement_credits}
            c_val, _c_ids, c_notes, c_warns = _apply_statement_credits(
                credits=profile.statement_credits,
                remaining_by_id=rem_map,
                category=SpendCategory.CAR_RENTAL,
                channel=cand.channel,
                item_amount_minor=rental_cost_minor,
                item_currency=norm_rental_ccy,
                home_currency=norm_home_ccy,
                fx_rates=fx_rates,
            )
            credit_val = c_val
            notes.extend(c_notes)
            warnings.update(c_warns)

        # 5. Granted rental-car status perks
        status_val = 0
        if profile is not None and profile.granted_statuses:
            s_val, s_notes, s_warns = _best_status_for_item(
                statuses=profile.granted_statuses,
                program_kind="car_rental",
                target_program_id=cand.preferred_rental_program_id,
                multiplier=1,
                home_currency=norm_home_ccy,
                fx_rates=fx_rates,
            )
            status_val = s_val
            notes.extend(s_notes)
            warnings.update(s_warns)

        net_value = pts_val_home + cdw_savings + credit_val + status_val - forex_home
        net_cost = rental_home_minor - net_value
        sorted_warns = sorted(warnings)
        all_warnings.update(sorted_warns)

        breakdowns.append(
            RentalCarCardBreakdown(
                card_id=cand.card_id,
                channel=cand.channel,
                rental_cost_home_minor=rental_home_minor,
                points_value_minor=pts_val_home,
                primary_cdw_savings_minor=cdw_savings,
                primary_cdw_applied=cdw_applied,
                applicable_credit_minor=credit_val,
                status_perk_value_minor=status_val,
                forex_cost_minor=forex_home,
                net_total_value_minor=net_value,
                net_rental_cost_minor=net_cost,
                cdw_coverage_type=cov_type,
                cdw_disqualification_reason=cdw_reason,
                explanation=notes,
                provenance_warnings=sorted_warns,
            )
        )

    ranked = sorted(breakdowns, key=lambda b: (-b.net_total_value_minor, b.card_id))
    winner = ranked[0] if ranked else None
    summary_notes: list[str] = []
    if winner is not None:
        summary_notes.append(
            f"Recommended card {winner.card_id} yields net benefit "
            f"{winner.net_total_value_minor} {norm_home_ccy} minor "
            f"(primary CDW: {winner.primary_cdw_savings_minor})."
        )
    return RentalCarCardComparison(
        recommended_card_id=winner.card_id if winner is not None else None,
        rental_cost_home_minor=rental_home_minor,
        home_currency=norm_home_ccy,
        candidates=ranked,
        provenance_warnings=sorted(all_warnings),
        explanation=summary_notes,
    )


def evaluate_trip_perks(
    items: Sequence[TripPerkItem],
    card_profiles: Mapping[str, CardPerkProfile],
    fx_rates: Mapping[tuple[str, str], int],
    home_currency: str,
) -> TripPerksValuation:
    """Aggregate non-points card perks across a multi-item trip enforcing credit caps."""
    norm_home_ccy = home_currency.strip().upper()
    remaining_credits: dict[str, int] = {}
    for card_id in sorted(card_profiles):
        profile = card_profiles[card_id]
        for credit in profile.statement_credits:
            remaining_credits[credit.id] = credit.remaining_credit_minor

    item_breakdowns: list[TripItemPerkBreakdown] = []
    total_cdw = 0
    total_status = 0
    total_bags = 0
    total_credits = 0
    all_warnings: set[str] = set()
    trip_notes: list[str] = []

    for item in items:
        item_profile = card_profiles.get(item.card_id)
        if item_profile is None:
            item_breakdowns.append(
                TripItemPerkBreakdown(
                    item_id=item.id,
                    card_id=item.card_id,
                    explanation=["No perk profile configured for card."],
                )
            )
            continue

        notes: list[str] = []
        warnings: set[str] = set()

        # 1. Rental car primary CDW
        cdw_val = 0
        if item.category == SpendCategory.CAR_RENTAL and item.rental_days > 0:
            cdw_val, _applied, _reason, cdw_notes, cdw_warns = _evaluate_cdw(
                protection=item_profile.rental_protection,
                rental_days=item.rental_days,
                pickup_country=item.pickup_country,
                paid_in_full_on_card=item.paid_in_full_on_card,
                home_currency=norm_home_ccy,
                fx_rates=fx_rates,
            )
            notes.extend(cdw_notes)
            warnings.update(cdw_warns)

        # 2. Granted status perk (car rental / hotel / airline)
        status_val = 0
        if item.category == SpendCategory.CAR_RENTAL and item_profile.granted_statuses:
            s_val, s_notes, s_warns = _best_status_for_item(
                statuses=item_profile.granted_statuses,
                program_kind="car_rental",
                target_program_id=item.rental_program_id,
                multiplier=1,
                home_currency=norm_home_ccy,
                fx_rates=fx_rates,
            )
            status_val += s_val
            notes.extend(s_notes)
            warnings.update(s_warns)
        elif item.category == SpendCategory.HOTELS and item_profile.granted_statuses:
            s_val, s_notes, s_warns = _best_status_for_item(
                statuses=item_profile.granted_statuses,
                program_kind="hotel",
                target_program_id=item.hotel_program_id,
                multiplier=item.hotel_stays_count,
                home_currency=norm_home_ccy,
                fx_rates=fx_rates,
            )
            status_val += s_val
            notes.extend(s_notes)
            warnings.update(s_warns)
        elif item.category == SpendCategory.FLIGHTS and item_profile.granted_statuses:
            s_val, s_notes, s_warns = _best_status_for_item(
                statuses=item_profile.granted_statuses,
                program_kind="airline",
                target_program_id=item.airline_iata,
                multiplier=1,
                home_currency=norm_home_ccy,
                fx_rates=fx_rates,
            )
            status_val += s_val
            notes.extend(s_notes)
            warnings.update(s_warns)

        # 3. Airline free checked bags
        bag_val = 0
        if (
            item.category == SpendCategory.FLIGHTS
            and item.airline_iata is not None
            and item.checked_bags_count > 0
            and item_profile.bag_perks
        ):
            target_iata = item.airline_iata.strip().upper()
            matching_bags = [
                bp
                for bp in item_profile.bag_perks
                if bp.airline_iata.strip().upper() == target_iata
                and (not bp.requires_payment_on_card or item.paid_in_full_on_card)
            ]
            if matching_bags:
                best_bp = max(
                    matching_bags,
                    key=lambda row: (
                        min(item.checked_bags_count, row.free_checked_bags)
                        * _convert_minor(
                            row.estimated_value_per_bag_minor,
                            row.currency,
                            norm_home_ccy,
                            fx_rates,
                        )
                    ),
                )
                covered_bags = min(item.checked_bags_count, best_bp.free_checked_bags)
                if covered_bags > 0:
                    bag_val = covered_bags * _convert_minor(
                        best_bp.estimated_value_per_bag_minor,
                        best_bp.currency,
                        norm_home_ccy,
                        fx_rates,
                    )
                    notes.append(
                        f"Airline bag perk ({best_bp.airline_iata}): {covered_bags} free bag(s) "
                        f"save {bag_val} {norm_home_ccy} minor."
                    )
                    warn = _prov_warning(
                        "airline_bag_perk",
                        f"{best_bp.card_id}:{best_bp.airline_iata}",
                        best_bp.provenance,
                    )
                    if warn:
                        warnings.add(warn)

        # 4. Statement credits (enforcing remaining_credits cap across trip items)
        credit_val, applied_ids, c_notes, c_warns = _apply_statement_credits(
            credits=item_profile.statement_credits,
            remaining_by_id=remaining_credits,
            category=item.category,
            channel=item.channel,
            item_amount_minor=item.amount_minor,
            item_currency=item.currency,
            home_currency=norm_home_ccy,
            fx_rates=fx_rates,
        )
        notes.extend(c_notes)
        warnings.update(c_warns)

        item_total = cdw_val + status_val + bag_val + credit_val
        total_cdw += cdw_val
        total_status += status_val
        total_bags += bag_val
        total_credits += credit_val
        sorted_warns = sorted(warnings)
        all_warnings.update(sorted_warns)

        item_breakdowns.append(
            TripItemPerkBreakdown(
                item_id=item.id,
                card_id=item.card_id,
                primary_cdw_savings_minor=cdw_val,
                status_perk_value_minor=status_val,
                bag_perk_value_minor=bag_val,
                statement_credit_minor=credit_val,
                total_perk_value_minor=item_total,
                applied_credit_ids=applied_ids,
                explanation=notes,
                provenance_warnings=sorted_warns,
            )
        )

    total_all = total_cdw + total_status + total_bags + total_credits
    trip_notes.append(
        f"Total trip non-points perks: {total_all} {norm_home_ccy} minor "
        f"(CDW={total_cdw}, status={total_status}, bags={total_bags}, credits={total_credits})."
    )
    return TripPerksValuation(
        home_currency=norm_home_ccy,
        total_primary_cdw_savings_minor=total_cdw,
        total_status_perk_value_minor=total_status,
        total_bag_perk_value_minor=total_bags,
        total_statement_credit_minor=total_credits,
        total_perks_value_minor=total_all,
        remaining_credit_balances_minor=dict(sorted(remaining_credits.items())),
        item_breakdowns=item_breakdowns,
        provenance_warnings=sorted(all_warnings),
        explanation=trip_notes,
    )
