"""Regression tests for historical campaign selection, using synthetic offers."""

from datetime import date

from evals.welcome_support import synthetic_offer
from welcome.catalog import OfferCatalog


def test_historical_offer_selection_uses_campaign_start_and_end() -> None:
    old = synthetic_offer(id="old", valid_from=date(2026, 1, 1), valid_to=date(2026, 6, 30))
    new = synthetic_offer(id="new", valid_from=date(2026, 7, 1), valid_to=date(2026, 12, 31))
    catalog = OfferCatalog([old, new])
    assert catalog.select_offer("hdfc-infinia", date(2026, 3, 1)).offer == old
    assert catalog.select_offer("hdfc-infinia", date(2026, 8, 1)).offer == new
    assert catalog.select_acquisition_offer("hdfc-infinia", date(2026, 3, 1)).offer == old
    assert catalog.select_offer("hdfc-infinia", date(2027, 1, 1)).offer is None


def test_overlapping_campaigns_remain_ambiguous() -> None:
    a = synthetic_offer(id="a", valid_from=date(2026, 1, 1), valid_to=date(2026, 12, 31))
    b = synthetic_offer(id="b", valid_from=date(2026, 6, 1), valid_to=date(2027, 1, 31))
    catalog = OfferCatalog([a, b])
    assert catalog.select_offer("hdfc-infinia", date(2026, 6, 1)).reason == "AMBIGUOUS_OFFER"


def test_unknown_campaign_start_never_rules_out_an_overlapping_offer() -> None:
    known = synthetic_offer(id="known", valid_from=date(2026, 1, 1), valid_to=date(2026, 12, 31))
    unknown = synthetic_offer(id="unknown", valid_to=date(2026, 12, 31))
    assert (
        OfferCatalog([known, unknown]).select_offer("hdfc-infinia", date(2026, 3, 1)).reason
        == "AMBIGUOUS_OFFER"
    )


def test_unknown_end_and_program_do_not_become_a_recommendation() -> None:
    offer = synthetic_offer(valid_to=None, bonus_currency_id=None)
    catalog = OfferCatalog([offer])
    selected = catalog.select_acquisition_offer("hdfc-infinia", date(2026, 11, 26))
    assert selected.offer is None
    assert selected.reason == "OFFER_TERMS_INCOMPLETE"
    held = catalog.select_offer("hdfc-infinia", date(2026, 11, 1))
    assert held.offer is None
    assert held.reason == "OFFER_TERMS_INCOMPLETE"


def test_unknown_exclusions_prevent_recommendation() -> None:
    offer = synthetic_offer(eligibility_exclusions=None)
    catalog = OfferCatalog([offer])
    assert (
        catalog.select_offer("hdfc-infinia", date(2026, 11, 1)).reason == "OFFER_TERMS_INCOMPLETE"
    )
    assert (
        catalog.select_acquisition_offer("hdfc-infinia", date(2026, 11, 1)).reason
        == "OFFER_TERMS_INCOMPLETE"
    )
