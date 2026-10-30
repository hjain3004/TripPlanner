"""The welcome-offer catalog and the package boundaries (spec 18 §1, spec 17 §1).

The shipped catalog must hold no invented terms; the approval gate must keep unsourced or
draft rows out; offer selection must refuse to guess; and the new package must stay on
the right side of the repo's import boundaries.
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from core.models import Provenance
from evals.welcome_support import SYNTHETIC_PROVENANCE, synthetic_offer
from welcome.catalog import (
    DEFAULT_OFFERS_PATH,
    OfferCatalog,
    OfferCatalogError,
    is_approved,
    load_offer_catalog,
    shipped_offer_catalog,
    verification_status,
)
from welcome.models import CardAcquisitionOffer

BACKEND = Path(__file__).resolve().parents[1]


def _provenance(**overrides: Any) -> Provenance:
    fields: dict[str, Any] = {
        "source_url": "https://example.invalid/x",
        "source_type": "official_page",
        "last_verified": date(2026, 10, 1),
        "verified_by": "curator-1",
        "needs_verification": False,
        "confidence": 0.9,
    }
    fields.update(overrides)
    return Provenance.model_validate(fields)


# --- the shipped catalog invents nothing ------------------------------------- #


def test_the_shipped_catalog_is_empty_so_the_normal_path_reports_no_offer() -> None:
    assert yaml.safe_load(DEFAULT_OFFERS_PATH.read_text()) == []
    selection = shipped_offer_catalog().select_offer("hdfc-infinia", date(2026, 10, 1))
    assert selection.offer is None
    assert selection.reason == "NO_APPROVED_OFFER"


def test_a_synthetic_offer_can_never_be_loaded_from_a_shipped_file(tmp_path: Path) -> None:
    path = tmp_path / "offers.yaml"
    path.write_text(yaml.safe_dump([synthetic_offer().model_dump(mode="json")]))
    with pytest.raises(OfferCatalogError, match="synthetic"):
        load_offer_catalog(path)
    # A test or demo may opt in explicitly; the shipped path never does.
    assert load_offer_catalog(path, allow_synthetic=True).offers_for_card("hdfc-infinia")


def test_a_malformed_offers_file_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "offers.yaml"
    path.write_text("not: a list\n")
    with pytest.raises(OfferCatalogError):
        load_offer_catalog(path)
    path.write_text(yaml.safe_dump([{"id": "x", "card_id": "y"}]))
    with pytest.raises(ValidationError):
        load_offer_catalog(path)


def test_duplicate_offer_ids_are_rejected() -> None:
    with pytest.raises(OfferCatalogError):
        OfferCatalog([synthetic_offer(), synthetic_offer()])


# --- the approval gate ------------------------------------------------------- #


def test_only_sourced_non_draft_human_verified_rows_are_approved() -> None:
    assert is_approved(synthetic_offer(provenance=_provenance()))
    assert not is_approved(synthetic_offer(provenance=_provenance(source_url=None)))
    assert not is_approved(synthetic_offer(provenance=_provenance(source_type="crawl_draft")))
    assert not is_approved(synthetic_offer(provenance=_provenance(verified_by="UNVERIFIED")))
    assert not is_approved(synthetic_offer(provenance=_provenance(verified_by=" unverified ")))


def test_unapproved_rows_are_excluded_and_counted_not_silently_dropped() -> None:
    draft = synthetic_offer(id="draft", provenance=_provenance(source_type="crawl_draft"))
    selection = OfferCatalog([draft]).select_offer("hdfc-infinia", date(2026, 10, 1))
    assert selection.offer is None
    assert selection.reason == "NO_APPROVED_OFFER"
    assert selection.ineligible_count == 1


def test_needs_verification_does_not_disqualify_but_is_reported() -> None:
    flagged = synthetic_offer(provenance=_provenance(needs_verification=True))
    assert is_approved(flagged)
    assert verification_status(flagged) == "needs_verification"
    assert verification_status(synthetic_offer(provenance=_provenance())) == "verified"
    assert verification_status(synthetic_offer(provenance=SYNTHETIC_PROVENANCE)) == (
        "synthetic_fixture"
    )


# --- selection refuses to guess ---------------------------------------------- #


def test_selection_picks_the_single_offer_in_force_on_the_open_date() -> None:
    catalog = OfferCatalog([synthetic_offer(valid_to=date(2026, 12, 31))])
    assert catalog.select_offer("hdfc-infinia", date(2026, 12, 31)).offer is not None
    expired = catalog.select_offer("hdfc-infinia", date(2027, 1, 1))
    assert expired.offer is None
    assert expired.reason == "OFFER_NOT_IN_FORCE_AT_OPEN_DATE"


def test_two_candidate_offers_select_neither() -> None:
    catalog = OfferCatalog(
        [
            synthetic_offer(id="old", valid_to=date(2027, 6, 30)),
            synthetic_offer(id="new", valid_to=date(2028, 6, 30)),
        ]
    )
    both = catalog.select_offer("hdfc-infinia", date(2026, 10, 1))
    assert both.offer is None and both.reason == "AMBIGUOUS_OFFER"
    # Opened after the older one ended, only the newer remains.
    only_new = catalog.select_offer("hdfc-infinia", date(2027, 9, 1))
    assert only_new.offer is not None and only_new.offer.id == "new"


def test_an_unknown_open_date_does_not_pick_between_offers() -> None:
    one = OfferCatalog([synthetic_offer()]).select_offer("hdfc-infinia", None)
    assert one.offer is not None  # terms may be shown; the window is not computed here
    two = OfferCatalog([synthetic_offer(id="a"), synthetic_offer(id="b")]).select_offer(
        "hdfc-infinia", None
    )
    assert two.offer is None and two.reason == "AMBIGUOUS_OFFER"


def test_offers_are_scoped_to_their_card() -> None:
    catalog = OfferCatalog([synthetic_offer("hdfc-infinia")])
    other = catalog.select_offer("axis-atlas", date(2026, 10, 1))
    assert other.offer is None and other.reason == "NO_APPROVED_OFFER"


# --- the offer model --------------------------------------------------------- #


def test_an_offer_has_exactly_one_bonus_kind() -> None:
    with pytest.raises(ValidationError):
        synthetic_offer(bonus_flat_minor=100)  # both points and flat
    with pytest.raises(ValidationError):
        synthetic_offer(bonus_points=None, bonus_currency_id=None)  # neither
    with pytest.raises(ValidationError):
        synthetic_offer(bonus_currency_id=None)  # points without a currency
    with pytest.raises(ValidationError):
        synthetic_offer(bonus_points=None, bonus_flat_minor=100)  # flat naming a currency
    with pytest.raises(ValidationError):
        CardAcquisitionOffer.model_validate(
            {**synthetic_offer().model_dump(), "affiliate_link": "https://x"}
        )


# --- package boundaries ------------------------------------------------------ #


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_welcome_reads_core_but_touches_no_store_llm_provider_or_network() -> None:
    forbidden = {"accounts", "agents", "gateway", "planning", "api", "httpx", "requests"}
    for module in (BACKEND / "welcome").glob("*.py"):
        assert not (_imports(module) & forbidden), module.name


def test_core_and_accounts_do_not_import_welcome() -> None:
    for package in ("core", "accounts"):
        for module in (BACKEND / package).rglob("*.py"):
            assert "welcome" not in _imports(module), module


def test_the_status_computation_reads_no_clock_and_no_randomness() -> None:
    source = (BACKEND / "welcome" / "status.py").read_text()
    for banned in ("datetime.now", "date.today", ".utcnow", "time.time", "random", "uuid"):
        assert banned not in source, banned
