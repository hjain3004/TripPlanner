from __future__ import annotations

from datetime import date

from agents.models import EstimatorResult, KernelResult, TripSpec
from core.db import KnowledgeBase
from core.models import AwardTarget, RecommendationKind
from core.optimizer import optimize
from core.transfer.pathfinder import find_transfer_plans

DEFAULT_BASELINE_VALUATIONS: dict[str, int] = {
    "voyager-prime": 1_000_000,
}


def _flight_cash_price_minor(estimate: EstimatorResult) -> int:
    for line in estimate.costed_trip.lines:
        if line.id.startswith("flight:"):
            return line.amount_minor
    return 0


def _award_target(spec: TripSpec, home_currency: str) -> AwardTarget:
    return AwardTarget(
        origin=spec.origin_city,
        destination=spec.destination_city,
        cabin="business",
        trip_type="round_trip",
        travelers=spec.travelers,
        home_currency=home_currency,
    )


def _baseline_valuations(spec: TripSpec) -> dict[str, int]:
    return {
        currency_id: DEFAULT_BASELINE_VALUATIONS[currency_id]
        for currency_id in spec.wallet.points_balances
        if currency_id in DEFAULT_BASELINE_VALUATIONS
    }


def run_kernel(
    spec: TripSpec,
    estimate: EstimatorResult,
    kb: KnowledgeBase,
    *,
    booking_date: date,
) -> KernelResult:
    optimizer_result = optimize(
        estimate.costed_trip,
        spec.wallet,
        kb,
        spec.optimization,
    )
    baseline = _baseline_valuations(spec)
    cash_price = _flight_cash_price_minor(estimate)
    if not spec.wallet.points_balances or not baseline or cash_price <= 0:
        return KernelResult(
            optimizer_result=optimizer_result,
            transfer_advice=None,
        )

    transfer_advice = find_transfer_plans(
        _award_target(spec, estimate.costed_trip.home_currency),
        spec.wallet,
        kb,
        baseline,
        cash_price,
        booking_date,
    )
    if transfer_advice.recommendation.kind == RecommendationKind.NO_DATA:
        return KernelResult(optimizer_result=optimizer_result, transfer_advice=transfer_advice)
    return KernelResult(optimizer_result=optimizer_result, transfer_advice=transfer_advice)
