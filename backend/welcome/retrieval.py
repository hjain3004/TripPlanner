"""Zero-bias candidate retrieval & lazy exact max-heap pruning for Case B (OPT-1).

Implements Stage-1 hard eligibility filtering, pure-integer sound additive upper
bounds ``UB(c | W)``, and CELF-style lazy max-heap (``heapq``) evaluation for top-m
single-card acquisition recommendations without affiliate or popularity bias.

Mathematical soundness guarantees:
- All money/points/upper-bound arithmetic uses exact Python ``int`` (plus stdlib
  arbitrary-precision ``fractions.Fraction`` only for fractional knapsack tier sums).
- For every candidate card ``c`` and held wallet ``W``, the computed upper bound satisfies
  ``UB(c | W) >= net_first_year_minor(c | W)`` unconditionally, guaranteeing that
  lazy heap halting returns the 100% exact same top-m suggestions as brute-force
  evaluation across the entire catalog.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction
from functools import cmp_to_key
from typing import Literal

from core.db import KnowledgeBase
from core.models import (
    Card,
    Channel,
    CostedTrip,
    EarnRate,
    Offer,
    OfferKind,
    RewardRule,
    SpendLineItem,
    UserWallet,
)
from core.optimizer import optimize
from core.optimizer.money import forex_fee_minor, points_value_minor
from core.optimizer.offers import apply_offer_subset, card_eligible, offer_subsets
from core.optimizer.rules import (
    POS_CHANNELS,
    earn_schedule,
    matching_rules,
    pool_key,
)
from welcome.catalog import OfferCatalog, verification_status
from welcome.models import (
    AcquisitionOfferOut,
    AcquisitionRefusal,
    AcquisitionRefusalReason,
    AcquisitionSuggestion,
    CandidateTimingAssessment,
    CardAcquisitionOffer,
    Limitation,
    OfferProvenanceOut,
    PaymentTimingIn,
)
from welcome.status import StoredPlan, _limit

# --------------------------------------------------------------------------- #
# Formatting & Offer Conversion Helpers                                       #
# --------------------------------------------------------------------------- #


def format_money(minor: int, currency: str) -> str:
    """Format minor currency units for human-readable sentences without floats."""
    symbol = "₹" if currency == "INR" else f"{currency} "
    negative = minor < 0
    abs_major = abs(minor) // 100
    formatted = f"{symbol}{abs_major:,}"
    return f"-{formatted}" if negative else formatted


def acquisition_offer_out(offer: CardAcquisitionOffer) -> AcquisitionOfferOut:
    """Convert internal CardAcquisitionOffer row to public AcquisitionOfferOut."""
    assert offer.eligibility_exclusions is not None
    assert offer.expected_approval_days is not None
    assert offer.expected_card_in_hand_days is not None
    assert offer.annual_fee_minor is not None
    assert offer.valid_to is not None
    prov = offer.provenance
    return AcquisitionOfferOut(
        id=offer.id,
        card_id=offer.card_id,
        title=offer.title,
        bonus_points=offer.bonus_points,
        bonus_currency_id=offer.bonus_currency_id,
        bonus_flat_minor=offer.bonus_flat_minor,
        min_spend_minor=offer.min_spend_minor,
        spend_window_days=offer.spend_window_days,
        expected_approval_days=offer.expected_approval_days,
        expected_card_in_hand_days=offer.expected_card_in_hand_days,
        annual_fee_minor=offer.annual_fee_minor,
        fee_waiver_condition=offer.fee_waiver_condition,
        currency=offer.currency,
        valid_to=offer.valid_to,
        eligibility_exclusions=list(offer.eligibility_exclusions),
        provenance=OfferProvenanceOut(
            source_url=prov.source_url,
            source_type=prov.source_type,
            last_verified=prov.last_verified,
            verified_by=prov.verified_by,
            needs_verification=prov.needs_verification,
            confidence=prov.confidence,
            notes=prov.notes,
            verification_status=verification_status(offer),
        ),
    )


def acquisition_assumptions(as_of: date, pt: PaymentTimingIn | None) -> list[str]:
    """Build standard Case B assumptions list."""
    notes = [
        f"Dates are evaluated as of {as_of.isoformat()} (the server's UTC date).",
        "The held-card strategy is unchanged and built entirely from cards already in your wallet.",
        "Incremental trip benefit is computed by running the deterministic optimizer with the "
        "candidate card added. No parallel reward calculation is used.",
        "This assessment is informational only and does not constitute a recommendation to apply, "
        "credit pre-qualification, or an approval decision.",
        "Welcome bonus is counted only once in the net first-year calculation and is not added "
        "to ongoing trip rewards.",
    ]
    if pt is None:
        notes.append(
            "Payment timing was not provided. Travel dates cannot be assumed to be payment dates, "
            "so timing feasibility and spend window compliance cannot be verified."
        )
    else:
        notes.append(
            f"Payment timing reflects caller-supplied dates: planned booking on "
            f"{pt.booking_date.isoformat()}, earliest spend on "
            f"{pt.first_bookable_spend_date.isoformat()}."
        )
    return notes


# --------------------------------------------------------------------------- #
# Gate Evaluation & Exact Candidate Assessment                                #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CandidatePreGateContext:
    """Validated pre-optimize terms and timing for an eligible candidate."""

    card_id: str
    card_name: str | None
    offer: CardAcquisitionOffer
    lead_time_days: int
    earliest_usable_date: date
    window_closes_on: date
    bonus_value_minor: int
    annual_fee_minor: int


def check_pre_optimize_gates(
    *,
    card_id: str,
    card_name: str | None,
    as_of: date,
    costed_trip: CostedTrip,
    catalog: OfferCatalog,
    pt: PaymentTimingIn | None,
    check_spend_window_before_optimize: bool = False,
) -> tuple[CandidatePreGateContext | None, AcquisitionRefusal | None, Limitation | None]:
    """Evaluate all offer/timing/currency gates prior to running ``optimize()``.

    When ``check_spend_window_before_optimize`` is True (multi-card retrieval), Gate 3
    is filtered upfront alongside Gate 1; for single-card explicit inspection it remains
    evaluated after Gate 2 to preserve refusal ordering.
    """
    booking_date = pt.booking_date if pt is not None else as_of
    selection = catalog.select_acquisition_offer(card_id, booking_date)

    if selection.offer is None:
        sel_reason = selection.reason or "NO_APPROVED_OFFER"
        ref_reason: AcquisitionRefusalReason
        if sel_reason == "OFFER_NOT_IN_FORCE_AT_OPEN_DATE":
            ref_reason = "OFFER_EXPIRED"
        elif sel_reason == "AMBIGUOUS_OFFER":
            ref_reason = "AMBIGUOUS_OFFER"
        elif sel_reason == "OFFER_TERMS_INCOMPLETE":
            ref_reason = "OFFER_TERMS_INCOMPLETE"
        else:
            ref_reason = "NO_APPROVED_OFFER"
        refusal = AcquisitionRefusal(
            card_id=card_id,
            card_name=card_name,
            offer_id=None,
            reason=ref_reason,
            message=(
                f"No approved welcome offer is available for candidate card {card_id}."
                if ref_reason == "NO_APPROVED_OFFER"
                else (
                    f"The offer terms for candidate card {card_id} have expired."
                    if ref_reason == "OFFER_EXPIRED"
                    else f"Offer selection failed with code {sel_reason}."
                )
            ),
            details={"selection_reason": sel_reason},
        )
        return None, refusal, None

    offer = selection.offer

    if pt is None:
        refusal = AcquisitionRefusal(
            card_id=card_id,
            card_name=card_name,
            offer_id=offer.id,
            reason="PAYMENT_TIMING_UNKNOWN",
            message=(
                "Explicit payment timing was not provided. Travel dates cannot be "
                "assumed to be payment dates, so whether the card can arrive in time "
                "cannot be determined."
            ),
            details={"offer_id": offer.id},
        )
        return None, refusal, None

    # Gate 5: offer.valid_to >= booking_date
    if offer.valid_to is None:
        raise AssertionError("catalog selected offer without an end date")
    if offer.valid_to < pt.booking_date:
        refusal = AcquisitionRefusal(
            card_id=card_id,
            card_name=card_name,
            offer_id=offer.id,
            reason="OFFER_EXPIRED",
            message=(
                f"The offer expired on {offer.valid_to.isoformat()}, before the "
                f"planned booking date {pt.booking_date.isoformat()}."
            ),
            details={
                "valid_to": offer.valid_to.isoformat(),
                "booking_date": pt.booking_date.isoformat(),
            },
        )
        return None, refusal, None

    unknown_terms = [
        name
        for name, value in (
            ("expected_approval_days", offer.expected_approval_days),
            ("expected_card_in_hand_days", offer.expected_card_in_hand_days),
            ("annual_fee_minor", offer.annual_fee_minor),
        )
        if value is None
    ]
    if unknown_terms:
        refusal = AcquisitionRefusal(
            card_id=card_id,
            card_name=card_name,
            offer_id=offer.id,
            reason="OFFER_TERMS_INCOMPLETE",
            message=(
                "An approved offer exists for this card, but its published terms do not "
                "state " + ", ".join(unknown_terms) + ", so a new-card assessment "
                "cannot be computed from it."
            ),
            details={"offer_id": offer.id, "unknown_terms": unknown_terms},
        )
        return None, refusal, None

    assert offer.expected_approval_days is not None
    assert offer.expected_card_in_hand_days is not None
    assert offer.annual_fee_minor is not None
    lead_time_days = offer.expected_approval_days + offer.expected_card_in_hand_days
    earliest_usable_date = pt.booking_date + timedelta(days=lead_time_days)
    window_closes_on = earliest_usable_date + timedelta(days=offer.spend_window_days)

    # Gate 1: earliest_usable_date <= first_bookable_spend_date
    if earliest_usable_date > pt.first_bookable_spend_date:
        refusal = AcquisitionRefusal(
            card_id=card_id,
            card_name=card_name,
            offer_id=offer.id,
            reason="TIMING_GATE_FAILED",
            message=(
                f"This card's welcome bonus would need ~{lead_time_days} days' lead "
                "time you don't have (card expected on "
                f"{earliest_usable_date.isoformat()}, after first spend date "
                f"{pt.first_bookable_spend_date.isoformat()})."
            ),
            details={
                "expected_lead_time_days": lead_time_days,
                "earliest_usable_date": earliest_usable_date.isoformat(),
                "first_bookable_spend_date": pt.first_bookable_spend_date.isoformat(),
            },
        )
        return None, refusal, None

    # Gate 3 (optional upfront pruning during multi-card retrieval)
    if check_spend_window_before_optimize:
        latest_payment_date = pt.latest_spend_date or pt.first_bookable_spend_date
        if latest_payment_date > window_closes_on:
            refusal = AcquisitionRefusal(
                card_id=card_id,
                card_name=card_name,
                offer_id=offer.id,
                reason="SPEND_WINDOW_EXCEEDED",
                message=(
                    f"Planned trip spend extends past the offer spend window closing date "
                    f"(spend date {latest_payment_date.isoformat()} is after window closing "
                    f"date {window_closes_on.isoformat()})."
                ),
                details={
                    "latest_payment_date": latest_payment_date.isoformat(),
                    "window_closes_on": window_closes_on.isoformat(),
                },
            )
            return None, refusal, None

    # Currency match
    if offer.currency != costed_trip.home_currency:
        refusal = AcquisitionRefusal(
            card_id=card_id,
            card_name=card_name,
            offer_id=offer.id,
            reason="CURRENCY_MISMATCH",
            message=(
                f"The offer's currency ({offer.currency}) differs from the trip's "
                f"currency ({costed_trip.home_currency}). Amounts are not converted."
            ),
            details={
                "offer_currency": offer.currency,
                "trip_currency": costed_trip.home_currency,
            },
        )
        return None, refusal, None

    # Points bonus without verified points program valuation
    if offer.bonus_points is not None:
        refusal = AcquisitionRefusal(
            card_id=card_id,
            card_name=card_name,
            offer_id=offer.id,
            reason="POINTS_PROGRAM_NOT_ESTABLISHED",
            message=(
                "The bonus is stated in points, but no verified link connects the "
                "offer's points program to this card's point valuation. Without an "
                "established valuation, monetary value cannot be computed and the "
                "suggestion is withheld."
            ),
            details={
                "bonus_points": offer.bonus_points,
                "bonus_currency_id": offer.bonus_currency_id,
            },
        )
        return None, refusal, _limit("POINTS_PROGRAM_NOT_ESTABLISHED")

    assert offer.bonus_flat_minor is not None
    return (
        CandidatePreGateContext(
            card_id=card_id,
            card_name=card_name,
            offer=offer,
            lead_time_days=lead_time_days,
            earliest_usable_date=earliest_usable_date,
            window_closes_on=window_closes_on,
            bonus_value_minor=offer.bonus_flat_minor,
            annual_fee_minor=offer.annual_fee_minor,
        ),
        None,
        None,
    )


def evaluate_exact_candidate(
    *,
    ctx: CandidatePreGateContext,
    as_of: date,
    kb: KnowledgeBase,
    plan: StoredPlan,
    costed_trip: CostedTrip,
    stored_card_ids: list[str],
    held_benefit_minor: int,
    pt: PaymentTimingIn,
) -> tuple[AcquisitionSuggestion | None, AcquisitionRefusal | None]:
    """Run exact ``optimize(wallet + candidate)`` and enforce Gates 2, 3, and 4."""
    offer = ctx.offer
    card_id = ctx.card_id
    card_name = ctx.card_name

    existing_points_balances = (
        plan.planned_wallet.points_balances if plan.planned_wallet else {}
    )
    candidate_wallet = UserWallet(
        card_ids=[*stored_card_ids, card_id],
        points_balances=existing_points_balances,
    )
    candidate_result = optimize(
        costed_trip,
        candidate_wallet,
        kb,
        plan.optimization_prefs,
    )

    candidate_benefit = (
        candidate_result.discounts_minor
        + candidate_result.rewards_value_minor
        - candidate_result.forex_fees_minor
    )
    trip_earn_delta_minor = candidate_benefit - held_benefit_minor

    candidate_assignments = [a for a in candidate_result.assignments if a.card_id == card_id]
    trip_eligible_spend_minor = sum(
        max(0, a.line.amount_minor - sum(o.discount_minor for o in a.offers_applied))
        for a in candidate_assignments
    )

    # Gate 2: min_spend_minor <= trip_eligible_spend_minor
    if trip_eligible_spend_minor < offer.min_spend_minor:
        return None, AcquisitionRefusal(
            card_id=card_id,
            card_name=card_name,
            offer_id=offer.id,
            reason="MINIMUM_SPEND_NOT_MET",
            message=(
                f"Eligible trip spend assigned to this card "
                f"({format_money(trip_eligible_spend_minor, offer.currency)}) "
                f"is less than the required minimum spend "
                f"({format_money(offer.min_spend_minor, offer.currency)})."
            ),
            details={
                "trip_eligible_spend_minor": trip_eligible_spend_minor,
                "min_spend_minor": offer.min_spend_minor,
            },
        )

    # Gate 3: all trip spend counted in (2) falls on or before window_closes_on
    latest_payment_date = pt.latest_spend_date or pt.first_bookable_spend_date
    spend_within_window = latest_payment_date <= ctx.window_closes_on
    if not spend_within_window:
        return None, AcquisitionRefusal(
            card_id=card_id,
            card_name=card_name,
            offer_id=offer.id,
            reason="SPEND_WINDOW_EXCEEDED",
            message=(
                f"Planned trip spend extends past the offer spend window closing date "
                f"(spend date {latest_payment_date.isoformat()} is after window closing "
                f"date {ctx.window_closes_on.isoformat()})."
            ),
            details={
                "latest_payment_date": latest_payment_date.isoformat(),
                "window_closes_on": ctx.window_closes_on.isoformat(),
            },
        )

    # Gate 4: net_first_year_minor > 0
    net_first_year_minor = ctx.bonus_value_minor + trip_earn_delta_minor - ctx.annual_fee_minor
    if net_first_year_minor <= 0:
        return None, AcquisitionRefusal(
            card_id=card_id,
            card_name=card_name,
            offer_id=offer.id,
            reason="NONPOSITIVE_NET_VALUE",
            message=(
                f"Net first-year value "
                f"({format_money(net_first_year_minor, offer.currency)}) is not "
                f"greater than zero (bonus value "
                f"{format_money(ctx.bonus_value_minor, offer.currency)} + "
                f"incremental rewards "
                f"{format_money(trip_earn_delta_minor, offer.currency)} - annual fee "
                f"{format_money(ctx.annual_fee_minor, offer.currency)} <= 0)."
            ),
            details={
                "net_first_year_minor": net_first_year_minor,
                "bonus_value_minor": ctx.bonus_value_minor,
                "trip_earn_delta_minor": trip_earn_delta_minor,
                "annual_fee_minor": ctx.annual_fee_minor,
            },
        )

    timing_assessment = CandidateTimingAssessment(
        booking_date=pt.booking_date,
        first_bookable_spend_date=pt.first_bookable_spend_date,
        latest_spend_date=pt.latest_spend_date,
        expected_lead_time_days=ctx.lead_time_days,
        earliest_usable_date=ctx.earliest_usable_date,
        window_closes_on=ctx.window_closes_on,
        lead_time_sufficient=True,
        spend_within_window=True,
    )

    framing = (
        f"This card's current welcome bonus would be worth "
        f"{format_money(net_first_year_minor, offer.currency)} on this trip if you held it"
    )

    assert offer.eligibility_exclusions is not None
    suggestion = AcquisitionSuggestion(
        card_id=card_id,
        card_name=card_name,
        offer=acquisition_offer_out(offer),
        verbatim_framing=framing,
        timing=timing_assessment,
        trip_eligible_spend_minor=trip_eligible_spend_minor,
        min_spend_minor=offer.min_spend_minor,
        bonus_value_minor=ctx.bonus_value_minor,
        trip_earn_delta_minor=trip_earn_delta_minor,
        annual_fee_minor=ctx.annual_fee_minor,
        net_first_year_minor=net_first_year_minor,
        currency=offer.currency,
        eligibility_exclusions=list(offer.eligibility_exclusions),
        assumptions=acquisition_assumptions(as_of, pt),
    )
    return suggestion, None


# --------------------------------------------------------------------------- #
# Pure-Integer Sound Upper Bound UB(c | W)                                    #
# --------------------------------------------------------------------------- #


def _cmp_rate_tiers(
    a: tuple[int, int, int | None], b: tuple[int, int, int | None]
) -> int:
    """Sort descending by marginal earn rate ``points / per_amount_minor``."""
    lhs = a[0] * b[1]
    rhs = b[0] * a[1]
    if lhs != rhs:
        return -1 if lhs > rhs else 1
    # Deterministic tie-break: uncapped before capped, larger capacity first
    a_cap = a[2] if a[2] is not None else -1
    b_cap = b[2] if b[2] is not None else -1
    if (a[2] is None) != (b[2] is None):
        return -1 if a[2] is None else 1
    if a_cap != b_cap:
        return -1 if a_cap > b_cap else 1
    return 0


def _max_earn_points_ub(
    post_minor: int,
    sorted_rules: list[RewardRule],
    base_earn: EarnRate,
    *,
    force_fractional: bool = False,
) -> int:
    """Sound integer upper bound on points earned across ANY pool balance state.

    When all matching rules are uncapped and evaluating full spend (``force_fractional=False``),
    ``earn_schedule`` does not read ``pool_balances`` and is exact. Whenever any rule has a
    cap (or when bounding uncapped fallback over unknown remaining spend ``post' <= post``),
    fractional knapsack relaxation over ``(rules + [base_earn])`` guarantees ``UB >= actual``
    despite cap-fallthrough remainders or non-monotonic rule/base earn rates.
    """
    if post_minor <= 0:
        return 0

    has_capped = any(r.cap is not None for r in sorted_rules)
    if not has_capped and not force_fractional:
        return earn_schedule(post_minor, sorted_rules, base_earn, {}).total_points

    tiers: list[tuple[int, int, int | None]] = []
    for r in sorted_rules:
        if r.earn.per_amount_minor <= 0 or r.earn.points <= 0:
            continue
        if r.cap is None:
            tiers.append((r.earn.points, r.earn.per_amount_minor, None))
        else:
            max_blocks = max(0, r.cap.max_points // r.earn.points)
            cap_spend = max_blocks * r.earn.per_amount_minor
            if cap_spend > 0:
                tiers.append((r.earn.points, r.earn.per_amount_minor, cap_spend))
    if base_earn.per_amount_minor > 0 and base_earn.points > 0:
        tiers.append((base_earn.points, base_earn.per_amount_minor, None))

    tiers.sort(key=cmp_to_key(_cmp_rate_tiers))
    remaining = post_minor
    total_frac = Fraction(0)
    for pts, per, max_spend in tiers:
        if remaining <= 0:
            break
        take = remaining if max_spend is None else min(remaining, max_spend)
        if take > 0:
            total_frac += Fraction(take * pts, per)
            remaining -= take
        if max_spend is None:
            break
    return int(total_frac)


def _line_card_benefit_ub(
    *,
    line: SpendLineItem,
    card: Card,
    kb: KnowledgeBase,
    matched_offers_by_channel: Mapping[Channel, list[Offer]],
    on_date_by_channel: Mapping[Channel, date],
    uncapped_only: bool = False,
) -> tuple[int, bool]:
    """Compute sound single-line upper bound on benefit for ``(card, line)``.

    Returns ``(max_benefit_minor, touched_any_capped_rule)``.
    If ``line.available_channels`` is empty, returns ``(0, False)`` matching cash-only.
    """
    if not line.available_channels:
        return 0, False

    val = kb.best_valuation(card.id)
    value_micro = val[0] if val is not None else 0

    best_benefit: int | None = None
    touched_capped = False

    for channel in line.available_channels:
        on_date = on_date_by_channel[channel]
        all_rules = matching_rules(kb, line, card, channel, on_date)
        if any(r.cap is not None for r in all_rules):
            touched_capped = True
        rules = [r for r in all_rules if r.cap is None] if uncapped_only else all_rules

        raw_offers = matched_offers_by_channel.get(channel, [])
        eligible = [
            o
            for o in raw_offers
            if card_eligible(o, card)
            and (o.min_txn_minor is None or line.amount_minor >= o.min_txn_minor)
        ]

        seen_discounts: set[int] = set()
        subsets = offer_subsets(eligible)
        for subset in subsets:
            discount, _ = apply_offer_subset(line.amount_minor, subset)
            if discount in seen_discounts:
                continue
            seen_discounts.add(discount)

            post = line.amount_minor - discount
            pts_ub = _max_earn_points_ub(
                post,
                rules,
                card.base_earn,
                force_fractional=uncapped_only,
            )
            pv_ub = points_value_minor(pts_ub, value_micro)
            fee = (
                forex_fee_minor(post, card.forex_markup_bp, card.forex_markup_tax_bp)
                if channel == Channel.POS_ABROAD
                else 0
            )
            benefit = discount + pv_ub - fee
            if best_benefit is None or benefit > best_benefit:
                best_benefit = benefit

    return (0 if best_benefit is None else best_benefit), touched_capped


@dataclass(frozen=True)
class PrecomputedWalletBaseline:
    """Precomputed baseline across held wallet W to avoid redundant work per candidate."""

    total_trip_spend_minor: int
    held_benefit_minor: int
    line_baseline_ub_minor: dict[str, int]
    line_held_benefit_minor: dict[str, int]
    total_held_slack_minor: int
    on_date_by_channel: dict[Channel, date]
    matched_offers_by_line_channel: dict[str, dict[Channel, list[Offer]]]


def build_wallet_baseline(
    *,
    kb: KnowledgeBase,
    costed_trip: CostedTrip,
    held_benefit_minor: int,
    stored_line_benefits: Mapping[str, int],
    held_card_ids: list[str],
) -> PrecomputedWalletBaseline:
    """Precompute per-line held-wallet benefit UBs and candidate-offer buckets once per trip."""
    on_date_by_channel: dict[Channel, date] = {
        ch: (costed_trip.trip_start_date if ch in POS_CHANNELS else costed_trip.booking_date)
        for ch in Channel
    }

    matched_offers: dict[str, dict[Channel, list[Offer]]] = {}
    line_baseline_ub: dict[str, int] = {}
    line_held_benefit: dict[str, int] = {}
    total_slack = 0
    total_trip_spend = 0

    for line in costed_trip.lines:
        total_trip_spend += line.amount_minor
        by_ch: dict[Channel, list[Offer]] = {}
        for ch in line.available_channels:
            raw = kb.offers_matching(
                line.merchant_hint, ch, line.category, on_date_by_channel[ch]
            )
            by_ch[ch] = [o for o in raw if o.kind == OfferKind.INSTANT_DISCOUNT]
        matched_offers[line.id] = by_ch

        # Cash-only is always available as a 0-benefit baseline floor
        ub_w = 0
        for held_id in held_card_ids:
            if not kb.has_card(held_id):
                continue
            b_ub, _ = _line_card_benefit_ub(
                line=line,
                card=kb.card(held_id),
                kb=kb,
                matched_offers_by_channel=by_ch,
                on_date_by_channel=on_date_by_channel,
                uncapped_only=False,
            )
            if b_ub > ub_w:
                ub_w = b_ub

        held_b = stored_line_benefits.get(line.id, 0)
        line_held_benefit[line.id] = held_b
        line_baseline_ub[line.id] = ub_w
        if ub_w > held_b:
            total_slack += ub_w - held_b

    return PrecomputedWalletBaseline(
        total_trip_spend_minor=total_trip_spend,
        held_benefit_minor=held_benefit_minor,
        line_baseline_ub_minor=line_baseline_ub,
        line_held_benefit_minor=line_held_benefit,
        total_held_slack_minor=total_slack,
        on_date_by_channel=on_date_by_channel,
        matched_offers_by_line_channel=matched_offers,
    )


@dataclass(frozen=True)
class CandidateUpperBound:
    """Sound additive upper bound for a candidate card ``c`` over held wallet ``W``."""

    card_id: str
    ctx: CandidatePreGateContext
    upper_bound_net_minor: int
    earn_delta_ub_minor: int


def compute_card_upper_bound(
    *,
    kb: KnowledgeBase,
    card: Card,
    ctx: CandidatePreGateContext,
    costed_trip: CostedTrip,
    baseline: PrecomputedWalletBaseline,
    milestone_bonus_minor: int = 0,
) -> CandidateUpperBound:
    """Compute sound pure-integer upper bound ``UB(c | W)``."""
    per_line_excess_sum = 0
    uncapped_excess_sum = 0
    capped_lines_count = 0

    for line in costed_trip.lines:
        by_ch = baseline.matched_offers_by_line_channel[line.id]
        ub_w = baseline.line_baseline_ub_minor[line.id]

        line_ub, touched_capped = _line_card_benefit_ub(
            line=line,
            card=card,
            kb=kb,
            matched_offers_by_channel=by_ch,
            on_date_by_channel=baseline.on_date_by_channel,
            uncapped_only=False,
        )
        if line_ub > ub_w:
            per_line_excess_sum += line_ub - ub_w

        if touched_capped:
            capped_lines_count += 1
            base_ub, _ = _line_card_benefit_ub(
                line=line,
                card=card,
                kb=kb,
                matched_offers_by_channel=by_ch,
                on_date_by_channel=baseline.on_date_by_channel,
                uncapped_only=True,
            )
            if base_ub > ub_w:
                uncapped_excess_sum += base_ub - ub_w
        else:
            if line_ub > ub_w:
                uncapped_excess_sum += line_ub - ub_w

    # Trip-wide shared-pool bound prevents double-counting scarce capped pools across lines
    if capped_lines_count > 0:
        pool_caps: dict[str, int] = {}
        for r in kb.rules_for_card(card.id):
            if r.cap is None:
                continue
            key = pool_key(r)
            assert key is not None
            pool_caps[key] = min(pool_caps.get(key, r.cap.max_points), r.cap.max_points)

        val = kb.best_valuation(card.id)
        value_micro = val[0] if val is not None else 0
        total_pool_pts_cap = sum(pool_caps.values())
        pool_bonus_minor = points_value_minor(total_pool_pts_cap, value_micro)
        trip_pool_bound = uncapped_excess_sum + pool_bonus_minor + capped_lines_count
        earn_delta_ub = baseline.total_held_slack_minor + min(per_line_excess_sum, trip_pool_bound)
    else:
        earn_delta_ub = baseline.total_held_slack_minor + per_line_excess_sum

    upper_bound_net = (
        ctx.bonus_value_minor + milestone_bonus_minor + earn_delta_ub - ctx.annual_fee_minor
    )
    return CandidateUpperBound(
        card_id=ctx.card_id,
        ctx=ctx,
        upper_bound_net_minor=upper_bound_net,
        earn_delta_ub_minor=earn_delta_ub,
    )


# --------------------------------------------------------------------------- #
# Lazy Max-Heap Zero-Bias Top-M Candidate Retrieval                           #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RetrievalStats:
    """Diagnostic statistics proving lazy pruning efficiency without changing API models."""

    total_catalog_cards: int
    hard_filtered_out: int
    nonpositive_ub_pruned: int
    exact_evaluations: int
    heap_pruned: int
    ub_pruned_ratio_bp: int


@dataclass(frozen=True)
class RetrievalResult:
    """Output of zero-bias lazy max-heap candidate retrieval."""

    suggestions: list[AcquisitionSuggestion]
    evaluated_refusals: list[AcquisitionRefusal]
    hard_filtered_refusals: list[AcquisitionRefusal]
    limitations: list[Limitation]
    stats: RetrievalStats


def retrieve_top_candidates(
    *,
    as_of: date,
    kb: KnowledgeBase,
    catalog: OfferCatalog,
    plan: StoredPlan,
    user_held_card_ids: set[str],
    payment_timing: PaymentTimingIn | None,
    top_m: int | None = None,
    home_country: Literal["IN", "AE", "US"] | None = None,
    closed_card_ids: set[str] | None = None,
    open_card_ids: set[str] | None = None,
    milestone_bonus_by_card: Mapping[str, int] | None = None,
    on_exact_evaluate: Callable[[str], None] | None = None,
) -> RetrievalResult:
    """Retrieve exact top-m single-card acquisition recommendations without bias.

    Stage 1: Hard eligibility filter (already held, ``home_country``, ``open_for_application``,
             valid approved offer, ``payment_timing``, Gate 1 lead time, Gate 3 spend window,
             Gate 5 expiry, currency match, points mapping, ``min_spend <= total_trip_spend``).
    Stage 2: Compute sound integer upper bound ``UB(c | W)`` and discard ``UB <= 0``.
    Stage 3: Lazy max-heap (``heapq``) over ``(-UB, card_id)``: pop highest ``UB``, run exact
             ``optimize(W + c)``, and halt immediately when ``next_UB < threshold_m``
             (strictly below the ``m``-th best exact ``net_first_year_minor`` found).
    """
    assert plan.costed_trip is not None
    assert plan.optimizer_result is not None
    costed_trip = plan.costed_trip
    stored_result = plan.optimizer_result
    stored_card_ids = list(plan.planned_wallet_card_ids)
    all_held_ids = user_held_card_ids | set(stored_card_ids)

    held_benefit = (
        stored_result.discounts_minor
        + stored_result.rewards_value_minor
        - stored_result.forex_fees_minor
    )
    stored_line_benefits = {
        a.line.id: a.benefit_minor for a in stored_result.assignments
    }

    unheld_cards = [c for c in kb.cards() if c.id not in all_held_ids]
    total_catalog_cards = len(unheld_cards)

    if top_m is not None and top_m <= 0:
        return RetrievalResult(
            suggestions=[],
            evaluated_refusals=[],
            hard_filtered_refusals=[],
            limitations=[],
            stats=RetrievalStats(
                total_catalog_cards=total_catalog_cards,
                hard_filtered_out=0,
                nonpositive_ub_pruned=0,
                exact_evaluations=0,
                heap_pruned=0,
                ub_pruned_ratio_bp=10_000 if total_catalog_cards > 0 else 0,
            ),
        )

    baseline = build_wallet_baseline(
        kb=kb,
        costed_trip=costed_trip,
        held_benefit_minor=held_benefit,
        stored_line_benefits=stored_line_benefits,
        held_card_ids=stored_card_ids,
    )

    hard_filtered_refusals: list[AcquisitionRefusal] = []
    limitations: list[Limitation] = []
    seen_lim_codes: set[str] = set()

    if payment_timing is None:
        limitations.append(_limit("PAYMENT_TIMING_UNKNOWN"))
        seen_lim_codes.add("PAYMENT_TIMING_UNKNOWN")

    closed = closed_card_ids or set()
    milestones = milestone_bonus_by_card or {}

    hard_filtered_out = 0
    nonpositive_ub_pruned = 0

    # Min-heap of (-upper_bound_net_minor, card_id, CandidateUpperBound)
    heap: list[tuple[int, str, CandidateUpperBound]] = []

    for card in unheld_cards:
        if card.id in closed or (open_card_ids is not None and card.id not in open_card_ids):
            hard_filtered_out += 1
            continue
        if home_country is not None and card.country != home_country:
            hard_filtered_out += 1
            continue

        ctx, pre_refusal, pre_lim = check_pre_optimize_gates(
            card_id=card.id,
            card_name=card.name,
            as_of=as_of,
            costed_trip=costed_trip,
            catalog=catalog,
            pt=payment_timing,
            check_spend_window_before_optimize=True,
        )
        if pre_lim is not None and pre_lim.code not in seen_lim_codes:
            seen_lim_codes.add(pre_lim.code)
            limitations.append(pre_lim)
        if pre_refusal is not None or ctx is None:
            hard_filtered_out += 1
            if pre_refusal is not None and pre_refusal.offer_id is not None:
                hard_filtered_refusals.append(pre_refusal)
            continue

        # Hard filter: min_spend_minor <= total_eligible_trip_spend
        if ctx.offer.min_spend_minor > baseline.total_trip_spend_minor:
            hard_filtered_out += 1
            hard_filtered_refusals.append(
                AcquisitionRefusal(
                    card_id=card.id,
                    card_name=card.name,
                    offer_id=ctx.offer.id,
                    reason="MINIMUM_SPEND_NOT_MET",
                    message=(
                        f"Total trip spend "
                        f"({format_money(baseline.total_trip_spend_minor, ctx.offer.currency)}) "
                        f"is less than the required minimum spend "
                        f"({format_money(ctx.offer.min_spend_minor, ctx.offer.currency)})."
                    ),
                    details={
                        "trip_eligible_spend_minor": baseline.total_trip_spend_minor,
                        "min_spend_minor": ctx.offer.min_spend_minor,
                    },
                )
            )
            continue

        ub_obj = compute_card_upper_bound(
            kb=kb,
            card=card,
            ctx=ctx,
            costed_trip=costed_trip,
            baseline=baseline,
            milestone_bonus_minor=milestones.get(card.id, 0),
        )

        # Since Gate 4 requires net_first_year_minor > 0, UB <= 0 can never pass
        if ub_obj.upper_bound_net_minor <= 0:
            nonpositive_ub_pruned += 1
            continue

        heapq.heappush(heap, (-ub_obj.upper_bound_net_minor, card.id, ub_obj))

    assert payment_timing is not None or not heap, "heap must be empty when payment_timing is None"

    qualifying: list[AcquisitionSuggestion] = []
    evaluated_refusals: list[AcquisitionRefusal] = []
    exact_evaluations = 0
    heap_pruned = 0

    while heap:
        neg_ub, card_id, ub_obj = heapq.heappop(heap)
        ub = -neg_ub

        if top_m is not None and len(qualifying) >= top_m:
            mth_best = qualifying[top_m - 1].net_first_year_minor
            if ub < mth_best:
                heap_pruned = len(heap) + 1
                break

        if on_exact_evaluate is not None:
            on_exact_evaluate(card_id)
        exact_evaluations += 1

        assert payment_timing is not None
        suggestion, refusal = evaluate_exact_candidate(
            ctx=ub_obj.ctx,
            as_of=as_of,
            kb=kb,
            plan=plan,
            costed_trip=costed_trip,
            stored_card_ids=stored_card_ids,
            held_benefit_minor=held_benefit,
            pt=payment_timing,
        )
        if suggestion is not None:
            qualifying.append(suggestion)
            qualifying.sort(key=lambda s: (-s.net_first_year_minor, s.card_id))
        elif refusal is not None:
            evaluated_refusals.append(refusal)

    final_suggestions = qualifying[:top_m] if top_m is not None else qualifying
    skipped = max(0, total_catalog_cards - exact_evaluations)
    ratio_bp = skipped * 10_000 // total_catalog_cards if total_catalog_cards > 0 else 0

    return RetrievalResult(
        suggestions=final_suggestions,
        evaluated_refusals=evaluated_refusals,
        hard_filtered_refusals=hard_filtered_refusals,
        limitations=limitations,
        stats=RetrievalStats(
            total_catalog_cards=total_catalog_cards,
            hard_filtered_out=hard_filtered_out,
            nonpositive_ub_pruned=nonpositive_ub_pruned,
            exact_evaluations=exact_evaluations,
            heap_pruned=heap_pruned,
            ub_pruned_ratio_bp=ratio_bp,
        ),
    )
