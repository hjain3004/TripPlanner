"""The welcome-offer catalog: what offers exist, and which are approved to use.

Offer terms are reference data owned by humans. This module only *reads* them, and it
refuses to treat a row as usable unless it is properly sourced and not an agent draft
(spec 18 §1, non-negotiable 4). Selecting the offer that applied to a held card is a
judgment the system cannot fully make, so ``select_offer`` refuses to guess: zero or
several candidates return no offer and say why.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import yaml

from welcome.models import (
    SYNTHETIC_VERIFIER_PREFIX,
    CardAcquisitionOffer,
    VerificationStatus,
)

DEFAULT_OFFERS_PATH = Path(__file__).parent / "data" / "card_acquisition_offers.yaml"


class OfferCatalogError(ValueError):
    """The offer data file is malformed or contains something it must not."""


def is_synthetic(offer: CardAcquisitionOffer) -> bool:
    return offer.provenance.verified_by.upper().startswith(SYNTHETIC_VERIFIER_PREFIX)


def is_approved(offer: CardAcquisitionOffer) -> bool:
    """Properly sourced and not an unreviewed draft.

    ``needs_verification`` does NOT disqualify a row: like every shipped seed fact it may
    be curated yet awaiting re-verification, and the response carries that flag. What
    disqualifies it is having no source, an agent ``crawl_draft`` origin, or no human
    verifier at all.
    """
    prov = offer.provenance
    return (
        bool(prov.source_url)
        and prov.source_type != "crawl_draft"
        and prov.verified_by.strip().upper() != "UNVERIFIED"
    )


def verification_status(offer: CardAcquisitionOffer) -> VerificationStatus:
    if is_synthetic(offer):
        return "synthetic_fixture"
    return "needs_verification" if offer.provenance.needs_verification else "verified"


SelectionReason = Literal[
    "NO_APPROVED_OFFER",
    "AMBIGUOUS_OFFER",
    "OFFER_NOT_IN_FORCE_AT_OPEN_DATE",
    "OFFER_TERMS_INCOMPLETE",
]


@dataclass(frozen=True)
class OfferSelection:
    offer: CardAcquisitionOffer | None
    reason: SelectionReason | None
    ineligible_count: int


class OfferCatalog:
    def __init__(self, offers: list[CardAcquisitionOffer]) -> None:
        ids = [o.id for o in offers]
        if len(set(ids)) != len(ids):
            raise OfferCatalogError("duplicate offer id in catalog")
        self._offers = sorted(offers, key=lambda o: o.id)

    def offers_for_card(self, card_id: str) -> list[CardAcquisitionOffer]:
        return [o for o in self._offers if o.card_id == card_id]

    def all_offers(self) -> list[CardAcquisitionOffer]:
        return list(self._offers)

    def approved_offers(self) -> list[CardAcquisitionOffer]:
        return [o for o in self._offers if is_approved(o)]

    def select_acquisition_offer(self, card_id: str, booking_date: date | None) -> OfferSelection:
        """The one approved offer that could apply to this unheld card, or none and why."""
        rows = self.offers_for_card(card_id)
        approved = [o for o in rows if is_approved(o)]
        ineligible = len(rows) - len(approved)
        if not approved:
            return OfferSelection(None, "NO_APPROVED_OFFER", ineligible)
        in_force = (
            approved
            if booking_date is None
            else [
                o
                for o in approved
                if (o.valid_from is None or o.valid_from <= booking_date)
                and (o.valid_to is None or booking_date <= o.valid_to)
            ]
        )
        if not in_force:
            return OfferSelection(None, "OFFER_NOT_IN_FORCE_AT_OPEN_DATE", ineligible)
        if len(in_force) > 1:
            return OfferSelection(None, "AMBIGUOUS_OFFER", ineligible)
        if in_force[0].valid_to is None or in_force[0].eligibility_exclusions is None:
            return OfferSelection(None, "OFFER_TERMS_INCOMPLETE", ineligible)
        return OfferSelection(in_force[0], None, ineligible)

    def select_offer(self, card_id: str, opened_on: date | None) -> OfferSelection:
        """The one approved offer that could have applied, or none and why.

        The offer actually granted to a user cannot be observed, so the rule is
        conservative: only approved rows whose ``valid_to`` is not before the card's open
        date are candidates, and anything other than exactly one candidate selects none.
        """
        rows = self.offers_for_card(card_id)
        approved = [o for o in rows if is_approved(o)]
        ineligible = len(rows) - len(approved)
        if not approved:
            return OfferSelection(None, "NO_APPROVED_OFFER", ineligible)
        in_force = (
            approved
            if opened_on is None
            else [
                o
                for o in approved
                if (o.valid_from is None or o.valid_from <= opened_on)
                and (o.valid_to is None or opened_on <= o.valid_to)
            ]
        )
        if not in_force:
            return OfferSelection(None, "OFFER_NOT_IN_FORCE_AT_OPEN_DATE", ineligible)
        if len(in_force) > 1:
            return OfferSelection(None, "AMBIGUOUS_OFFER", ineligible)
        if in_force[0].valid_to is None or in_force[0].eligibility_exclusions is None:
            return OfferSelection(None, "OFFER_TERMS_INCOMPLETE", ineligible)
        return OfferSelection(in_force[0], None, ineligible)


def load_offer_catalog(
    path: Path = DEFAULT_OFFERS_PATH, *, allow_synthetic: bool = False
) -> OfferCatalog:
    """Read and validate an offers file. Synthetic rows are refused unless asked for.

    The shipped file is loaded with ``allow_synthetic=False`` so an authored demo offer can
    never be served as issuer terms; tests and the demo build their catalog explicitly.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise OfferCatalogError(f"{path.name} must be a YAML list of offers")
    offers = [CardAcquisitionOffer.model_validate(item) for item in raw]
    if not allow_synthetic:
        for offer in offers:
            if is_synthetic(offer):
                raise OfferCatalogError(
                    f"offer {offer.id} is a synthetic fixture and may not be shipped"
                )
    return OfferCatalog(offers)


