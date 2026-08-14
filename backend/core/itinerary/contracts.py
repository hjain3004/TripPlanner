# ruff: noqa: E501, E402
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class RouteCell(BaseModel):
    origin_place_id: str
    destination_place_id: str
    mode: str
    duration_min: int
    distance_km: float
    retrieved_at: datetime
    source: str
    status: Literal["routed", "estimated"]
    confidence: float

    @model_validator(mode="after")
    def validate_routed_source(self) -> "RouteCell":
        if self.status == "routed" and self.source == "geodesic_estimate":
            raise ValueError("An estimate is never labeled routed travel time.")
        return self


class RouteMatrix(BaseModel):
    cells: list[RouteCell]

    def duration_min(self, origin: str, dest: str, mode: str) -> int | None:
        for cell in self.cells:
            if cell.mode == mode:
                if cell.origin_place_id == origin and cell.destination_place_id == dest:
                    return cell.duration_min
                if cell.status == "estimated" and cell.origin_place_id == dest and cell.destination_place_id == origin:
                    return cell.duration_min
        return None


class ItineraryConstraints(BaseModel):
    max_daily_travel_min: int = Field(ge=0)


class RejectionReason(BaseModel):
    code: Literal[
        "overlap",
        "closed_day",
        "unknown_hours_timing_critical",
        "travel_budget_exceeded",
        "travel_time_infeasible",
        "accessibility_excluded",
        "fixed_window_violated",
        "no_evidence_backed_place_id"
    ]
    place_id: str | None = None
    detail: str | None = None


class ItineraryValidation(BaseModel):
    valid: bool
    rejections: list[RejectionReason]


class ItineraryDraft(BaseModel):
    pass
