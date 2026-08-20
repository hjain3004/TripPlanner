"""Normalized airport reference-data contracts (offline import, spec 09 §13 G2b).

Fields mirror the OurAirports schema (public domain). Nothing here is
manufactured -- IATA codes, coordinates, municipalities are preserved
exactly as sourced or left None.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from gateway.reference.contracts import SourceProvenance

AirportType = Literal[
    "balloonport",
    "closed_airport",
    "heliport",
    "large_airport",
    "medium_airport",
    "seaplane_base",
    "small_airport",
]


def _upper_or_none(value: str | None) -> str | None:
    return value.strip().upper() if value else None


class AirportRecord(BaseModel):
    id: str
    ident: str
    airport_type: AirportType
    name: str
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    elevation_ft: int | None = None
    continent: str | None = None
    iso_country: str | None = None
    iso_region: str | None = None
    municipality: str | None = None
    scheduled_service: bool
    gps_code: str | None = None
    icao_code: str | None = None
    iata_code: str | None = None
    local_code: str | None = None
    home_link: str | None = None

    _u1 = field_validator("iso_country")(classmethod(lambda cls, v: _upper_or_none(v)))
    _u2 = field_validator("iata_code")(classmethod(lambda cls, v: _upper_or_none(v)))
    _u3 = field_validator("icao_code")(classmethod(lambda cls, v: _upper_or_none(v)))
    _u4 = field_validator("gps_code")(classmethod(lambda cls, v: _upper_or_none(v)))
    _u5 = field_validator("local_code")(classmethod(lambda cls, v: _upper_or_none(v)))


class AirportSnapshot(BaseModel):
    provenance: SourceProvenance
    airports: list[AirportRecord]
