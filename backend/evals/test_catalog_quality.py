from gateway.catalog.quality import (
    SUPPORTED_CATEGORIES,
    evaluate_quality,
)
from gateway.places.contracts import Place, PlaceClaim


def test_report_covers_every_supported_category(
    places: list[Place], claims: list[PlaceClaim]
) -> None:
    report = evaluate_quality(places, claims)
    assert set(report.by_category) == set(SUPPORTED_CATEGORIES)


def test_a_category_below_its_minimum_fails_the_report(
    places_missing_food: list[Place], claims: list[PlaceClaim]
) -> None:
    report = evaluate_quality(places_missing_food, claims)
    assert report.passed is False
    assert any("food_court" in f for f in report.failures)


def test_report_counts_places_lacking_coordinates(
    places: list[Place], claims_without_coords: list[PlaceClaim]
) -> None:
    report = evaluate_quality(places, claims_without_coords)
    assert report.places_without_coordinates > 0
    assert report.passed is False


def test_unknown_hours_are_counted_but_do_not_fail_the_build(
    places: list[Place], claims_without_hours: list[PlaceClaim]
) -> None:
    """Spec 5.4: unknown hours become verify_required, not a build failure."""
    report = evaluate_quality(places, claims_without_hours)
    assert report.places_with_unknown_hours > 0
    assert not any("opening_hours" in f for f in report.failures)


def test_licence_coverage_must_be_total(
    places: list[Place], claims_one_missing_licence: list[PlaceClaim]
) -> None:
    """Gate I3: 'licence and attribution coverage is complete.'"""
    report = evaluate_quality(places, claims_one_missing_licence)
    assert report.passed is False
    assert any("licence" in f for f in report.failures)


def test_report_serializes_deterministically(
    places: list[Place], claims: list[PlaceClaim]
) -> None:
    a = evaluate_quality(places, claims).model_dump_json()
    b = evaluate_quality(places, claims).model_dump_json()
    assert a == b
