"""Card acquisition assessment (spec 18 §3-5, Case B).

Pure and deterministic: no network, no clock (``as_of`` passed in), no LLM.
It evaluates unheld card welcome offers against a stored trip revision.
Invariants enforced:
- The existing held-card strategy is unchanged and returned in full.
- Incremental trip benefit is computed by running the existing optimizer twice
  (wallet vs wallet + candidate). No parallel reward calculator is written.
- All 5 gates from spec 18 §4 are enforced fail-closed:
  1. earliest_usable_date <= first_bookable_spend_date
  2. min_spend_minor <= trip_eligible_spend_minor
  3. all trip spend counted in (2) falls on or before window_closes_on
  4. net_first_year_minor > 0
  5. offer.valid_to >= booking_date
- Requires explicit payment-timing inputs. Travel dates are not payment dates.
- Points bonuses require an established valuation mapping; unestablished points bonuses
  are withheld with a typed limitation.
- Informational framing only:
  "This card's current welcome bonus would be worth ₹X on this trip if you held it".
  Never "you should apply".
- Eligibility exclusions are rendered verbatim.
- No affiliate links, applications, credit checks, or enrollment.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from core.db import KnowledgeBase
from core.models import UserWallet
from core.optimizer import optimize
from welcome.catalog import OfferCatalog, verification_status
from welcome.models import (
    AcquisitionAssessmentIn,
    AcquisitionAssessmentReport,
    AcquisitionOfferOut,
    AcquisitionRefusal,
    AcquisitionRefusalReason,
    AcquisitionSuggestion,
    CandidateTimingAssessment,
    CardAcquisitionOffer,
    HeldCardsStrategySummary,
    Limitation,
    OfferProvenanceOut,
)
from welcome.status import StoredPlan, StoredPlanUnreadableError, _limit


def format_money(minor: int, currency: str) -> str:
    """Format minor currency units for human-readable sentences without floats."""
    symbol = "₹" if currency == "INR" else f"{currency} "
    negative = minor < 0
    abs_major = abs(minor) // 100
    formatted = f"{symbol}{abs_major:,}"
    return f"-{formatted}" if negative else formatted


def _acquisition_offer_out(offer: CardAcquisitionOffer) -> AcquisitionOfferOut:
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


def compute_acquisition_assessment(
    *,
    trip_id: str,
    revision: int,
    as_of: date,
    kb: KnowledgeBase,
    catalog: OfferCatalog,
    plan: StoredPlan,
    user_held_card_ids: set[str],
    payload: AcquisitionAssessmentIn,
) -> AcquisitionAssessmentReport:
    """Assess candidate unheld card welcome offers against a stored trip revision."""
    if plan.costed_trip is None or plan.optimizer_result is None:
        raise StoredPlanUnreadableError(
            "stored revision has no readable costed trip or optimizer result"
        )

    stored_result = plan.optimizer_result
    costed_trip = plan.costed_trip
    stored_card_ids = list(plan.planned_wallet_card_ids)

    held_benefit = (
        stored_result.discounts_minor
        + stored_result.rewards_value_minor
        - stored_result.forex_fees_minor
    )
    held_strategy = HeldCardsStrategySummary(
        card_ids=stored_card_ids,
        gross_minor=stored_result.gross_minor,
        discounts_minor=stored_result.discounts_minor,
        rewards_value_minor=stored_result.rewards_value_minor,
        forex_fees_minor=stored_result.forex_fees_minor,
        effective_cost_minor=stored_result.effective_cost_minor,
        total_benefit_minor=held_benefit,
        currency=costed_trip.home_currency,
    )

    limitations: list[Limitation] = []
    suggestions: list[AcquisitionSuggestion] = []
    refusals: list[AcquisitionRefusal] = []

    # Exclude already-held cards appropriately
    all_held_ids = user_held_card_ids | set(stored_card_ids)

    if payload.candidate_card_id is not None:
        cand_id = payload.candidate_card_id
        if cand_id in all_held_ids:
            refusals.append(
                AcquisitionRefusal(
                    card_id=cand_id,
                    card_name=kb.card(cand_id).name if kb.has_card(cand_id) else None,
                    offer_id=None,
                    reason="ALREADY_HELD_CARD",
                    message=(
                        "This card is already held in your wallet; welcome window tracking "
                        "for held cards is handled under held-card welcome status."
                    ),
                    details={"candidate_card_id": cand_id},
                )
            )
            return AcquisitionAssessmentReport(
                trip_id=trip_id,
                revision=revision,
                as_of=as_of,
                held_cards_strategy=held_strategy,
                suggestions=[],
                refusals=refusals,
                limitations=limitations,
                assumptions=_acquisition_assumptions(as_of, None),
            )
        candidate_ids = [cand_id]
    else:
        candidate_ids = [c.id for c in kb.cards() if c.id not in all_held_ids]

    approved_in_catalog = catalog.approved_offers()
    if not approved_in_catalog and payload.candidate_card_id is None:
        limitations.append(_limit("NO_APPROVED_OFFER"))
        return AcquisitionAssessmentReport(
            trip_id=trip_id,
            revision=revision,
            as_of=as_of,
            held_cards_strategy=held_strategy,
            suggestions=[],
            refusals=[],
            limitations=limitations,
            assumptions=_acquisition_assumptions(as_of, None),
        )

    pt = payload.payment_timing
    if pt is None:
        limitations.append(_limit("PAYMENT_TIMING_UNKNOWN"))

    for card_id in candidate_ids:
        card_obj = kb.card(card_id) if kb.has_card(card_id) else None
        card_name = card_obj.name if card_obj else None

        booking_date = pt.booking_date if pt is not None else as_of
        selection = catalog.select_acquisition_offer(card_id, booking_date)

        if selection.offer is None:
            if payload.candidate_card_id is not None:
                sel_reason = selection.reason or "NO_APPROVED_OFFER"
                ref_reason: AcquisitionRefusalReason
                if sel_reason == "OFFER_NOT_IN_FORCE_AT_OPEN_DATE":
                    ref_reason = "OFFER_EXPIRED"
                elif sel_reason == "AMBIGUOUS_OFFER":
                    ref_reason = "AMBIGUOUS_OFFER"
                else:
                    ref_reason = "NO_APPROVED_OFFER"
                refusals.append(
                    AcquisitionRefusal(
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
                )
            continue

        offer = selection.offer

        if pt is None:
            refusals.append(
                AcquisitionRefusal(
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
            )
            continue

        # Gate 5: offer.valid_to >= booking_date
        if offer.valid_to < pt.booking_date:
            refusals.append(
                AcquisitionRefusal(
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
            )
            continue

        lead_time_days = offer.expected_approval_days + offer.expected_card_in_hand_days
        earliest_usable_date = pt.booking_date + timedelta(days=lead_time_days)
        window_closes_on = earliest_usable_date + timedelta(days=offer.spend_window_days)

        # Gate 1: earliest_usable_date <= first_bookable_spend_date
        if earliest_usable_date > pt.first_bookable_spend_date:
            refusals.append(
                AcquisitionRefusal(
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
            )
            continue

        # Currency match
        if offer.currency != costed_trip.home_currency:
            refusals.append(
                AcquisitionRefusal(
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
            )
            continue

        # Points bonus without verified points program valuation
        if offer.bonus_points is not None:
            refusals.append(
                AcquisitionRefusal(
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
            )
            limitations.append(_limit("POINTS_PROGRAM_NOT_ESTABLISHED"))
            continue

        assert offer.bonus_flat_minor is not None
        bonus_value_minor = offer.bonus_flat_minor

        # Compute incremental trip benefit using the existing optimizer
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
        trip_earn_delta_minor = candidate_benefit - held_benefit

        candidate_assignments = [
            a for a in candidate_result.assignments if a.card_id == card_id
        ]
        trip_eligible_spend_minor = sum(
            max(0, a.line.amount_minor - sum(o.discount_minor for o in a.offers_applied))
            for a in candidate_assignments
        )

        # Gate 2: min_spend_minor <= trip_eligible_spend_minor
        if trip_eligible_spend_minor < offer.min_spend_minor:
            refusals.append(
                AcquisitionRefusal(
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
            )
            continue

        # Gate 3: all trip spend counted in (2) falls on or before window_closes_on
        latest_payment_date = pt.latest_spend_date or pt.first_bookable_spend_date
        spend_within_window = latest_payment_date <= window_closes_on
        if not spend_within_window:
            refusals.append(
                AcquisitionRefusal(
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
            )
            continue

        # Gate 4: net_first_year_minor > 0
        annual_fee_minor = offer.annual_fee_minor
        net_first_year_minor = (
            bonus_value_minor + trip_earn_delta_minor - annual_fee_minor
        )
        if net_first_year_minor <= 0:
            refusals.append(
                AcquisitionRefusal(
                    card_id=card_id,
                    card_name=card_name,
                    offer_id=offer.id,
                    reason="NONPOSITIVE_NET_VALUE",
                    message=(
                        f"Net first-year value "
                        f"({format_money(net_first_year_minor, offer.currency)}) is not "
                        f"greater than zero (bonus value "
                        f"{format_money(bonus_value_minor, offer.currency)} + "
                        f"incremental rewards "
                        f"{format_money(trip_earn_delta_minor, offer.currency)} - annual fee "
                        f"{format_money(annual_fee_minor, offer.currency)} <= 0)."
                    ),
                    details={
                        "net_first_year_minor": net_first_year_minor,
                        "bonus_value_minor": bonus_value_minor,
                        "trip_earn_delta_minor": trip_earn_delta_minor,
                        "annual_fee_minor": annual_fee_minor,
                    },
                )
            )
            continue

        # All 5 gates passed! Create suggestion with required informational framing.
        timing_assessment = CandidateTimingAssessment(
            booking_date=pt.booking_date,
            first_bookable_spend_date=pt.first_bookable_spend_date,
            latest_spend_date=pt.latest_spend_date,
            expected_lead_time_days=lead_time_days,
            earliest_usable_date=earliest_usable_date,
            window_closes_on=window_closes_on,
            lead_time_sufficient=True,
            spend_within_window=True,
        )

        framing = (
            f"This card's current welcome bonus would be worth "
            f"{format_money(net_first_year_minor, offer.currency)} on this trip if you held it"
        )

        suggestions.append(
            AcquisitionSuggestion(
                card_id=card_id,
                card_name=card_name,
                offer=_acquisition_offer_out(offer),
                verbatim_framing=framing,
                timing=timing_assessment,
                trip_eligible_spend_minor=trip_eligible_spend_minor,
                min_spend_minor=offer.min_spend_minor,
                bonus_value_minor=bonus_value_minor,
                trip_earn_delta_minor=trip_earn_delta_minor,
                annual_fee_minor=annual_fee_minor,
                net_first_year_minor=net_first_year_minor,
                currency=offer.currency,
                eligibility_exclusions=list(offer.eligibility_exclusions),
                assumptions=_acquisition_assumptions(as_of, pt),
            )
        )

    # Deduplicate limitations by code
    seen_limit_codes: set[str] = set()
    unique_limitations: list[Limitation] = []
    for lim in limitations:
        if lim.code not in seen_limit_codes:
            seen_limit_codes.add(lim.code)
            unique_limitations.append(lim)

    return AcquisitionAssessmentReport(
        trip_id=trip_id,
        revision=revision,
        as_of=as_of,
        held_cards_strategy=held_strategy,
        suggestions=suggestions,
        refusals=refusals,
        limitations=unique_limitations,
        assumptions=_acquisition_assumptions(as_of, pt),
    )


def _acquisition_assumptions(as_of: date, pt: Any | None) -> list[str]:
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
