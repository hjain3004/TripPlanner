"""Welcome-window status for a held card (spec 18 §2-3, Case A).

Pure and deterministic: no store, no network, no clock (``as_of`` is passed in), no LLM.
It *reports the consequences of assignments the optimizer already made*. It never
re-runs, re-ranks or adds to the optimizer (spec 02 is frozen) and the welcome bonus is
not added into any plan total.

Honesty rules this module enforces:

* An unknown input stays unknown. A missing ``opened_on`` yields status ``unknown`` and no
  window; a missing prior-spend figure yields no shortfall. Neither becomes a date or 0.
* Travel dates are not payment dates. The plan never observes when money moves, so no
  line is ever called "qualifying" — the strongest claim is ``could_count_if_paid_by_close``
  and the amount is reported as *conditional*.
* Offer terms are used as given and carried with their provenance; nothing is invented.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from core.db import KnowledgeBase
from core.models import Channel, CostedTrip, LineAssignment, OptimizerResult
from core.optimizer.money import points_value_minor
from welcome.catalog import OfferSelection, verification_status
from welcome.models import (
    CLOSING_SOON_DAYS,
    BonusOut,
    CardAcquisitionOffer,
    Limitation,
    LimitationCode,
    OfferOut,
    OfferProvenanceOut,
    TimingAssessment,
    TimingBasis,
    TripLineTiming,
    TripWindow,
    ValuationOut,
    WelcomeStatus,
    WelcomeWindowReport,
)

# Lines paid when the traveler books versus charged at the destination. This is a
# stated assumption about *payment* timing, surfaced verbatim in ``assumptions``.
_ADVANCE_BOOKING = frozenset(
    {Channel.DIRECT_AIRLINE, Channel.DIRECT_HOTEL, Channel.OTA_GENERIC, Channel.BANK_PORTAL}
)

_LIMITATION_MESSAGES: dict[LimitationCode, str] = {
    "NO_APPROVED_OFFER": (
        "No approved welcome-offer terms are available for this card, so the spend "
        "window and bonus cannot be computed."
    ),
    "AMBIGUOUS_OFFER": (
        "More than one approved offer could have applied when this card was opened. "
        "The offer granted to you cannot be determined, so none is assumed."
    ),
    "OFFER_NOT_IN_FORCE_AT_OPEN_DATE": (
        "The approved offer terms for this card had ended before its recorded open "
        "date, so they are not assumed to apply to it."
    ),
    "OPENED_ON_UNKNOWN": (
        "This card has no recorded open date. The window is not guessed from any "
        "other data."
    ),
    "OPENED_ON_IN_FUTURE": (
        "The recorded open date is after today, which cannot be right. The window is "
        "not computed from it."
    ),
    "PRIOR_SPEND_UNKNOWN": (
        "Spend already made on this card in the window was not provided. It is not "
        "assumed to be zero, so the remaining spend cannot be stated."
    ),
    "DUPLICATE_CARD_ENTRIES": (
        "More than one wallet entry holds this card product. The plan assigns spend "
        "to the product, not to one entry, so none of it is attributed here."
    ),
    "CARD_NOT_IN_PLANNED_WALLET": (
        "This card was not in the wallet the stored plan was computed with, so the "
        "plan assigned it no spend."
    ),
    "CURRENCY_MISMATCH": (
        "The plan's spend currency differs from the offer's currency. The amounts "
        "are not converted or compared."
    ),
    "NO_POINT_VALUATION": (
        "No point valuation exists for this card, so the points bonus is not valued."
    ),
    "VALUATION_CURRENCY_MISMATCH": (
        "The point valuation is in a different currency from the offer, so the "
        "points bonus is not valued."
    ),
}


def _limit(code: LimitationCode) -> Limitation:
    return Limitation(code=code, message=_LIMITATION_MESSAGES[code])


# --------------------------------------------------------------------------- #
# Reading the server-owned plan                                                 #
# --------------------------------------------------------------------------- #


class StoredPlanUnreadableError(ValueError):
    """A stored revision lacks the artifacts this feature needs, or they do not parse."""


class _StoredWallet(BaseModel):
    model_config = ConfigDict(extra="ignore")
    card_ids: list[str]


class _StoredTripSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    start_date: date
    end_date: date
    wallet: _StoredWallet


class _StoredArtifacts(BaseModel):
    """The subset of a stored ``FinalReport`` this feature reads; the rest is ignored."""

    model_config = ConfigDict(extra="ignore")
    trip_spec: _StoredTripSpec
    costed_trip: CostedTrip
    optimizer_result: OptimizerResult


@dataclass(frozen=True)
class StoredPlan:
    trip_id: str
    revision: int
    computed_at: str
    trip_start_date: date
    trip_end_date: date
    plan_booking_date: date
    currency: str
    assignments: list[LineAssignment]
    planned_wallet_card_ids: list[str]


def parse_stored_plan(
    *, trip_id: str, revision: int, computed_at: str, report_json: str
) -> StoredPlan:
    """Extract the computed assignments and dates from a stored report, verbatim."""
    try:
        raw: Any = json.loads(report_json)
        artifacts = _StoredArtifacts.model_validate(raw)
    except (ValueError, ValidationError) as exc:
        raise StoredPlanUnreadableError(
            "stored revision has no readable optimizer result"
        ) from exc
    return StoredPlan(
        trip_id=trip_id,
        revision=revision,
        computed_at=computed_at,
        trip_start_date=artifacts.trip_spec.start_date,
        trip_end_date=artifacts.trip_spec.end_date,
        plan_booking_date=artifacts.costed_trip.booking_date,
        currency=artifacts.costed_trip.home_currency,
        assignments=artifacts.optimizer_result.assignments,
        planned_wallet_card_ids=artifacts.trip_spec.wallet.card_ids,
    )


# --------------------------------------------------------------------------- #
# Computation                                                                   #
# --------------------------------------------------------------------------- #


def _status(
    *,
    as_of: date,
    closes_on: date,
    days_remaining: int,
    prior: int | None,
    min_spend: int,
) -> WelcomeStatus:
    if prior is not None and prior >= min_spend:
        return "met"
    if as_of > closes_on:
        return "expired"
    if days_remaining <= CLOSING_SOON_DAYS:
        return "closing_soon"
    return "active"


def _assess(
    *,
    basis: TimingBasis,
    plan: StoredPlan,
    opened_on: date | None,
    closes_on: date | None,
    as_of: date,
    line_currency: str,
    offer_currency: str | None,
    ambiguous_entry: bool,
) -> TimingAssessment:
    if ambiguous_entry:
        return "ambiguous_card_entry"
    if opened_on is None or closes_on is None or offer_currency is None:
        return "window_unknown"
    if line_currency != offer_currency:
        return "currency_mismatch"
    if basis == "advance_booking":
        # Paid when the traveler books. The booking date is theirs to choose, so the
        # only thing known is whether today is still inside the window.
        return "could_count_if_paid_by_close" if as_of <= closes_on else "outside_window"
    start, end = plan.trip_start_date, plan.trip_end_date
    if end < opened_on or start > closes_on:
        return "outside_window"
    if opened_on <= start and end <= closes_on:
        return "could_count_if_paid_by_close"
    return "straddles_window_unknown"


def _value_bonus(
    offer: CardAcquisitionOffer, kb: KnowledgeBase
) -> tuple[BonusOut, list[Limitation]]:
    limits: list[Limitation] = []
    if offer.bonus_flat_minor is not None:
        return (
            BonusOut(
                bonus_points=None,
                bonus_flat_minor=offer.bonus_flat_minor,
                bonus_value_minor=offer.bonus_flat_minor,
                currency=offer.currency,
                valuation=None,
            ),
            limits,
        )
    assert offer.bonus_points is not None  # the model guarantees exactly one bonus kind
    valuation = kb.best_valuation_obj(offer.card_id) if kb.has_card(offer.card_id) else None
    value_minor: int | None = None
    shown: ValuationOut | None = None
    if valuation is None:
        limits.append(_limit("NO_POINT_VALUATION"))
    else:
        shown = ValuationOut(
            valuation_id=valuation.id,
            path=valuation.path.value,
            value_micro_major_per_point=valuation.value_micro_major_per_point,
            currency=valuation.currency,
            conditions=valuation.conditions,
            needs_verification=valuation.provenance.needs_verification,
            verified_by=valuation.provenance.verified_by,
        )
        if valuation.currency != offer.currency:
            limits.append(_limit("VALUATION_CURRENCY_MISMATCH"))
        else:
            value_minor = points_value_minor(
                offer.bonus_points, valuation.value_micro_major_per_point
            )
    return (
        BonusOut(
            bonus_points=offer.bonus_points,
            bonus_flat_minor=None,
            bonus_value_minor=value_minor,
            currency=offer.currency,
            valuation=shown,
        ),
        limits,
    )


def _offer_out(offer: CardAcquisitionOffer) -> OfferOut:
    prov = offer.provenance
    return OfferOut(
        id=offer.id,
        title=offer.title,
        bonus_points=offer.bonus_points,
        bonus_currency_id=offer.bonus_currency_id,
        bonus_flat_minor=offer.bonus_flat_minor,
        min_spend_minor=offer.min_spend_minor,
        spend_window_days=offer.spend_window_days,
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


def compute_welcome_status(
    *,
    wallet_entry_id: str,
    card_id: str,
    opened_on: date | None,
    kb: KnowledgeBase,
    selection: OfferSelection,
    plan: StoredPlan,
    as_of: date,
    prior_spend_minor: int | None,
    duplicate_card_entries: bool,
) -> WelcomeWindowReport:
    offer = selection.offer
    limits: list[Limitation] = []
    if selection.reason is not None:
        limits.append(_limit(selection.reason))
    if opened_on is None:
        limits.append(_limit("OPENED_ON_UNKNOWN"))
    elif opened_on > as_of:
        limits.append(_limit("OPENED_ON_IN_FUTURE"))
    if duplicate_card_entries:
        limits.append(_limit("DUPLICATE_CARD_ENTRIES"))
    if card_id not in plan.planned_wallet_card_ids:
        limits.append(_limit("CARD_NOT_IN_PLANNED_WALLET"))

    window_known = offer is not None and opened_on is not None and opened_on <= as_of
    closes_on: date | None = None
    days_remaining: int | None = None
    status: WelcomeStatus = "unknown"
    if offer is not None and window_known:
        assert opened_on is not None
        closes_on = opened_on + timedelta(days=offer.spend_window_days)
        days_remaining = max(0, (closes_on - as_of).days)
        status = _status(
            as_of=as_of,
            closes_on=closes_on,
            days_remaining=(closes_on - as_of).days,
            prior=prior_spend_minor,
            min_spend=offer.min_spend_minor,
        )
    if prior_spend_minor is None:
        limits.append(_limit("PRIOR_SPEND_UNKNOWN"))

    offer_currency = offer.currency if offer is not None else None
    effective_opened = opened_on if window_known else None
    lines: list[TripLineTiming] = []
    mismatch = False
    omitted_zero = 0
    for assignment in plan.assignments:
        if assignment.card_id != card_id:
            continue
        line = assignment.line
        if line.amount_minor == 0:
            omitted_zero += 1
            continue
        basis: TimingBasis = (
            "advance_booking" if assignment.channel in _ADVANCE_BOOKING else "on_trip"
        )
        discounts = sum(applied.discount_minor for applied in assignment.offers_applied)
        assessment = _assess(
            basis=basis,
            plan=plan,
            opened_on=effective_opened,
            closes_on=closes_on,
            as_of=as_of,
            line_currency=line.currency,
            offer_currency=offer_currency,
            ambiguous_entry=duplicate_card_entries,
        )
        mismatch = mismatch or assessment == "currency_mismatch"
        lines.append(
            TripLineTiming(
                line_id=line.id,
                label=line.label,
                category=line.category.value,
                channel=assignment.channel.value,
                timing_basis=basis,
                amount_minor=line.amount_minor,
                instant_discounts_minor=discounts,
                counted_minor=max(0, line.amount_minor - discounts),
                currency=line.currency,
                assessment=assessment,
            )
        )
    if mismatch:
        limits.append(_limit("CURRENCY_MISMATCH"))

    gross = sum(item.amount_minor for item in lines)
    counted = sum(item.counted_minor for item in lines)
    conditional = sum(
        item.counted_minor
        for item in lines
        if item.assessment == "could_count_if_paid_by_close"
    )

    min_spend = offer.min_spend_minor if offer is not None else None
    shortfall: int | None = None
    after_trip: int | None = None
    clears: bool | None = None
    if min_spend is not None and prior_spend_minor is not None:
        shortfall = max(0, min_spend - prior_spend_minor)
        if window_known:
            after_trip = max(0, min_spend - prior_spend_minor - conditional)
    if min_spend is not None and window_known:
        clears = conditional >= min_spend

    bonus: BonusOut | None = None
    if offer is not None:
        bonus, bonus_limits = _value_bonus(offer, kb)
        limits.extend(bonus_limits)

    return WelcomeWindowReport(
        card_id=card_id,
        card_name=kb.card(card_id).name if kb.has_card(card_id) else None,
        wallet_entry_id=wallet_entry_id,
        as_of=as_of,
        status=status,
        limitations=limits,
        opened_on=opened_on,
        window_closes_on=closes_on,
        days_remaining=days_remaining,
        offer=_offer_out(offer) if offer is not None else None,
        ineligible_offer_count=selection.ineligible_count,
        min_spend_minor=min_spend,
        currency=offer_currency,
        qualifying_spend_to_date_minor=prior_spend_minor,
        shortfall_minor=shortfall,
        trip=TripWindow(
            trip_id=plan.trip_id,
            revision=plan.revision,
            revision_computed_at=plan.computed_at,
            trip_start_date=plan.trip_start_date,
            trip_end_date=plan.trip_end_date,
            plan_booking_date=plan.plan_booking_date,
            currency=plan.currency,
        ),
        trip_assigned_spend_minor=gross,
        trip_counted_spend_minor=counted,
        conditional_trip_spend_minor=conditional,
        shortfall_after_conditional_trip_minor=after_trip,
        trip_alone_clears_minimum_if_conditions_hold=clears,
        omitted_zero_amount_lines=omitted_zero,
        lines=lines,
        bonus=bonus,
        assumptions=_assumptions(offer=offer, bonus=bonus, prior=prior_spend_minor, as_of=as_of),
    )


def _assumptions(
    *,
    offer: CardAcquisitionOffer | None,
    bonus: BonusOut | None,
    prior: int | None,
    as_of: date,
) -> list[str]:
    notes = [
        f"Dates are evaluated as of {as_of.isoformat()} (the server's UTC date).",
        "The report describes the assignments in the stored plan. It does not change "
        "them, re-rank them, or add the welcome bonus to any plan total.",
        "Trip spend counted is the amount the plan assigns to this card, net of instant "
        "discounts the plan applied. Issuer-specific spend that does not count toward "
        "a minimum (excluded categories, fees, refunds) is not modeled; check the "
        "verbatim offer terms.",
        "Payment timing is not observed. Flights, hotels, online agencies and bank "
        "portal lines are assumed paid when you book; destination (POS) lines are "
        "assumed charged within the travel dates, which can differ from posting dates. "
        "Spend is therefore reported as conditional, never as confirmed qualifying.",
    ]
    if offer is not None:
        notes.append(
            "The offer shown is the approved offer for this card that was still in "
            "force on the recorded open date. Which offer your account was actually "
            "granted cannot be verified."
        )
        notes.append(
            "The window runs from the open date for the offer's spend_window_days; the "
            "closing day is treated as the last qualifying day. Issuer day-counting "
            "rules are not modeled."
        )
    if prior is None:
        notes.append(
            "Spend already made on this card was not provided and is not assumed to "
            "be zero."
        )
    else:
        notes.append(
            "Spend already made is as you entered it, in the offer's currency, and "
            "is not verified."
        )
    if bonus is not None and bonus.valuation is not None:
        notes.append(
            "A points bonus is valued with the card's best existing valuation path "
            f"({bonus.valuation.path}), using the same integer valuation as the "
            "optimizer. That valuation may itself need verification."
        )
    return notes