OFFERS_PATH_ENV = "TRIPWISE_WELCOME_OFFERS_PATH"


def active_offers_path() -> Path:
    """The catalog file the service reads: the operator's published file, else the shipped one.

    ``TRIPWISE_WELCOME_OFFERS_PATH`` names a file outside the repository that the controlled
    publisher writes. Unset, the shipped (empty) file is used and nothing changes.
    """
    configured = os.environ.get(OFFERS_PATH_ENV, "").strip()
    return Path(configured) if configured else DEFAULT_OFFERS_PATH


@dataclass
class _Loaded:
    key: tuple[str, int, int]
    catalog: OfferCatalog


_loaded: _Loaded | None = None
last_reload_error: str | None = None
_failed_since: datetime | None = None
logger = logging.getLogger(__name__)


def reload_offer_catalog() -> OfferCatalog:
    """Drop the cached catalog and read the active file again."""
    global _loaded
    _loaded = None
    return shipped_offer_catalog()


def shipped_offer_catalog() -> OfferCatalog:
    """The approved catalog, reloaded whenever its file changes (no restart needed).

    The file is checked by modification time and size on every call (one ``stat``). If it has
    gone missing, or a changed file is unreadable or invalid, the last catalog that loaded cleanly
    keeps being served: its offers keep the provenance dates they were approved with, nothing is
    re-stamped as freshly verified, and ``catalog_status()`` reports the failure. With no earlier
    good catalog there is nothing honest to serve, so an ``OfferCatalogError`` is raised and no
    offer data is invented.
    """
    global _loaded, last_reload_error, _failed_since
    path = active_offers_path()
    try:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        if _loaded is not None and _loaded.key == key:
            last_reload_error = None
            _failed_since = None
            return _loaded.catalog
        catalog = load_offer_catalog(path)
    except (OfferCatalogError, ValueError, OSError, yaml.YAMLError) as error:
        last_reload_error = f"{type(error).__name__}: {error}"[:300]
        if _failed_since is None:
            _failed_since = datetime.now(UTC)
        if _loaded is None:
            raise OfferCatalogError(
                f"the approved offer catalog is unavailable and no earlier good copy exists: "
                f"{last_reload_error}"
            ) from error
        logger.warning(
            "welcome offer catalog reload failed; serving the last good copy: %s",
            last_reload_error,
        )
        return _loaded.catalog
    last_reload_error = None
    _failed_since = None
    _loaded = _Loaded(key=key, catalog=catalog)
    return catalog


def catalog_status() -> dict[str, object]:
    """Whether the served catalog is the current file or an earlier good copy, and why."""
    return {
        "path": str(active_offers_path()),
        "loaded": _loaded is not None,
        "serving_last_good_copy": last_reload_error is not None and _loaded is not None,
        "last_reload_error": last_reload_error,
        "failing_since": None if _failed_since is None else _failed_since.isoformat(),
    }
