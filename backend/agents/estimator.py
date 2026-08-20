from __future__ import annotations

from datetime import date
from typing import Literal

from agents.config import load_agent_config
from agents.models import DraftItinerary, EstimatorResult, TripSpec
from agents.retrieval import resolve_destination_city
from core.db import KnowledgeBase
from core.models import (
    POI,
    Area,
    Channel,
    CostedTrip,
    SampleFlight,
    SampleHotel,
    SpendCategory,
    SpendLineItem,
)
from core.transfer.arithmetic import convert_minor
from core.travel_taxonomy import spend_category_for_tags

HOME_CURRENCY_BY_COUNTRY = {"IN": "INR", "AE": "AED", "US": "USD"}
DESTINATION_CURRENCY_BY_IATA = {"SIN": "SGD"}
PER_DIEM_MINOR_BY_STYLE = load_agent_config().estimator.per_diem_sgd_minor


def home_currency(spec: TripSpec) -> str:
    return HOME_CURRENCY_BY_COUNTRY[spec.home_country]


def destination_city(spec: TripSpec) -> str:
    return resolve_destination_city(spec.destination_city)


def preferred_cabin(style: str) -> Literal["economy", "premium", "business"]:
    if style == "luxury":
        return "business"
    return "economy"


def price_in_home(amount_minor: int, currency: str, home_currency: str, kb: KnowledgeBase) -> int:
    if amount_minor == 0 or currency == home_currency:
        return amount_minor
    fx = kb.fx_rate(currency, home_currency)
    if fx is None:
        raise ValueError(f"Missing FX rate for {currency}->{home_currency}")
    return convert_minor(amount_minor, fx)


def _pick_flight(spec: TripSpec, kb: KnowledgeBase) -> tuple[SampleFlight | None, list[str]]:
    cabin = preferred_cabin(spec.style)
    matches = kb.sample_flights(spec.origin_city, spec.destination_city, cabin)
    assumptions: list[str] = []
    if not matches and cabin != "economy":
        matches = kb.sample_flights(spec.origin_city, spec.destination_city, "economy")
        assumptions.append(
            f"No sample {cabin} cash flight exists for {spec.origin_city}-{spec.destination_city}; "
            "using the cheapest economy fixture."
        )
    if not matches:
        return None, [f"No sample flight exists for {spec.origin_city}-{spec.destination_city}."]
    return min(matches, key=lambda row: (row.price_minor, row.stops, row.id)), assumptions


def area_by_id(kb: KnowledgeBase, city: str, area_id: str) -> Area | None:
    for area in kb.areas(city):
        if area.id == area_id:
            return area
    return None


def _pick_hotel(
    spec: TripSpec, itinerary: DraftItinerary, kb: KnowledgeBase
) -> tuple[SampleHotel | None, list[str]]:
    city = destination_city(spec)
    exact = kb.sample_hotels(city, spec.style, itinerary.hotel_area_id)
    assumptions: list[str] = []
    if exact:
        return min(exact, key=lambda row: (row.price_per_night_minor, row.id)), assumptions

    same_style = kb.sample_hotels(city, spec.style)
    if not same_style:
        return None, [f"No sample {spec.style} hotel exists for {city}."]

    selected_area = area_by_id(kb, city, itinerary.hotel_area_id)
    centrality = selected_area.centrality_score if selected_area is not None else 1.0
    area_scores = {area.id: area.centrality_score for area in kb.areas(city)}
    assumptions.append(
        f"No sample {spec.style} hotel exists in {itinerary.hotel_area_id}; "
        "used closest available area by centrality fallback."
    )
    return min(
        same_style,
        key=lambda row: (
            abs(area_scores.get(row.area, 1.0) - centrality),
            row.price_per_night_minor,
            row.id,
        ),
    ), assumptions





def _poi_category(poi: POI) -> SpendCategory:
    return spend_category_for_tags(poi.tags)


def poi_lines(
    spec: TripSpec, itinerary: DraftItinerary, kb: KnowledgeBase
) -> tuple[list[SpendLineItem], list[str]]:
    home_ccy = home_currency(spec)
    seen: set[str] = set()
    lines: list[SpendLineItem] = []
    assumptions: list[str] = []

    # Pre-fetch kb pois for fast lookup
    kb_pois = {poi.id: poi for poi in kb.pois(destination_city(spec))}

    for day in itinerary.days:
        for item in day.items:
            if item.poi_id in seen:
                continue
            seen.add(item.poi_id)

            poi = kb_pois.get(item.poi_id)
            if not poi:
                from agents.retrieval import get_catalog_poi

                poi = get_catalog_poi(item.poi_id, spec.destination_city)

            if not poi:
                # If a POI is genuinely hallucinated, skip costing it for now
                continue

            try:
                amount = (
                    price_in_home(poi.price_minor, poi.currency, home_ccy, kb)
                    * spec.travelers
                )
            except ValueError:
                assumptions.append(
                    f"No verified FX rate for {poi.currency}->{home_ccy}; "
                    f"omitted cash pricing for {poi.name} from budget estimation."
                )
                continue

            lines.append(
                SpendLineItem(
                    id=f"poi:{poi.id}",
                    label=poi.name,
                    category=_poi_category(poi),
                    amount_minor=amount,
                    currency=home_ccy,
                    available_channels=[poi.booking_channel],
                    merchant_hint=poi.merchant_hint,
                )
            )
    return lines, assumptions


