from __future__ import annotations

from datetime import date

from agents.critic import run_critic
from agents.estimator import estimate_costed_trip
from agents.explainer import build_final_report, run_explainer
from agents.kernel import run_kernel
from agents.llm import ScriptedLLMClient
from agents.models import (
    CriticIssue,
    CriticVerdict,
    DraftItinerary,
    ExplainerOutput,
    ItineraryDay,
    ItineraryItem,
    TripSpec,
)
from core.db import SEEDS_DIR, load_kb, seed_database
from core.models import UserWallet


def _kb(tmp_path):
    db_path = tmp_path / "tripwise.sqlite"
    seed_database(SEEDS_DIR, db_path)
    return load_kb(db_path)


def _spec() -> TripSpec:
    return TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        travelers=2,
        budget_minor=25000000,
        budget_currency="INR",
        style="balanced",
        interests=["nature", "food"],
        wallet=UserWallet(
            card_ids=["hdfc-infinia", "axis-atlas"],
            points_balances={"voyager-prime": 140000},
        ),
    )


def _itinerary() -> DraftItinerary:
    return DraftItinerary(
        hotel_area_id="marina_bay",
        days=[
            ItineraryDay(
                date=date(2026, 8, 1),
                items=[
                    ItineraryItem(poi_id="sg-gardens-by-the-bay"),
                    ItineraryItem(poi_id="sg-hawker-maxwell"),
                ],
            ),
            ItineraryDay(date=date(2026, 8, 2), items=[]),
            ItineraryDay(date=date(2026, 8, 3), items=[]),
            ItineraryDay(date=date(2026, 8, 4), items=[]),
        ],
    )


def _artifacts(tmp_path):
    kb = _kb(tmp_path)
    spec = _spec()
    itinerary = _itinerary()
    estimate = estimate_costed_trip(spec, itinerary, kb, booking_date=date(2026, 7, 25))
    kernel = run_kernel(spec, estimate, kb, booking_date=date(2026, 7, 25))
    return kb, spec, itinerary, estimate, kernel


def test_critic_returns_scripted_verdict(tmp_path) -> None:
    kb, spec, itinerary, estimate, _kernel = _artifacts(tmp_path)
    llm = ScriptedLLMClient(
        {
            "critic": [
                CriticVerdict(
                    passed=False,
                    issues=[
                        CriticIssue(
                            severity="blocking",
                            kind="geography",
                            message="Too much same-day scatter.",
                        )
                    ],
                )
            ]
        }
    )

    result = run_critic(spec, itinerary, estimate, kb, llm)

    assert result.verdict.passed is False
    assert result.verdict.blocking_issues[0].kind == "geography"
    assert result.caveats == []


def test_critic_failure_skips_with_caveat(tmp_path) -> None:
    kb, spec, itinerary, estimate, _kernel = _artifacts(tmp_path)
    result = run_critic(spec, itinerary, estimate, kb, ScriptedLLMClient({"critic": [RuntimeError()]}))

    assert result.verdict.passed is True
    assert result.caveats == ["Critic unavailable; itinerary was not LLM-reviewed."]


def test_build_final_report_is_deterministic_and_uses_kernel_numbers(tmp_path) -> None:
    _kb, spec, itinerary, estimate, kernel = _artifacts(tmp_path)

    report = build_final_report(
        spec,
        itinerary,
        estimate,
        kernel,
        critic_caveats=["Manual caveat."],
        explainer=ExplainerOutput(
            summary="Structured prototype summary.",
            itinerary_overview="Two curated stops.",
            payment_overview="Use computed assignments.",
        ),
        trace_id="trace-123",
    )

    assert report.budget_totals.gross_minor == kernel.optimizer_result.gross_minor
    assert report.budget_totals.effective_cost_minor == kernel.optimizer_result.effective_cost_minor
    assert report.payment_strategy
    assert report.payment_strategy[0].line_id.startswith("flight:")
    assert report.booking_checklist[0].startswith("Verify all sample prices")
    assert report.caveats == ["Manual caveat."]
    assert report.trace_id == "trace-123"


def test_explainer_groundedness_falls_back_on_invented_currency_amount(tmp_path) -> None:
    _kb, spec, itinerary, estimate, kernel = _artifacts(tmp_path)
    llm = ScriptedLLMClient(
        {
            "explainer": [
                ExplainerOutput(
                    summary="This trip magically costs ₹999,999.",
                    itinerary_overview="Grounded itinerary.",
                    payment_overview="Grounded payments.",
                )
            ]
        }
    )

    report = run_explainer(
        spec,
        itinerary,
        estimate,
        kernel,
        critic_caveats=[],
        trace_id="trace-ground",
        llm=llm,
    )

    assert "₹999,999" not in report.summary
    assert any("groundedness" in caveat.casefold() for caveat in report.caveats)
