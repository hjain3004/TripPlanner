from __future__ import annotations

from datetime import date
from pathlib import Path

from agents.estimator import estimate_costed_trip
from agents.explainer import build_final_report
from agents.kernel import run_kernel
from agents.models import DraftItinerary, ExplainerOutput, ItineraryDay, ItineraryItem, TripSpec
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


def _report(tmp_path):
    kb = _kb(tmp_path)
    spec = _spec()
    itinerary = _itinerary()
    estimate = estimate_costed_trip(spec, itinerary, kb, booking_date=date(2026, 7, 25))
    kernel = run_kernel(spec, estimate, kb, booking_date=date(2026, 7, 25))
    return build_final_report(
        spec,
        itinerary,
        estimate,
        kernel,
        critic_caveats=[],
        explainer=ExplainerOutput(
            summary="Grounded summary.",
            itinerary_overview="Grounded itinerary.",
            payment_overview="Grounded payment plan.",
        ),
        trace_id="trace-m3",
    )


def test_report_footer_contains_min_last_verified_and_disclaimer(tmp_path) -> None:
    report = _report(tmp_path)

    assert report.footer.startswith("Computed from data last verified on 2026-07-07")
    assert "informational, not financial advice" in report.footer
    assert "verify prices and offer terms before paying" in report.footer


def test_provenance_warnings_render_for_seeded_needs_verification_fact(tmp_path) -> None:
    report = _report(tmp_path)

    assert report.provenance_warnings
    assert any("needs_verification" in warning for warning in report.provenance_warnings)
    assert any(warning.startswith("flight:") for warning in report.provenance_warnings)


def test_runtime_packages_do_not_import_evals_judge() -> None:
    root = Path(__file__).resolve().parents[1]
    runtime_files = [
        *sorted((root / "agents").glob("*.py")),
        *sorted((root / "api").glob("*.py")),
        *sorted((root / "core").rglob("*.py")),
    ]

    offenders = [
        path.relative_to(root).as_posix()
        for path in runtime_files
        if "evals.judge" in path.read_text()
    ]
    assert offenders == []