def per_diem_lines(spec: TripSpec, kb: KnowledgeBase) -> tuple[list[SpendLineItem], list[str]]:
    from gateway.catalog.regions import get_region

    region = get_region(spec.destination_city)
    home_ccy = home_currency(spec)

    # Per-diem constants (PER_DIEM_MINOR_BY_STYLE) are SGD-denominated seed
    # data - Singapore-specific. A region without verified per-diem/FX data
    # gets no per-diem line rather than a converted-through-SGD guess (I7
    # constraint: no currencies or FX rates added speculatively for new
    # regions). This also fixes a real crash: registering Mumbai without this
    # gate raised ValueError("Missing FX rate for INR->INR") on every trip,
    # because _pick_flight/_pick_hotel already degrade gracefully but this
    # unconditionally required an FX rate. Matches their (value, assumptions)
    # return shape.
    if region and not region.budget_supported:
        city = region.city_name
        return [], [
            f"No per-diem cost data for {city} yet; "
            "dining and local transport are not included in the budget."
        ]

    if region:
        destination_currency = region.currency
    else:
        destination_currency = DESTINATION_CURRENCY_BY_IATA.get(
            spec.destination_city, "SGD"
        )
    fx = kb.fx_rate(destination_currency, home_ccy)
    if fx is None:
        raise ValueError(f"Missing FX rate for {destination_currency}->{home_ccy}")
    constants = PER_DIEM_MINOR_BY_STYLE[spec.style]
    days = spec.nights
    lines = [
        SpendLineItem(
            id="per_diem:dining",
            label="Dining per-diem estimate",
            category=SpendCategory.DINING,
            amount_minor=convert_minor(constants["dining"] * spec.travelers * days, fx),
            currency=home_ccy,
            available_channels=[Channel.POS_ABROAD],
        ),
        SpendLineItem(
            id="per_diem:misc",
            label="Local transport and misc per-diem estimate",
            category=SpendCategory.OTHER,
            amount_minor=convert_minor(constants["misc"] * spec.travelers * days, fx),
            currency=home_ccy,
            available_channels=[Channel.POS_ABROAD],
        ),
    ]
    assumptions = [
        f"Sample per-diem estimate uses {spec.style} Singapore constants: "
        f"{constants['dining']} SGD cents dining and "
        f"{constants['misc']} SGD cents misc per person-day."
    ]
    return lines, assumptions


def estimate_costed_trip(
    spec: TripSpec,
    itinerary: DraftItinerary,
    kb: KnowledgeBase,
    *,
    booking_date: date,
) -> EstimatorResult:
    home_ccy = home_currency(spec)
    flight, flight_assumptions = _pick_flight(spec, kb)
    hotel, hotel_assumptions = _pick_hotel(spec, itinerary, kb)
    lines: list[SpendLineItem] = []

    if flight is not None:
        lines.append(
            SpendLineItem(
                id=f"flight:{flight.id}",
                label=f"{flight.airline} round-trip flight",
                category=SpendCategory.FLIGHTS,
                amount_minor=price_in_home(
                    flight.price_minor, flight.currency, home_ccy, kb
                )
                * spec.travelers,
                currency=home_ccy,
                available_channels=flight.purchasable_channels,
                merchant_hint=flight.airline,
            )
        )
    if hotel is not None:
        lines.append(
            SpendLineItem(
                id=f"hotel:{hotel.id}",
                label=f"{hotel.name} ({spec.nights} nights)",
                category=SpendCategory.HOTELS,
                amount_minor=price_in_home(
                    hotel.price_per_night_minor, hotel.currency, home_ccy, kb
                )
                * spec.nights,
                currency=home_ccy,
                available_channels=hotel.purchasable_channels,
                merchant_hint=hotel.name,
            )
        )

    poi_line_items, poi_assumptions = poi_lines(spec, itinerary, kb)
    lines.extend(poi_line_items)
    per_diem_line_items, per_diem_assumptions = per_diem_lines(spec, kb)
    lines.extend(per_diem_line_items)

    return EstimatorResult(
        costed_trip=CostedTrip(
            id=f"{spec.origin_city}-{spec.destination_city}-{spec.start_date.isoformat()}",
            origin=spec.origin_city,
            destination=spec.destination_city,
            home_currency=home_ccy,
            booking_date=booking_date,
            trip_start_date=spec.start_date,
            lines=lines,
        ),
        flight=flight,
        hotel=hotel,
        assumptions=[
            *flight_assumptions,
            *hotel_assumptions,
            *poi_assumptions,
            *per_diem_assumptions,
        ],
    )
