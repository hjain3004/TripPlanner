from __future__ import annotations

import re
from datetime import date

from agents.llm import LLMClient, complete_with_repair
from agents.models import (
    BudgetTotals,
    DraftItinerary,
    EstimatorResult,
    ExplainerOutput,
    FinalReport,
    KernelResult,
    PaymentStrategyRow,
    SelectedHotelArea,
    TripSpec,
)
from core.models import LineAssignment, OptimizerResult, TransferAdvice

RUPEE_RE = re.compile(r"₹\s?[0-9][0-9,]*")


def _rupees(minor: int) -> str:
    return f"₹{minor // 100:,}"


def _totals(result: OptimizerResult) -> BudgetTotals:
    return BudgetTotals(
        gross_minor=result.gross_minor,
        discounts_minor=result.discounts_minor,
        rewards_value_minor=result.rewards_value_minor,
        forex_fees_minor=result.forex_fees_minor,
        effective_cost_minor=result.effective_cost_minor,
        cash_outlay_now_minor=result.cash_outlay_now_minor,
        deferred_value_minor=result.deferred_value_minor,
        savings_pct_bp=result.savings_pct_bp,
    )


def _payment_sentence(assignment: LineAssignment) -> str:
    line = assignment.line
    offer_text = ""
    if assignment.offers_applied:
        offer_text = " after applying " + ", ".join(
            offer.offer_id for offer in assignment.offers_applied
        )
    return (
        f"Pay {_rupees(line.amount_minor)} for {line.label} with "
        f"{assignment.card_id} via {assignment.channel.value}{offer_text}."
    )


def _payment_rows(assignments: list[LineAssignment]) -> list[PaymentStrategyRow]:
    return [
        PaymentStrategyRow(
            line_id=assignment.line.id,
            label=assignment.line.label,
            card_id=assignment.card_id,
            channel=assignment.channel.value,
            offers=[offer.offer_id for offer in assignment.offers_applied],
            action_sentence=_payment_sentence(assignment),
        )
        for assignment in sorted(assignments, key=lambda row: row.line.id)
    ]


def _checklist(
    assignments: list[LineAssignment], transfer_advice: TransferAdvice | None
) -> list[str]:
    out = ["Verify all sample prices, award availability, and card/offer terms before paying."]
    for assignment in sorted(assignments, key=lambda row: row.line.id):
        out.append(
            f"Book {assignment.line.label} via {assignment.channel.value} using "
            f"{assignment.card_id}; do not transfer points until availability is verified."
        )
    if transfer_advice is not None:
        out.extend(
            step
            for plan in transfer_advice.plans
            if plan.id == transfer_advice.recommendation.plan_id
            for step in plan.checklist_steps
        )
    return out


def _provenance_warnings(
    estimate: EstimatorResult, optimizer: OptimizerResult, transfer: TransferAdvice | None
) -> list[str]:
    warnings: set[str] = set()
    for assignment in optimizer.assignments:
        warnings.update(assignment.provenance_flags)
    if estimate.flight is not None and estimate.flight.provenance.needs_verification:
        warnings.add(f"flight:{estimate.flight.id}:needs_verification")
    if estimate.hotel is not None and estimate.hotel.provenance.needs_verification:
        warnings.add(f"hotel:{estimate.hotel.id}:needs_verification")
    if transfer is not None:
        for plan in transfer.plans:
            warnings.update(plan.provenance_flags)
    return sorted(warnings)


def _used_last_verified_dates(
    estimate: EstimatorResult, transfer: TransferAdvice | None
) -> list[date]:
    dates: list[date] = []
    if estimate.flight is not None:
        dates.append(estimate.flight.provenance.last_verified)
    if estimate.hotel is not None:
        dates.append(estimate.hotel.provenance.last_verified)
    if transfer is not None:
        dates.extend(plan.award.provenance.last_verified for plan in transfer.plans)
    return dates


def _footer(estimate: EstimatorResult, transfer: TransferAdvice | None) -> str:
    dates = _used_last_verified_dates(estimate, transfer)
    last_verified = min(dates).isoformat() if dates else "UNKNOWN"
    return (
        f"Computed from data last verified on {last_verified}; informational, not financial "
        "advice; verify prices and offer terms before paying."
    )


def _hotel_area(itinerary: DraftItinerary, estimate: EstimatorResult) -> SelectedHotelArea:
    if estimate.hotel is not None:
        return SelectedHotelArea(
            id=estimate.hotel.area,
            name=estimate.hotel.area.replace("_", " ").title(),
            reason=f"Selected from the {estimate.hotel.style} sample hotel fixture.",
        )
    return SelectedHotelArea(
        id=itinerary.hotel_area_id,
        name=itinerary.hotel_area_id.replace("_", " ").title(),
        reason="Selected by the itinerary planner; no matching sample hotel was available.",
    )


def _template_explainer(kernel: KernelResult) -> ExplainerOutput:
    totals = kernel.optimizer_result
    return ExplainerOutput(
        summary=(
            f"Estimated gross trip cost is {_rupees(totals.gross_minor)}; effective cost after "
            f"computed discounts, rewards value, and forex fees is "
            f"{_rupees(totals.effective_cost_minor)}."
        ),
        itinerary_overview="The itinerary is assembled from curated sample POIs only.",
        payment_overview="Payment guidance is generated from deterministic optimizer assignments.",
    )


