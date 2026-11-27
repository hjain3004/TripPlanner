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

from datetime import date
from typing import Literal

from core.db import KnowledgeBase
from welcome.catalog import OfferCatalog
from welcome.models import (
    AcquisitionAssessmentIn,
    AcquisitionAssessmentReport,
    AcquisitionRefusal,
    AcquisitionSuggestion,
    HeldCardsStrategySummary,
    Limitation,
)
from welcome.retrieval import (
    acquisition_assumptions,
    acquisition_offer_out,
    check_pre_optimize_gates,
    evaluate_exact_candidate,
    format_money,
    retrieve_top_candidates,
)
from welcome.status import StoredPlan, StoredPlanUnreadableError, _limit

# Re-exported for backwards compatibility with existing callers/tests.
__all__ = [
    "acquisition_assumptions",
    "acquisition_offer_out",
    "compute_acquisition_assessment",
    "format_money",
]


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
    top_m: int | None = None,
    home_country: Literal["IN", "AE", "US"] | None = None,
    closed_card_ids: set[str] | None = None,
    open_card_ids: set[str] | None = None,
) -> AcquisitionAssessmentReport:
    """Assess candidate unheld card welcome offers against a stored trip revision.

    When ``payload.candidate_card_id`` is None and ``top_m`` is provided, uses OPT-1's
    zero-bias Stage-1 eligibility filter, pure-integer sound upper bound ``UB(c | W)``,
    and lazy max-heap evaluation to compute the exact top-``m`` suggestions without
    evaluating pruned candidates.
    """
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

    all_held_ids = user_held_card_ids | set(stored_card_ids)
    pt = payload.payment_timing

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
                assumptions=acquisition_assumptions(as_of, None),
            )
        candidate_ids = [cand_id]
    else:
        approved_in_catalog = catalog.approved_offers()
        if not approved_in_catalog:
            limitations.append(_limit("NO_APPROVED_OFFER"))
            return AcquisitionAssessmentReport(
                trip_id=trip_id,
                revision=revision,
                as_of=as_of,
                held_cards_strategy=held_strategy,
                suggestions=[],
                refusals=[],
                limitations=limitations,
                assumptions=acquisition_assumptions(as_of, None),
            )

        if top_m is not None:
            retrieval = retrieve_top_candidates(
                as_of=as_of,
                kb=kb,
                catalog=catalog,
                plan=plan,
                user_held_card_ids=user_held_card_ids,
                payment_timing=pt,
                top_m=top_m,
                home_country=home_country,
                closed_card_ids=closed_card_ids,
                open_card_ids=open_card_ids,
            )
            return AcquisitionAssessmentReport(
                trip_id=trip_id,
                revision=revision,
                as_of=as_of,
                held_cards_strategy=held_strategy,
                suggestions=retrieval.suggestions,
                refusals=[*retrieval.evaluated_refusals, *retrieval.hard_filtered_refusals],
                limitations=retrieval.limitations,
                assumptions=acquisition_assumptions(as_of, pt),
            )

        closed = closed_card_ids or set()
        candidate_ids = [
            c.id
            for c in kb.cards()
            if c.id not in all_held_ids
            and c.id not in closed
            and (open_card_ids is None or c.id in open_card_ids)
            and (home_country is None or c.country == home_country)
        ]

    if pt is None:
        limitations.append(_limit("PAYMENT_TIMING_UNKNOWN"))

    for card_id in candidate_ids:
        card_name = kb.card(card_id).name if kb.has_card(card_id) else None
        ctx, pre_refusal, pre_lim = check_pre_optimize_gates(
            card_id=card_id,
            card_name=card_name,
            as_of=as_of,
            costed_trip=costed_trip,
            catalog=catalog,
            pt=pt,
            check_spend_window_before_optimize=False,
        )
        if pre_lim is not None:
            limitations.append(pre_lim)
        if pre_refusal is not None or ctx is None:
            if pre_refusal is not None:
                # Preserve existing empty-refusal behavior when catalog lacks an offer for a card
                # during an unscoped catalog scan.
                if payload.candidate_card_id is not None or pre_refusal.offer_id is not None:
                    refusals.append(pre_refusal)
            continue

        assert pt is not None
        suggestion, eval_refusal = evaluate_exact_candidate(
            ctx=ctx,
            as_of=as_of,
            kb=kb,
            plan=plan,
            costed_trip=costed_trip,
            stored_card_ids=stored_card_ids,
            held_benefit_minor=held_benefit,
            pt=pt,
        )
        if suggestion is not None:
            suggestions.append(suggestion)
        elif eval_refusal is not None:
            refusals.append(eval_refusal)

    suggestions.sort(key=lambda s: (-s.net_first_year_minor, s.card_id))

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
        assumptions=acquisition_assumptions(as_of, pt),
    )
