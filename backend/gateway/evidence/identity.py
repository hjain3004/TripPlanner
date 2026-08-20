from datetime import date
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field


class FlightSegmentIdentity(BaseModel):
    origin: str
    destination: str
    departure_at: AwareDatetime
    arrival_at: AwareDatetime
    operating_carrier: str
    flight_number: str


class FlightQuoteIdentity(BaseModel):
    kind: Literal["flight_quote"]
    segments: tuple[FlightSegmentIdentity, ...] = Field(min_length=1)
    cabin: str
    fare_conditions: str


class FlightObservationIdentity(BaseModel):
    kind: Literal["flight_price_observation"]
    provider: str
    origin: str
    destination: str
    depart_date: date
    return_date: date | None
    cabin: str
    stops: int
    observed_bucket: AwareDatetime


class HotelQuoteIdentity(BaseModel):
    kind: Literal["hotel_quote"]
    property_key: str
    check_in: date
    check_out: date
    occupancy_key: str
    room_type: str
    rate_plan: str


class AwardQuoteIdentity(BaseModel):
    kind: Literal["award_quote"]
    program_id: str
    origin: str
    destination: str
    depart_date: date
    return_date: date | None
    cabin: str
    operating_carrier: str


class PlaceClaimIdentity(BaseModel):
    kind: Literal["place_claim"]
    place_id: str
    field: str


class ReferenceFactIdentity(BaseModel):
    kind: Literal["reference_fact"]
    namespace: str
    entity_id: str
    field: str


EvidenceIdentity = Annotated[
    FlightQuoteIdentity
    | FlightObservationIdentity
    | HotelQuoteIdentity
    | AwardQuoteIdentity
    | ReferenceFactIdentity
    | PlaceClaimIdentity,
    Field(discriminator="kind"),
]