def _allowed_currency_strings(estimate: EstimatorResult, kernel: KernelResult) -> set[str]:
    values: set[int] = {
        kernel.optimizer_result.gross_minor,
        kernel.optimizer_result.discounts_minor,
        kernel.optimizer_result.rewards_value_minor,
        kernel.optimizer_result.forex_fees_minor,
        kernel.optimizer_result.effective_cost_minor,
        kernel.optimizer_result.cash_outlay_now_minor,
        kernel.optimizer_result.deferred_value_minor,
    }
    values.update(line.amount_minor for line in estimate.costed_trip.lines)
    values.update(assignment.benefit_minor for assignment in kernel.optimizer_result.assignments)
    if kernel.transfer_advice is not None:
        for plan in kernel.transfer_advice.plans:
            values.update(
                {
                    plan.total_fees_minor,
                    plan.effective_redemption_cost_minor,
                    plan.savings_vs_cash_minor,
                }
            )
    return {_rupees(value) for value in values if value >= 0}


def _is_grounded(output: ExplainerOutput, estimate: EstimatorResult, kernel: KernelResult) -> bool:
    haystack = "\n".join(
        [output.summary, output.itinerary_overview, output.payment_overview, *output.caveats]
    )
    mentioned = {match.group(0).replace("₹ ", "₹") for match in RUPEE_RE.finditer(haystack)}
    return mentioned.issubset(_allowed_currency_strings(estimate, kernel))


def _explainer_system() -> str:
    return (
        "You write concise TripPlanner report prose as ExplainerOutput JSON only. "
        "Every number must be copied verbatim from the supplied structured artifacts; "
        "never compute or invent amounts. Never mention cards, offers, providers, or facts "
        "absent from the supplied artifacts."
    )


def _explainer_user(
    spec: TripSpec,
    itinerary: DraftItinerary,
    estimate: EstimatorResult,
    kernel: KernelResult,
    critic_caveats: list[str],
) -> str:
    return (
        "TripSpec:\n"
        f"{spec.model_dump_json()}\n"
        "DraftItinerary:\n"
        f"{itinerary.model_dump_json()}\n"
        "EstimatorResult:\n"
        f"{estimate.model_dump_json()}\n"
        "KernelResult:\n"
        f"{kernel.model_dump_json()}\n"
        "Critic caveats:\n"
        f"{critic_caveats}"
    )


def build_final_report(
    spec: TripSpec,
    itinerary: DraftItinerary,
    estimate: EstimatorResult,
    kernel: KernelResult,
    *,
    critic_caveats: list[str],
    explainer: ExplainerOutput,
    trace_id: str,
) -> FinalReport:
    optimizer = kernel.optimizer_result
    caveats = [*critic_caveats, *explainer.caveats]
    return FinalReport(
        trip_spec=spec,
        itinerary=itinerary,
        hotel_area=_hotel_area(itinerary, estimate),
        flights_pick=estimate.flight,
        hotel_pick=estimate.hotel,
        costed_trip=estimate.costed_trip,
        optimizer_result=optimizer,
        budget_totals=_totals(optimizer),
        payment_strategy=_payment_rows(optimizer.assignments),
        transfer_advice=kernel.transfer_advice,
        booking_checklist=_checklist(optimizer.assignments, kernel.transfer_advice),
        assumptions=[*estimate.assumptions, *optimizer.assumptions],
        provenance_warnings=_provenance_warnings(estimate, optimizer, kernel.transfer_advice),
        confidence=optimizer.confidence,
        caveats=caveats,
        summary=explainer.summary,
        itinerary_overview=explainer.itinerary_overview,
        payment_overview=explainer.payment_overview,
        footer=_footer(estimate, kernel.transfer_advice),
        trace_id=trace_id,
    )


def run_explainer(
    spec: TripSpec,
    itinerary: DraftItinerary,
    estimate: EstimatorResult,
    kernel: KernelResult,
    *,
    critic_caveats: list[str],
    trace_id: str,
    llm: LLMClient,
) -> FinalReport:
    caveats = list(critic_caveats)
    try:
        explainer = complete_with_repair(
            llm,
            node="explainer",
            system=_explainer_system(),
            user=_explainer_user(spec, itinerary, estimate, kernel, critic_caveats),
            schema=ExplainerOutput,
            temperature=0.3,
            max_tokens=2048,
            timeout_s=20,
        )
        if not _is_grounded(explainer, estimate, kernel):
            caveats.append("Explainer groundedness gate failed; deterministic prose fallback used.")
            explainer = _template_explainer(kernel)
    except Exception:
        caveats.append("Explainer unavailable; deterministic prose fallback used.")
        explainer = _template_explainer(kernel)
    return build_final_report(
        spec,
        itinerary,
        estimate,
        kernel,
        critic_caveats=caveats,
        explainer=explainer,
        trace_id=trace_id,
    )
