from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from core.models import (
    Area,
    CostedTrip,
    OptimizationPrefs,
    OptimizerResult,
    POI,
    SampleFlight,
    SampleHotel,
    TransferAdvice,
    UserWallet,
)


class PipelineStatus(str, Enum):
    NEEDS_CLARIFICATION = "needs_clarification"
    OK = "ok"
    ERROR = "error"


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


class ItineraryItem(BaseModel):
    poi_id: str
    start_hint: str | None = None
    meal_slots: list[str] = Field(default_factory=list)


class ItineraryDay(BaseModel):
    date: date
    items: list[ItineraryItem] = Field(default_factory=list)


class DraftItinerary(BaseModel):
    hotel_area_id: str
    days: list[ItineraryDay] = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)
    itinerary_quality: Literal["llm", "fallback"] = "llm"


class SelectedHotelArea(BaseModel):
    id: str
    name: str
    reason: str


class BudgetTotals(BaseModel):
    gross_minor: int = Field(ge=0)
    discounts_minor: int = Field(ge=0)
    rewards_value_minor: int = Field(ge=0)
    forex_fees_minor: int = Field(ge=0)
    effective_cost_minor: int = Field(ge=0)
    cash_outlay_now_minor: int = Field(ge=0)
    deferred_value_minor: int = Field(ge=0)
    savings_pct_bp: int


class PaymentStrategyRow(BaseModel):
    line_id: str
    label: str
    card_id: str
    channel: str
    offers: list[str] = Field(default_factory=list)
    action_sentence: str


class CriticIssue(BaseModel):
    severity: Literal["blocking", "warning"]
    kind: Literal[
        "hours",
        "geography",
        "pace",
        "budget",
        "dietary",
        "unsupported_claim",
    ]
    message: str
    poi_id: str | None = None


class CriticVerdict(BaseModel):
    passed: bool
    issues: list[CriticIssue] = Field(default_factory=list)

    @property
    def blocking_issues(self) -> list[CriticIssue]:
        return [issue for issue in self.issues if issue.severity == "blocking"]


class CriticResult(BaseModel):
    verdict: CriticVerdict
    caveats: list[str] = Field(default_factory=list)


class ExplainerOutput(BaseModel):
    summary: str
    itinerary_overview: str
    payment_overview: str
    caveats: list[str] = Field(default_factory=list)


class FinalReport(BaseModel):
    trip_spec: TripSpec
    itinerary: DraftItinerary
    hotel_area: SelectedHotelArea
    flights_pick: SampleFlight | None = None
    hotel_pick: SampleHotel | None = None
    costed_trip: CostedTrip
    optimizer_result: OptimizerResult
    budget_totals: BudgetTotals
    payment_strategy: list[PaymentStrategyRow]
    transfer_advice: TransferAdvice | None = None
    booking_checklist: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    provenance_warnings: list[str] = Field(default_factory=list)
    confidence: float
    caveats: list[str] = Field(default_factory=list)
    summary: str = ""
    itinerary_overview: str = ""
    payment_overview: str = ""
    footer: str = ""
    trace_id: str
    status: PipelineStatus = PipelineStatus.OK


class TripIntakeRequest(BaseModel):
    raw_request: str
    wallet: UserWallet | None = None


class PlanResponse(BaseModel):
    status: PipelineStatus
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    report: FinalReport | None = None
    unresolved: list[str] = Field(default_factory=list)
    error: str | None = None


class JobError(BaseModel):
    code: str
    message: str
    trace_id: str


PIPELINE_STAGES: list[str] = [
    "intake",
    "itinerary",
    "costing",
    "optimizing",
    "critic",
    "explaining",
]


class PlanJobStatus(BaseModel):
    job_id: str
    status: Literal[
        "queued", "running", "needs_clarification", "complete", "failed"
    ]
    stage: Literal[
        "intake",
        "itinerary",
        "costing",
        "optimizing",
        "transfer",
        "critic",
        "explaining",
    ] | None = None
    stage_index: int | None = None
    stages_total: int = len(PIPELINE_STAGES)
    unresolved: list[str] | None = None
    report: FinalReport | None = None
    error: JobError | None = None


class TraceEvent(BaseModel):
    trace_id: str
    name: str
    started_at: datetime
    ended_at: datetime
    model: str | None = None
    tokens: dict[str, int] = Field(default_factory=dict)
    artifact_hash: str
    attributes: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def now(
        cls,
        *,
        trace_id: str,
        name: str,
        artifact_hash: str,
        model: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> TraceEvent:
        timestamp = datetime.now(timezone.utc)
        return cls(
            trace_id=trace_id,
            name=name,
            started_at=timestamp,
            ended_at=timestamp,
            artifact_hash=artifact_hash,
            model=model,
            attributes=attributes or {},
        )


class RetrievalContext(BaseModel):
    pois: list[POI]
    areas: list[Area]
    poi_rows: list[str]
    area_rows: list[str]


class PlannerResult(BaseModel):
    itinerary: DraftItinerary
    used_fallback: bool = False
    repair_attempted: bool = False
    revision_count: int = 0
    caveats: list[str] = Field(default_factory=list)


class EstimatorResult(BaseModel):
    costed_trip: CostedTrip
    flight: SampleFlight | None = None
    hotel: SampleHotel | None = None
    assumptions: list[str] = Field(default_factory=list)


class KernelResult(BaseModel):
    optimizer_result: OptimizerResult
    transfer_advice: TransferAdvice | None = None
