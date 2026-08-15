from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from core.models import POI, Area, OptimizationPrefs, UserWallet


class TripSpec(BaseModel):
    home_country: Literal["IN", "AE", "US"]
    origin_city: str
    destination_city: str
    start_date: date
    end_date: date
    travelers: int = Field(gt=0)
    budget_minor: int | None = Field(default=None, ge=0)
    budget_currency: str = "INR"
    style: Literal["budget", "balanced", "luxury"]
    interests: list[str] = Field(default_factory=list)
    pace: Literal["relaxed", "moderate", "packed"] = "moderate"
    dietary: list[str] = Field(default_factory=list)
    wallet: UserWallet
    optimization: OptimizationPrefs = Field(default_factory=OptimizationPrefs)
    unresolved: list[str] = Field(default_factory=list)

    @property
    def nights(self) -> int:
        return (self.end_date - self.start_date).days

    @field_validator("origin_city", "destination_city")
    @classmethod
    def normalize_iata(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("city must be an IATA code")
        return normalized

    @field_validator("budget_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_kernel_range(self) -> TripSpec:
        if not 3 <= self.nights <= 7:
            raise ValueError("Kernel MVP supports trips of 3 to 7 nights")
        return self


class TransitSegment(BaseModel):
    duration_min: int
    status: Literal["routed", "estimated"]
    source: str


class Rejection(BaseModel):
    code: str
    place_id: str
    detail: str


class ItineraryItem(BaseModel):
    poi_id: str
    start_hint: str | None = None
    meal_slots: list[str] = Field(default_factory=list)
    start_time: str | None = Field(default=None, exclude=True)
    end_time: str | None = Field(default=None, exclude=True)
    name: str | None = None
    category: str | None = None
    travel_from_previous: TransitSegment | None = None
    evidence: POIEvidence | None = None


class ItineraryDay(BaseModel):
    date: date
    items: list[ItineraryItem] = Field(default_factory=list)
    unmet_needs: list[str] = Field(default_factory=list)
    rejections: list[Rejection] = Field(default_factory=list)


class DraftItinerary(BaseModel):
    hotel_area_id: str
    days: list[ItineraryDay] = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)
    itinerary_quality: Literal["llm", "fallback"] = "llm"
    unverified_suggestions: list[str] = Field(default_factory=list)


class POIEvidence(BaseModel):
    poi_id: str
    status: Literal["live", "cached", "estimated", "stale", "verify_required"]
    last_verified: date
    licence_id: str | None = None
    attribution: str | None = None
    needs_verification: bool


class RetrievalContext(BaseModel):
    pois: list[POI]
    areas: list[Area]
    poi_rows: list[str]
    area_rows: list[str]
    poi_provenance: list[POIEvidence] = Field(default_factory=list)
