"""Deterministic travel evidence identity — spec 16 §10.

Flight identity hashes ordered segments (origin, destination, departure,
arrival, operating carrier, flight number) plus fare condition, so fare
variants with different baggage/refundability remain distinct. Observation
identity is provider+route+dates+cabin/stops+observed time bucket, and is
never used to deduplicate an observation into a quote.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from gateway.travel.contracts import FlightSegment, TravelerMix


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def flight_quote_id(
    segments: list[FlightSegment], travelers: TravelerMix, *, fare_brand: str | None
) -> str:
    payload = {
        "segments": [
            {
                "origin": s.origin,
                "destination": s.destination,
                "departure_at": s.departure_at.isoformat(),
                "arrival_at": s.arrival_at.isoformat(),
                "operating_airline": s.operating_airline or s.marketing_airline,
                "flight_number": s.flight_number,
            }
            for s in segments
        ],
        "fare_brand": fare_brand,
    }
    return f"fq_{_hash(payload)}"


def flight_observation_id(
    *,
    provider_id: str,
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date | None,
    cabin: str | None,
    stops: int | None,
    observed_time_bucket: str,
) -> str:
    payload = {
        "kind": "observation",
        "provider_id": provider_id,
        "origin": origin,
        "destination": destination,
        "depart_date": depart_date.isoformat(),
        "return_date": return_date.isoformat() if return_date else None,
        "cabin": cabin,
        "stops": stops,
        "observed_time_bucket": observed_time_bucket,
    }
    return f"fo_{_hash(payload)}"


def hotel_quote_id(
    property_id: str,
    check_in: date,
    check_out: date,
    room_name: str | None,
    rate_plan: str | None,
) -> str:
    payload = {
        "property_id": property_id,
        "check_in": check_in.isoformat(),
        "check_out": check_out.isoformat(),
        "room_name": room_name,
        "rate_plan": rate_plan,
    }
    return f"hq_{_hash(payload)}"


def award_quote_id(
    program_id: str,
    origin: str,
    destination: str,
    depart_date: date,
    cabin: str,
    operating_airline: str | None,
) -> str:
    payload = {
        "program_id": program_id,
        "origin": origin,
        "destination": destination,
        "depart_date": depart_date.isoformat(),
        "cabin": cabin,
        "operating_airline": operating_airline,
    }
    return f"aq_{_hash(payload)}"
