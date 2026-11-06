"""Authenticated post-plan proposals and approvals (CP4 Tasks 5 and 7).

The router is intentionally thin: deterministic routing and typed validation happen
before the optional interpreter, while all state changes go through the durable account
store reservation/commit boundary.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from accounts.models import PostPlanOperation, User
from accounts.projection import build_user_wallet
from accounts.store import (
    AccountStore,
    PostPlanOperationConflictError,
    PostPlanOperationInProgressError,
    PostPlanProposalStateError,
    PostPlanQuotaError,
    StalePlanningSessionError,
    StalePostPlanBaseError,
    StalePostPlanWorkspaceError,
    StaleProfileSectionError,
    UnknownPlanningSessionError,
    trip_event_fingerprint,
)
from agents.confirmed_trip import build_inventory_requests, compile_confirmed_input
from agents.estimator import price_in_home
from agents.gateway_estimator import _summary_quote
from agents.models import FinalReport, FlightSelectionRecord, HotelSelectionRecord, PaymentStrategyRow
from agents.post_plan_execution import (
    PostPlanExecutionResult,
    recompute_confirmed_report,
    recompute_flight_selection,
    recompute_hotel_selection,
    refresh_provider_inventory,
    replan_scoped_itinerary,
    spec_for_brief,
)
from agents.post_plan_interpreter import (
    PostPlanInterpretationError,
    PostPlanInterpreter,
    UnsafeCommandText,
    get_post_plan_llm,
    sanitize_command_text,
)
from agents.post_plan_models import RetainedInventory
from api.auth import current_user, get_store, now_utc, require_csrf
from api.post_plan_service import (
    LoadedWorkspace,
    WorkspaceError,
    initialize_from_job,
    initialize_from_saved_revision,
    load_workspace,
    mark_active,
    mark_finished,
    recover_interrupted,
)
from core.models import Channel, SpendCategory, SpendLineItem
from gateway.travel.contracts import FlightPriceObservation, FlightQuote, FlightSearchRequest, TravelerMix
from gateway.travel.product import InventoryQuoteSummary, TravelInventorySnapshot
from planning.brief import profile_group_from_answer
from planning.contracts import ConfirmedBriefSnapshot, PlanningSession
from planning.post_plan import (
    ActionImpact,
    DayOverride,
    ExplainableRef,
    ExplanationRequest,
    HotelSelectionAction,
    FlightSelectionAction,
    PostPlanAction,
    PostPlanInputError,
    RoutingContext,
    RoutingDay,
    RoutingItem,
    ScopedItineraryReplan,
    apply_brief_patch,
    apply_wallet_or_objective,
    classify_command,
    compute_impact,
    impact_context_from_routing,
    validate_action_references,
)
from planning.repository import PlanningSessionRepository

router = APIRouter(prefix="/planning/sessions/{session_id}", tags=["post-plan"])
_ACTION: TypeAdapter[PostPlanAction] = TypeAdapter(PostPlanAction)


class WorkspaceInitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["job", "saved_revision"] = "job"
    trip_id: str | None = None
    revision: int | None = Field(default=None, ge=1)


class ActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_event_id: str = Field(min_length=1, max_length=128)
    expected_session_version: int = Field(ge=0)
    expected_workspace_version: int = Field(ge=1)
    # Accept oversized text here so the route can return its typed 413 response.
    text: str | None = None
    action: dict[str, Any] | None = None

    def model_post_init(self, __context: Any) -> None:
        if (self.text is None) == (self.action is None):
            raise ValueError("provide exactly one of text or action")


class HotelSelectionPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_event_id: str = Field(min_length=1, max_length=128)
    expected_session_version: int = Field(ge=0)
    expected_workspace_version: int = Field(ge=1)
    selection: HotelSelectionAction


class HotelSelectionComputedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hotel_amount_minor: int
    hotel_currency: str
    trip_cost_minor: int
    rewards_value_minor: int
    forex_fees_minor: int
    effective_cost_minor: int
    payment_strategy: list[PaymentStrategyRow]
    assumptions: list[str]
    limitations: list[str]


class HotelSelectionPreviewOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before: HotelSelectionComputedOut
    after: HotelSelectionComputedOut
    selection: HotelSelectionAction


class HotelSelectionOptionsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: dict[str, Any]
    selected: InventoryQuoteSummary | None
    alternatives: list[InventoryQuoteSummary]
    limitations: list[str]


class FlightSelectionPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_event_id: str = Field(min_length=1, max_length=128)
    expected_session_version: int = Field(ge=0)
    expected_workspace_version: int = Field(ge=1)
    selection: FlightSelectionAction


class FlightSelectionComputedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flight_amount_minor: int
    flight_currency: str
    trip_cost_minor: int
    rewards_value_minor: int
    forex_fees_minor: int
    effective_cost_minor: int
    payment_strategy: list[PaymentStrategyRow]
    assumptions: list[str]
    limitations: list[str]


class FlightSelectionPreviewOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before: FlightSelectionComputedOut
    after: FlightSelectionComputedOut
    selection: FlightSelectionAction


class FlightSelectionOptionsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: dict[str, Any]
    selected: InventoryQuoteSummary | None
    alternatives: list[InventoryQuoteSummary]
    observations: list[FlightPriceObservation]
    limitations: list[str]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_event_id: str = Field(min_length=1, max_length=128)
    expected_session_version: int = Field(ge=0)
    expected_workspace_version: int = Field(ge=1)


class WorkspaceRevisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_event_id: str = Field(min_length=1, max_length=128)
    expected_workspace_version: int = Field(ge=1)


class WorkspaceRevisionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trip_id: str
    revision: int
    result_id: str


class PostPlanError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str


_POST_PLAN_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": PostPlanError}
    for status in (401, 403, 404, 409, 410, 413, 422, 429, 503)
}


class PostPlanWorkspaceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    version: int
    current_result_id: str
    workspace: dict[str, Any]
    report: dict[str, Any]
    operations: list[dict[str, Any]]


class ActionProposalOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str
    operation_id: str
    status: str
    action: dict[str, Any]
    impact: dict[str, Any]
    decision: str | None
    preview: HotelSelectionPreviewOut | FlightSelectionPreviewOut | None = None


def _replayed_proposal(operation: PostPlanOperation) -> ActionProposalOut:
    if operation.status != "complete":
        raise _error(
            "OPERATION_NOT_REPLAYABLE",
            operation.error_code or "The original operation did not complete.",
            409,
        )
    payload = json.loads(operation.payload_json)
    action = _ACTION.validate_python(payload["action"])
    impact = ActionImpact.model_validate(payload["impact"])
    return ActionProposalOut(
        proposal_id=operation.operation_id,
        operation_id=operation.operation_id,
        status=operation.status,
        action=action.model_dump(mode="json"),
        impact=impact.model_dump(mode="json"),
        decision=operation.decision,
        preview=(
            TypeAdapter(HotelSelectionPreviewOut | FlightSelectionPreviewOut).validate_python(
                payload["preview"]
            )
            if "preview" in payload
            else None
        ),
    )


def _replayed_decision(operation: PostPlanOperation) -> dict[str, Any]:
    if operation.status != "complete":
        raise _error(
            "OPERATION_NOT_REPLAYABLE",
            operation.error_code or "The original operation did not complete.",
            409,
        )
    outcome = json.loads(operation.payload_json)
    return {
        "operation_id": operation.operation_id,
        "proposal_id": operation.proposal_id,
        "status": operation.status,
        "decision": operation.decision,
        "result_id": operation.result_id,
        **outcome,
    }


def _explanation_for(report: Any, action: ExplanationRequest) -> str:
    """Return a deterministic explanation anchored to the accepted report."""
    if action.target_kind == "cost_line":
        line = next(line for line in report.costed_trip.lines if line.id == action.target_id)
        if action.topic == "how_priced":
            return f"{line.label} is recorded at {line.amount_minor} {line.currency} minor units."
        return f"{line.label} is part of the accepted costed trip because it is in the report."
    if action.target_kind == "itinerary_item":
        item = next(
            item
            for day in report.itinerary.days
            for item in day.items
            if item.poi_id == action.target_id
        )
        return f"{item.name or item.poi_id} is scheduled in the accepted itinerary."
    if action.target_kind == "payment_assignment":
        assignment = next(
            row
            for row in report.optimizer_result.assignments
            if row.line.id == action.target_id
        )
        return (
            f"{assignment.line.label} is assigned to {assignment.card_id} "
            f"via {assignment.channel}."
        )
    if action.target_kind == "transfer_recommendation":
        return "The transfer recommendation is the accepted kernel output for this trip."
    return "The inventory quote is part of the accepted evidence snapshot for this trip."


def _error(code: str, message: str, code_status: int = 422) -> HTTPException:
    return HTTPException(code_status, detail={"code": code, "message": message})


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, UnknownPlanningSessionError):
        return _error("SESSION_NOT_FOUND", "Planning session not found", 404)
    if isinstance(
        exc, (StalePostPlanWorkspaceError, StalePlanningSessionError, StalePostPlanBaseError)
    ):
        return _error("STALE_WORKSPACE", "The plan changed; reload and retry.", 409)
    if isinstance(exc, PostPlanOperationInProgressError):
        return _error("OPERATION_IN_PROGRESS", "Another post-plan operation is running.", 409)
    if isinstance(exc, PostPlanOperationConflictError):
        return _error(
            "IDEMPOTENCY_KEY_REUSED",
            "That client event id was already used for a different selection request.",
            409,
        )
    if isinstance(exc, PostPlanProposalStateError):
        return _error("PROPOSAL_NOT_PENDING", "This proposal is no longer pending.", 409)
    if isinstance(exc, PostPlanQuotaError):
        return _error(
            "POST_PLAN_QUOTA_EXCEEDED", "This session has reached its post-plan limit.", 429
        )
    if isinstance(exc, StaleProfileSectionError):
        return _error(
            "PROFILE_SECTION_CONFLICT", "That preference section changed; reload and retry.", 409
        )
    if isinstance(exc, WorkspaceError):
        return _error(exc.code, str(exc), 409)
    if isinstance(exc, ValidationError):
        return _error("INVALID_ACTION", "The action is not valid for this workspace.")
    return _error("POST_PLAN_UNAVAILABLE", "Post-plan actions are temporarily unavailable.", 503)


def _session(store: AccountStore, user: User, session_id: str) -> PlanningSession:
    session = PlanningSessionRepository(store).get(user_id=user.id, session_id=session_id)
    if session is None:
        raise UnknownPlanningSessionError(session_id)
    if session.expires_at <= now_utc() and session.saved_trip_id is None:
        raise _error("SESSION_EXPIRED", "Planning session has expired.", 410)
    return session


def _routing_context(report: Any, brief: Any) -> RoutingContext:
    days = [
        RoutingDay(
            date=day.date,
            items=[
                RoutingItem(poi_id=item.poi_id, name=getattr(item, "name", item.poi_id))
                for item in day.items
            ],
        )
        for day in report.itinerary.days
    ]
    explainable = [
        ExplainableRef(
            kind="itinerary_item", ref_id=item.poi_id, label=getattr(item, "name", item.poi_id)
        )
        for day in report.itinerary.days
        for item in day.items
    ]
    explainable.extend(
        ExplainableRef(kind="cost_line", ref_id=line.id, label=line.label)
        for line in report.costed_trip.lines
    )
    return RoutingContext(days=days, candidates=[], explainable=explainable, brief=brief)


def _proposal_action(body: ActionIn, context: RoutingContext) -> PostPlanAction:
    if body.action is not None:
        action = _ACTION.validate_python(body.action)
        validate_action_references(action, context)
        return action
    assert body.text is not None
    deterministic = classify_command(body.text, context)
    if deterministic is not None:
        validate_action_references(deterministic, context)
        return deterministic
    raise RuntimeError("semantic interpretation is performed by the route")


def _after_brief(before: Any, action: PostPlanAction, store: AccountStore, user: User) -> Any:
    if action.kind == "scoped_itinerary_replan" and action.scope == "dates":
        return before
    if action.kind in {"scoped_itinerary_replan", "provider_invalidating_change"}:
        assert action.patch is not None
        return apply_brief_patch(before, action.patch)
    if action.kind == "wallet_or_objective_change":
        wallet = build_user_wallet(store.wallet_entries(user.id))
        return apply_wallet_or_objective(before, action, current_wallet=wallet)
    return before


def _section_fingerprint(profile: Any, section: str) -> str:
    value = getattr(profile, section)
    return hashlib.sha256(
        json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _profile_candidate(
    store: AccountStore, user: User, action: Any, *, now: Any
) -> tuple[Any, str]:
    current = store.get_travel_preferences(user.id)
    if current is None:
        from accounts.models import TravelPreferenceProfile

        current = TravelPreferenceProfile(user_id=user.id, updated_at=now)
    base_fingerprint = _section_fingerprint(current, action.section)
    group = profile_group_from_answer(action.section, action.candidate, now=now)
    candidate = current.model_copy(update={action.section: group, "updated_at": now})
    return candidate, base_fingerprint


def _advance_session_snapshot(
    store: AccountStore, user_id: str, session_id: str, *, now: Any
) -> Any:
    typed = PlanningSessionRepository(store).get(user_id=user_id, session_id=session_id)
    if typed is None:
        raise UnknownPlanningSessionError(session_id)
    return PlanningSessionRepository.snapshot_of(
        typed.model_copy(update={"version": typed.version + 1, "updated_at": now})
    )


def _loaded(store: AccountStore, user: User, session_id: str) -> LoadedWorkspace:
    loaded = load_workspace(store, user_id=user.id, session_id=session_id)
    if loaded is None:
        raise _error("WORKSPACE_NOT_INITIALIZED", "Initialize the post-plan workspace first.", 409)
    return loaded


def _hotel_snapshot(loaded: LoadedWorkspace) -> TravelInventorySnapshot:
    retained = loaded.workspace.inventory
    if retained is None or retained.snapshot_json is None:
        raise _error(
            "HOTEL_INVENTORY_UNAVAILABLE",
            "This trip has no retained server-owned hotel inventory snapshot.",
            409,
        )
    return TravelInventorySnapshot.model_validate_json(retained.snapshot_json)


def _flight_snapshot(loaded: LoadedWorkspace) -> TravelInventorySnapshot:
    retained = loaded.workspace.inventory
    if retained is None or retained.snapshot_json is None:
        raise _error(
            "FLIGHT_INVENTORY_UNAVAILABLE",
            "This trip has no retained server-owned flight inventory snapshot.",
            409,
        )
    return TravelInventorySnapshot.model_validate_json(retained.snapshot_json)


def _traveler_total(travelers: TravelerMix) -> int:
    return travelers.adults + travelers.children + travelers.infants


def _matches_retained_flight_request(quote: FlightQuote, request: FlightSearchRequest) -> bool:
    """Require a continuous, complete itinerary; chronology alone is not identity."""
    expected_trip_type = "round_trip" if request.return_date is not None else "one_way"
    if quote.trip_type != expected_trip_type or quote.travelers != request.travelers:
        return False
    segments = quote.segments
    if (
        segments[0].origin != request.origin
        or segments[0].departure_at.date() != request.depart_date
        or any(left.destination != right.origin for left, right in zip(segments, segments[1:]))
    ):
        return False
    destination_indexes = [
        index for index, segment in enumerate(segments) if segment.destination == request.destination
    ]
    if not destination_indexes:
        return False
    if request.return_date is None:
        return segments[-1].destination == request.destination
    outbound_end = destination_indexes[0]
    return (
        outbound_end < len(segments) - 1
        and segments[-1].destination == request.origin
        and segments[-1].departure_at.date() == request.return_date
    )


def _flight_selection_resolution(
    loaded: LoadedWorkspace,
    action: FlightSelectionAction,
    *,
    user: User,
    now: Any,
) -> tuple[SpendLineItem, FlightSelectionRecord]:
    """Resolve only a retained complete quote, never a discovery observation."""
    snapshot = _flight_snapshot(loaded)
    retained = loaded.workspace.inventory
    assert retained is not None
    if retained.flight_fingerprint is not None:
        from planning.post_plan import flight_fingerprint

        if retained.flight_fingerprint != flight_fingerprint(loaded.workspace.brief):
            raise _error("STALE_FLIGHT_INVENTORY", "The retained flight inventory no longer matches this trip.", 409)
    inputs = compile_confirmed_input(
        ConfirmedBriefSnapshot(
            revision=loaded.workspace.confirmed_brief_revision,
            brief=loaded.workspace.brief,
            confirmed_at=loaded.workspace.updated_at,
        )
    )
    expected_request, _hotel_request = build_inventory_requests(inputs, loaded.report.itinerary)
    if snapshot.flight_request != expected_request or not snapshot.is_current(now):
        raise _error("STALE_FLIGHT_INVENTORY", "The retained flight request is no longer current for this trip.", 409)
    quote = next((candidate for candidate in snapshot.flights if candidate.id == action.quote_id), None)
    linked_provider_id = quote.evidence.provider_id if quote is not None else None
    if action.source == "inventory_quote":
        if quote is None:
            raise _error("FLIGHT_CANDIDATE_NOT_FOUND", "That flight is not in the retained complete inventory.")
        scope = snapshot.flight_scopes.get(quote.id)
        if scope is None or not scope.cost_eligible or scope.travelers != _traveler_total(expected_request.travelers):
            raise _error("FLIGHT_PRICE_NOT_ADMISSIBLE", "That flight price has no verified party scope for this trip.")
        if quote.evidence.status == "stale":
            raise _error("FLIGHT_EVIDENCE_STALE", "That flight evidence is stale; reload the alternatives.", 409)
        if quote.travelers != expected_request.travelers or quote.currency != expected_request.currency:
            raise _error("FLIGHT_IDENTITY_MISMATCH", "That flight does not match the retained traveler or currency request.")
        if (
            not _matches_retained_flight_request(quote, expected_request)
        ):
            raise _error("FLIGHT_IDENTITY_MISMATCH", "That flight itinerary does not match the retained trip.")
        if not quote.purchasable_channels:
            raise _error("FLIGHT_PAYMENT_CHANNEL_UNKNOWN", "This flight has no supported payment channel for a card recommendation.")
        try:
            converted = price_in_home(quote.total_minor, quote.currency, loaded.report.costed_trip.home_currency, _get_kb())
        except ValueError as exc:
            raise _error("FLIGHT_FX_UNAVAILABLE", "The retained flight currency cannot be priced in the trip currency.") from exc
        if scope.basis == "sample_per_traveler_trip":
            # The seed quote is per traveler: preserve its per-transaction conversion order.
            converted = price_in_home(
                quote.total_minor, quote.currency, loaded.report.costed_trip.home_currency, _get_kb()
            ) * _traveler_total(expected_request.travelers)
            amount_scope: Literal["party_total", "per_traveler"] = "per_traveler"
        else:
            amount_scope = "party_total"
        record = FlightSelectionRecord(
            source="inventory_quote", quote_id=quote.id, provider_id=quote.evidence.provider_id,
            amount_minor=quote.total_minor, currency=quote.currency,
            covers=f"server-owned quote scope: {scope.basis}", amount_scope=amount_scope,
            payment_channel=cast(Channel, quote.purchasable_channels[0]), assumptions=list(action.assumptions),
            limitations=list(quote.evidence.notes), recorded_at=now, recorded_by=user.id,
            session_id=loaded.snapshot.session_id, trip_id=loaded.snapshot.saved_trip_id,
        )
        return SpendLineItem(
            id=f"flight:{quote.id}", label="Selected retained flight quote", category=SpendCategory.FLIGHTS,
            amount_minor=converted, currency=loaded.report.costed_trip.home_currency,
            available_channels=[cast(Channel, channel) for channel in quote.purchasable_channels], merchant_hint=quote.evidence.provider_id,
        ), record

    assert action.amount_minor is not None and action.currency is not None and action.covers is not None
    assert action.amount_scope is not None
    if action.payment_channel is None:
        raise _error("FLIGHT_PAYMENT_CHANNEL_REQUIRED", "A traveler-provided total needs an explicit payment-channel assumption before a card recommendation can be computed.")
    if action.quote_id is not None and quote is None:
        raise _error("FLIGHT_CANDIDATE_NOT_FOUND", "The linked flight is not in the retained complete inventory.")
    try:
        converted = price_in_home(action.amount_minor, action.currency, loaded.report.costed_trip.home_currency, _get_kb())
    except ValueError as exc:
        raise _error("FLIGHT_FX_UNAVAILABLE", "The supplied flight currency cannot be priced in the trip currency.") from exc
    if action.amount_scope == "per_traveler":
        converted *= _traveler_total(expected_request.travelers)
    record = FlightSelectionRecord(
        source="user_provided_total", quote_id=action.quote_id, provider_id=linked_provider_id,
        amount_minor=action.amount_minor, currency=action.currency, covers=action.covers,
        amount_scope=action.amount_scope, payment_channel=action.payment_channel,
        assumptions=[*action.assumptions, f"Payment channel assumed: {action.payment_channel.value}"],
        limitations=[
            "Traveler-provided planning estimate; not a verified provider quote, fare or booking guarantee.",
            "Taxes, fees, availability, itinerary details and fare terms are represented only by the stated assumptions.",
        ],
        recorded_at=now, recorded_by=user.id, session_id=loaded.snapshot.session_id,
        trip_id=loaded.snapshot.saved_trip_id,
    )
    selection_key = hashlib.sha256(
        json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    return SpendLineItem(
        id=f"flight:user:{selection_key}", label="Traveler-entered flight total (planning estimate)",
        category=SpendCategory.FLIGHTS, amount_minor=converted,
        currency=loaded.report.costed_trip.home_currency, available_channels=[action.payment_channel],
        merchant_hint=None,
    ), record


def _hotel_selection_resolution(
    loaded: LoadedWorkspace,
    action: HotelSelectionAction,
    *,
    user: User,
    now: Any,
) -> tuple[SpendLineItem, HotelSelectionRecord]:
    snapshot = _hotel_snapshot(loaded)
    retained = loaded.workspace.inventory
    assert retained is not None
    if retained.hotel_fingerprint is not None:
        from planning.post_plan import hotel_fingerprint

        if retained.hotel_fingerprint != hotel_fingerprint(
            loaded.workspace.brief, hotel_area_id=retained.retained_hotel_area_id
        ):
            raise _error(
                "STALE_HOTEL_INVENTORY",
                "The retained hotel inventory no longer matches this trip.",
                409,
            )
    inputs = compile_confirmed_input(
        ConfirmedBriefSnapshot(
            revision=loaded.workspace.confirmed_brief_revision,
            brief=loaded.workspace.brief,
            confirmed_at=loaded.workspace.updated_at,
        )
    )
    _flight_request, expected_hotel_request = build_inventory_requests(
        inputs, loaded.report.itinerary
    )
    if snapshot.hotel_request != expected_hotel_request:
        raise _error(
            "STALE_HOTEL_INVENTORY",
            "The retained hotel request no longer matches the confirmed trip.",
            409,
        )
    quote = next(
        (candidate for candidate in snapshot.hotels if candidate.id == action.quote_id),
        None,
    )
    linked_provider_id = quote.evidence.provider_id if quote is not None else None
    if action.source == "inventory_quote":
        if quote is None:
            raise _error(
                "HOTEL_CANDIDATE_NOT_FOUND",
                "That hotel is not in the retained inventory.",
            )
        scope = snapshot.hotel_scopes.get(quote.id)
        if scope is None or not scope.cost_eligible:
            raise _error(
                "HOTEL_PRICE_NOT_ADMISSIBLE",
                "That hotel is comparison-only because its price scope is incomplete.",
            )
        if quote.evidence.status == "stale":
            raise _error(
                "HOTEL_EVIDENCE_STALE",
                "That hotel evidence is stale; reload the alternatives.",
                409,
            )
        source_amount = quote.total_minor
        source_currency = quote.currency
        amount = price_in_home(
            source_amount, source_currency, loaded.report.costed_trip.home_currency, _get_kb()
        )
        if scope.basis == "sample_nightly_stay":
            nights = loaded.report.trip_spec.nights
            # Preserve the sample estimator's frozen rounding order: convert
            # the exact nightly amount, then multiply by nights.
            amount = price_in_home(
                source_amount // nights,
                source_currency,
                loaded.report.costed_trip.home_currency,
                _get_kb(),
            ) * nights
        channels = list(quote.purchasable_channels)
        if not channels:
            raise _error(
                "HOTEL_PAYMENT_CHANNEL_UNKNOWN",
                "This admissible hotel has no supported payment channel, so no card "
                "recommendation can be computed.",
            )
        limitations = list(quote.evidence.notes)
        covers = f"server-owned quote scope: {scope.basis}"
        record = HotelSelectionRecord(
            source="inventory_quote",
            quote_id=quote.id,
            provider_id=quote.evidence.provider_id,
            amount_minor=source_amount,
            currency=source_currency,
            covers=covers,
            payment_channel=channels[0],
            assumptions=list(action.assumptions),
            limitations=limitations,
            recorded_at=now,
            recorded_by=user.id,
            session_id=loaded.snapshot.session_id,
            trip_id=loaded.snapshot.saved_trip_id,
        )
        line = SpendLineItem(
            id=f"hotel:{quote.id}",
            label=f"{quote.name} ({loaded.report.trip_spec.nights} nights)",
            category=SpendCategory.HOTELS,
            amount_minor=amount,
            currency=loaded.report.costed_trip.home_currency,
            available_channels=channels,
            merchant_hint=quote.name,
        )
        return line, record

    assert (
        action.amount_minor is not None
        and action.currency is not None
        and action.covers is not None
    )
    if action.payment_channel is None:
        raise _error(
            "HOTEL_PAYMENT_CHANNEL_REQUIRED",
            "A user-provided total needs an explicit payment-channel assumption "
            "before a card recommendation can be computed.",
        )
    if action.quote_id is not None and quote is None:
        raise _error(
            "HOTEL_CANDIDATE_NOT_FOUND",
            "The linked hotel is not in the retained inventory.",
        )
    amount = price_in_home(
        action.amount_minor,
        action.currency,
        loaded.report.costed_trip.home_currency,
        _get_kb(),
    )
    limitations = [
        "User-provided planning total; not a verified provider quote or booking guarantee.",
        "Taxes, fees, room availability and purchase channel are represented only "
        "by the stated assumptions.",
    ]
    record = HotelSelectionRecord(
        source="user_provided_total",
        quote_id=action.quote_id,
        provider_id=linked_provider_id,
        amount_minor=action.amount_minor,
        currency=action.currency,
        covers=action.covers,
        payment_channel=action.payment_channel,
        assumptions=[
            *action.assumptions,
            f"Payment channel assumed: {action.payment_channel.value}",
        ],
        limitations=limitations,
        recorded_at=now,
        recorded_by=user.id,
        session_id=loaded.snapshot.session_id,
        trip_id=loaded.snapshot.saved_trip_id,
    )
    selection_key = hashlib.sha256(
        json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    return (
        SpendLineItem(
            id=f"hotel:user:{selection_key}",
            label=f"Traveler-entered hotel total ({loaded.report.trip_spec.nights} nights)",
            category=SpendCategory.HOTELS,
            amount_minor=amount,
            currency=loaded.report.costed_trip.home_currency,
            available_channels=[action.payment_channel],
            merchant_hint=None,
        ),
        record,
    )


def _get_kb() -> Any:
    from api.main import get_kb

    return get_kb()


def _hotel_computed(
    report: FinalReport, *, limitations: list[str] | None = None
) -> HotelSelectionComputedOut:
    hotel = next(
        line for line in report.costed_trip.lines if line.category is SpendCategory.HOTELS
    )
    return HotelSelectionComputedOut(
        hotel_amount_minor=hotel.amount_minor,
        hotel_currency=hotel.currency,
        trip_cost_minor=report.budget_totals.gross_minor,
        rewards_value_minor=report.budget_totals.rewards_value_minor,
        forex_fees_minor=report.budget_totals.forex_fees_minor,
        effective_cost_minor=report.budget_totals.effective_cost_minor,
        payment_strategy=report.payment_strategy,
        assumptions=report.assumptions,
        limitations=limitations or [],
    )


def _flight_computed(
    report: FinalReport, *, limitations: list[str] | None = None
) -> FlightSelectionComputedOut:
    flight = next(
        line for line in report.costed_trip.lines if line.category is SpendCategory.FLIGHTS
    )
    return FlightSelectionComputedOut(
        flight_amount_minor=flight.amount_minor,
        flight_currency=flight.currency,
        trip_cost_minor=report.budget_totals.gross_minor,
        rewards_value_minor=report.budget_totals.rewards_value_minor,
        forex_fees_minor=report.budget_totals.forex_fees_minor,
        effective_cost_minor=report.budget_totals.effective_cost_minor,
        payment_strategy=report.payment_strategy,
        assumptions=report.assumptions,
        limitations=limitations or [],
    )


def _workspace_out(store: AccountStore, user: User, session_id: str) -> PostPlanWorkspaceOut:
    loaded = _loaded(store, user, session_id)
    return PostPlanWorkspaceOut(
        session_id=session_id,
        version=loaded.snapshot.version,
        current_result_id=loaded.snapshot.current_result_id,
        workspace=loaded.workspace.model_dump(mode="json"),
        report=loaded.report.model_dump(mode="json"),
        operations=[
            o.model_dump(mode="json")
            for o in store.post_plan_operations(user_id=user.id, session_id=session_id)
        ],
    )


@router.post("/workspace", response_model=PostPlanWorkspaceOut, responses=_POST_PLAN_ERRORS)
def initialize_workspace(
    session_id: str,
    payload: WorkspaceInitIn,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
    request: Request,
) -> PostPlanWorkspaceOut:
    require_csrf(request)
    try:
        session = _session(store, user, session_id)
        if payload.source == "saved_revision":
            if payload.trip_id is None or payload.revision is None:
                raise _error("INVALID_SOURCE", "A saved revision requires trip_id and revision.")
            initialize_from_saved_revision(
                store,
                user_id=user.id,
                session=session,
                trip_id=payload.trip_id,
                revision=payload.revision,
                now=now_utc(),
            )
        else:
            initialize_from_job(store, user_id=user.id, session=session, now=now_utc())
        return _workspace_out(store, user, session_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _map_error(exc) from exc


@router.get("/workspace", response_model=PostPlanWorkspaceOut, responses=_POST_PLAN_ERRORS)
def get_workspace(
    session_id: str,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> PostPlanWorkspaceOut:
    try:
        _session(store, user, session_id)
        recover_interrupted(store, user_id=user.id, session_id=session_id, now=now_utc())
        return _workspace_out(store, user, session_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/actions", response_model=ActionProposalOut, responses=_POST_PLAN_ERRORS)
def propose_action(
    session_id: str,
    body: ActionIn,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> ActionProposalOut:
    require_csrf(request)
    try:
        loaded = _loaded(store, user, session_id)
        context = _routing_context(loaded.report, loaded.workspace.brief)
        clean_text: str | None = None
        if body.text is not None:
            try:
                clean_text = sanitize_command_text(body.text)
            except UnsafeCommandText as exc:
                raise _error("UNSAFE_INPUT", str(exc), 422) from None
            except PostPlanInputError as exc:
                code = 413 if len(body.text) > 2000 else 422
                raise _error(
                    "INPUT_TOO_LARGE" if code == 413 else "INVALID_ACTION", str(exc), code
                ) from None
        action: PostPlanAction
        if body.action is not None or (
            clean_text is not None and classify_command(clean_text, context) is not None
        ):
            action = _proposal_action(body.model_copy(update={"text": clean_text}), context)
        else:
            if clean_text is None:
                raise _error("INVALID_ACTION", "An action or text is required.")
            operation = _reserve(
                store,
                user,
                session_id,
                body,
                kind="propose",
                action_kind=None,
                interpreter_calls=1,
                payload={"text": clean_text},
            )
            if operation.status != "reserved":
                return _replayed_proposal(operation)
            mark_active(operation.operation_id)
            try:
                action = PostPlanInterpreter(get_post_plan_llm()).interpret(context, clean_text)
                validate_action_references(action, context)
            except PostPlanInterpretationError as exc:
                store.fail_post_plan_operation(
                    user_id=user.id,
                    session_id=session_id,
                    event_id=body.client_event_id,
                    fingerprint=operation.fingerprint,
                    expected_workspace_version=operation.reserved_workspace_version
                    or body.expected_workspace_version,
                    error_code=exc.reason,
                    updated_at=now_utc(),
                )
                raise _error("INTERPRETATION_" + exc.reason.upper(), str(exc)) from None
            except Exception:
                store.fail_post_plan_operation(
                    user_id=user.id,
                    session_id=session_id,
                    event_id=body.client_event_id,
                    fingerprint=operation.fingerprint,
                    expected_workspace_version=operation.reserved_workspace_version
                    or body.expected_workspace_version,
                    error_code="invalid",
                    updated_at=now_utc(),
                )
                raise
            finally:
                mark_finished(operation.operation_id)
        if isinstance(action, (HotelSelectionAction, FlightSelectionAction)):
            prior = store.get_post_plan_operation(
                user_id=user.id, event_id=body.client_event_id
            )
            if prior is not None:
                prior_payload = json.loads(prior.payload_json)
                if prior_payload.get("action") != action.model_dump(mode="json"):
                    raise PostPlanOperationConflictError(
                        "the selection event id was already used for a different request"
                    )
                return _replayed_proposal(prior)
        after = _after_brief(loaded.workspace.brief, action, store, user)
        impact = compute_impact(
            loaded.workspace.brief,
            after,
            action=action,
            context=impact_context_from_routing(context),
        )
        selection_preview: HotelSelectionPreviewOut | FlightSelectionPreviewOut | None = None
        if isinstance(action, HotelSelectionAction):
            hotel_line, record = _hotel_selection_resolution(
                loaded, action, user=user, now=now_utc()
            )
            preview_report = recompute_hotel_selection(
                loaded.report,
                hotel_line=hotel_line,
                record=record,
                kb=_get_kb(),
                now=now_utc(),
            )
            selection_preview = HotelSelectionPreviewOut(
                before=_hotel_computed(loaded.report),
                after=_hotel_computed(preview_report, limitations=record.limitations),
                selection=action,
            )
        elif isinstance(action, FlightSelectionAction):
            flight_line, flight_record = _flight_selection_resolution(
                loaded, action, user=user, now=now_utc()
            )
            preview_report = recompute_flight_selection(
                loaded.report, flight_line=flight_line, record=flight_record, kb=_get_kb(), now=now_utc()
            )
            selection_preview = FlightSelectionPreviewOut(
                before=_flight_computed(loaded.report),
                after=_flight_computed(preview_report, limitations=flight_record.limitations),
                selection=action,
            )
        proposal_payload: dict[str, Any] = {
            "action": action.model_dump(mode="json"),
            "impact": impact.model_dump(mode="json"),
        }
        if selection_preview is not None:
            proposal_payload["preview"] = selection_preview.model_dump(mode="json")
        if action.kind == "wallet_or_objective_change":
            proposal_payload["wallet_fingerprint"] = hashlib.sha256(
                json.dumps(
                    build_user_wallet(store.wallet_entries(user.id)).model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        if action.kind == "profile_update_proposal":
            _candidate, base_fingerprint = _profile_candidate(
                store, user, action, now=now_utc()
            )
            proposal_payload["profile_base_fingerprint"] = base_fingerprint
        operation = (
            _reserve(
                store,
                user,
                session_id,
                body,
                kind="propose",
                action_kind=action.kind,
                interpreter_calls=0,
                payload={
                    **proposal_payload,
                },
            )
            if body.action is not None
            or (clean_text is not None and classify_command(clean_text, context) is not None)
            else store.get_post_plan_operation(user_id=user.id, event_id=body.client_event_id)
        )
        assert operation is not None
        if operation.status != "reserved":
            return _replayed_proposal(operation)
        current = store.get_planning_session_snapshot(user_id=user.id, session_id=session_id)
        assert current is not None
        committed = loaded.snapshot.model_copy(update={"updated_at": now_utc()})
        finished = store.commit_post_plan_operation(
            user_id=user.id,
            session_id=session_id,
            event_id=body.client_event_id,
            fingerprint=operation.fingerprint,
            expected_workspace_version=operation.reserved_workspace_version
            or loaded.snapshot.version,
            workspace=committed,
            session=_advance_session_snapshot(store, user.id, session_id, now=now_utc()),
            report_json=None,
            outcome_json=json.dumps(
                {
                    **proposal_payload,
                },
                sort_keys=True,
            ),
            updated_at=now_utc(),
        )
        return ActionProposalOut(
            proposal_id=finished.operation_id,
            operation_id=finished.operation_id,
            status=finished.status,
            action=action.model_dump(mode="json"),
            impact=impact.model_dump(mode="json"),
            decision=finished.decision,
            preview=selection_preview,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _map_error(exc) from exc


@router.get(
    "/hotel-selection",
    response_model=HotelSelectionOptionsOut,
    responses=_POST_PLAN_ERRORS,
)
def hotel_selection_options(
    session_id: str,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> HotelSelectionOptionsOut:
    """Expose only the server-owned hotel alternatives retained for this workspace."""
    try:
        loaded = _loaded(store, user, session_id)
        snapshot = _hotel_snapshot(loaded)
        if loaded.report.travel_inventory is None:
            raise _error("HOTEL_INVENTORY_UNAVAILABLE", "Hotel alternatives are unavailable.", 409)
        selected_id = (
            loaded.report.travel_inventory.hotel.quote_id
            if loaded.report.travel_inventory.hotel is not None
            else None
        )
        hotel_options = [
            _summary_quote(
                "hotel",
                quote,
                selected=quote.id == selected_id,
                scope=snapshot.hotel_scopes[quote.id],
            )
            for quote in snapshot.hotels
            if quote.id in snapshot.hotel_scopes
        ]
        selected = next((option for option in hotel_options if option.selected), None)
        alternatives = [option for option in hotel_options if not option.selected]
        return HotelSelectionOptionsOut(
            request=snapshot.hotel_request.model_dump(mode="json"),
            selected=selected,
            alternatives=alternatives,
            limitations=list(loaded.report.travel_inventory.limitations),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post(
    "/hotel-selection/preview",
    response_model=ActionProposalOut,
    responses=_POST_PLAN_ERRORS,
)
def preview_hotel_selection(
    session_id: str,
    body: HotelSelectionPreviewIn,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> ActionProposalOut:
    """Create a durable CP4 proposal whose response contains the deterministic preview."""
    return propose_action(
        session_id=session_id,
        body=ActionIn(
            client_event_id=body.client_event_id,
            expected_session_version=body.expected_session_version,
            expected_workspace_version=body.expected_workspace_version,
            action=body.selection.model_dump(mode="json"),
        ),
        request=request,
        user=user,
        store=store,
    )


@router.get(
    "/flight-selection",
    response_model=FlightSelectionOptionsOut,
    responses=_POST_PLAN_ERRORS,
)
def flight_selection_options(
    session_id: str,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> FlightSelectionOptionsOut:
    """Expose retained complete flight quotes and separate non-bookable observations."""
    try:
        loaded = _loaded(store, user, session_id)
        snapshot = _flight_snapshot(loaded)
        if loaded.report.travel_inventory is None:
            raise _error("FLIGHT_INVENTORY_UNAVAILABLE", "Flight alternatives are unavailable.", 409)
        selected_id = (
            loaded.report.travel_inventory.flight.quote_id
            if loaded.report.travel_inventory.flight is not None
            else None
        )
        options = [
            _summary_quote("flight", quote, selected=quote.id == selected_id, scope=snapshot.flight_scopes[quote.id])
            for quote in snapshot.flights
            if quote.id in snapshot.flight_scopes
        ]
        return FlightSelectionOptionsOut(
            request=snapshot.flight_request.model_dump(mode="json"),
            selected=next((option for option in options if option.selected), None),
            alternatives=[option for option in options if not option.selected],
            observations=list(snapshot.flight_observations),
            limitations=[
                *loaded.report.travel_inventory.limitations,
                "Observed flight prices are discovery evidence only and cannot be selected or costed.",
                *(
                    [
                        "A retained one-way quote is shown as evidence only; it cannot be selected for this round trip."
                    ]
                    if snapshot.flight_request.return_date is not None
                    and any(quote.trip_type != "round_trip" for quote in snapshot.flights)
                    else []
                ),
            ],
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post(
    "/flight-selection/preview",
    response_model=ActionProposalOut,
    responses=_POST_PLAN_ERRORS,
)
def preview_flight_selection(
    session_id: str,
    body: FlightSelectionPreviewIn,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> ActionProposalOut:
    return propose_action(
        session_id=session_id,
        body=ActionIn(
            client_event_id=body.client_event_id,
            expected_session_version=body.expected_session_version,
            expected_workspace_version=body.expected_workspace_version,
            action=body.selection.model_dump(mode="json"),
        ),
        request=request,
        user=user,
        store=store,
    )


def _reserve(
    store: AccountStore,
    user: User,
    session_id: str,
    body: ActionIn | DecisionIn,
    *,
    kind: Literal["propose", "approve", "reject"],
    action_kind: str | None,
    interpreter_calls: int,
    payload: dict[str, Any],
    proposal_id: str | None = None,
) -> Any:

    canonical = json.dumps(
        {
            "kind": kind,
            "action_kind": action_kind,
            "proposal_id": proposal_id,
            "payload": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    op = PostPlanOperation(
        operation_id=uuid4().hex,
        user_id=user.id,
        session_id=session_id,
        kind=kind,
        event_id=body.client_event_id,
        fingerprint=hashlib.sha256(canonical.encode()).hexdigest(),
        expected_workspace_version=body.expected_workspace_version,
        expected_session_version=body.expected_session_version,
        action_kind=action_kind,
        interpreter_calls=interpreter_calls,
        proposal_id=proposal_id,
        payload_json=json.dumps(payload, sort_keys=True),
        created_at=now_utc(),
        updated_at=now_utc(),
    )
    return store.reserve_post_plan_operation(
        user_id=user.id,
        session_id=session_id,
        operation=op,
        expected_workspace_version=body.expected_workspace_version,
        expected_session_version=body.expected_session_version,
    )


def _decision(
    session_id: str,
    proposal_id: str,
    body: DecisionIn,
    *,
    approve: bool,
    request: Request,
    user: User,
    store: AccountStore,
) -> dict[str, Any]:
    require_csrf(request)
    loaded = _loaded(store, user, session_id)
    proposal = store.get_post_plan_operation_by_id(
        user_id=user.id, session_id=session_id, operation_id=proposal_id
    )
    if proposal is None or proposal.kind != "propose" or proposal.status != "complete":
        raise _error("PROPOSAL_NOT_FOUND", "No such proposal.", 404)
    data = json.loads(proposal.payload_json)
    action = _ACTION.validate_python(data["action"])
    decision_body = body.model_copy()
    operation = _reserve(
        store,
        user,
        session_id,
        decision_body,
        kind="approve" if approve else "reject",
        action_kind=action.kind,
        interpreter_calls=0,
        payload={"proposal_id": proposal_id},
        proposal_id=proposal_id,
    )
    if operation.status != "reserved":
        return _replayed_decision(operation)
    mark_active(operation.operation_id)
    try:
        current = store.get_planning_session_snapshot(user_id=user.id, session_id=session_id)
        assert current is not None
        now = now_utc()
        workspace_domain = loaded.workspace
        workspace = loaded.snapshot.model_copy(update={"updated_at": now})
        report_json = None
        profile_update = None
        profile_section = None
        profile_base_fingerprint = None
        execution = None
        explanation = None
        if approve and isinstance(action, ExplanationRequest):
            explanation = _explanation_for(loaded.report, action)
        if approve and isinstance(action, HotelSelectionAction):
            from api.main import get_kb

            hotel_line, record = _hotel_selection_resolution(
                loaded, action, user=user, now=now
            )
            report = recompute_hotel_selection(
                loaded.report,
                hotel_line=hotel_line,
                record=record,
                kb=get_kb(),
                now=now,
            )
            execution = PostPlanExecutionResult(report=report, brief=loaded.workspace.brief)
        elif approve and isinstance(action, FlightSelectionAction):
            from api.main import get_kb

            flight_line, flight_record = _flight_selection_resolution(
                loaded, action, user=user, now=now
            )
            report = recompute_flight_selection(
                loaded.report,
                flight_line=flight_line,
                record=flight_record,
                kb=get_kb(),
                now=now,
            )
            execution = PostPlanExecutionResult(report=report, brief=loaded.workspace.brief)
        elif approve and action.kind == "wallet_or_objective_change":
            expected_wallet = data.get("wallet_fingerprint")
            actual_wallet = hashlib.sha256(
                json.dumps(
                    build_user_wallet(store.wallet_entries(user.id)).model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            if expected_wallet != actual_wallet:
                raise _error("STALE_WALLET", "The stored wallet changed; reload and retry.", 409)
            after = _after_brief(loaded.workspace.brief, action, store, user)
            from api.main import get_kb

            new_spec = spec_for_brief(loaded.report.trip_spec, after)
            report = recompute_confirmed_report(
                loaded.report,
                itinerary=loaded.report.itinerary,
                spec=new_spec,
                kb=get_kb(),
                now=now,
            )
            execution = PostPlanExecutionResult(report=report, brief=after)
        elif approve and action.kind == "scoped_itinerary_replan":
            from api.main import get_kb

            after = _after_brief(loaded.workspace.brief, action, store, user)
            execution = replan_scoped_itinerary(
                loaded.report, action, brief=after, kb=get_kb(), now=now
            )
        elif approve and action.kind == "provider_invalidating_change":
            from api.confirmed_planning import build_travel_service
            from api.main import get_kb
            from gateway.travel.product import TravelInventorySnapshot

            after = _after_brief(loaded.workspace.brief, action, store, user)
            retained = (
                TravelInventorySnapshot.model_validate_json(loaded.workspace.inventory.snapshot_json)
                if loaded.workspace.inventory is not None
                and loaded.workspace.inventory.snapshot_json is not None
                else None
            )
            impact = ActionImpact.model_validate(data["impact"])
            service = build_travel_service(
                get_kb(),
                plan_id=f"{session_id}:cp4",
                now=lambda: now,
                country=loaded.workspace.brief.home.home_country,
            )
            execution = refresh_provider_inventory(
                loaded.report,
                action,
                brief=after,
                retained_snapshot=retained,
                kb=get_kb(),
                now=now,
                inventory_service=service,
                requested_domains=set(impact.refetch_domains),
            )
        elif approve and action.kind == "profile_update_proposal":
            profile_update, profile_base_fingerprint = _profile_candidate(
                store, user, action, now=now
            )
            profile_base_fingerprint = data.get("profile_base_fingerprint")
            if not isinstance(profile_base_fingerprint, str):
                raise _error(
                    "INVALID_ACTION", "The profile proposal is missing its base fingerprint."
                )
            profile_section = action.section
            typed = PlanningSessionRepository(store).get(
                user_id=user.id, session_id=session_id
            )
            if typed is None:
                raise UnknownPlanningSessionError(session_id)
            typed_updated = typed.model_copy(
                update={
                    "profile_defaults": profile_update,
                    "updated_at": now,
                    "version": typed.version + 1,
                }
            )
            current = PlanningSessionRepository.snapshot_of(typed_updated)
        elif approve and action.kind == "deterministic_edit":
            from agents.post_plan_execution import recompute_confirmed_edit
            from api.main import get_kb

            report = recompute_confirmed_edit(loaded.report, action.edit, kb=get_kb(), now=now)
            execution = PostPlanExecutionResult(report=report, brief=loaded.workspace.brief)
        if execution is not None:
            report_json = execution.report.model_dump_json()
            workspace = workspace.model_copy(update={"current_result_id": uuid4().hex})
            workspace_domain = workspace_domain.model_copy(
                update={"brief": execution.brief, "updated_at": now}
            )
            if approve and isinstance(action, ScopedItineraryReplan) and action.scope == "dates":
                workspace_domain = workspace_domain.model_copy(
                    update={
                        "day_overrides": [
                            *workspace_domain.day_overrides,
                            *[
                                DayOverride(
                                    date=d,
                                    question_ids=(
                                        sorted(
                                            action.patch.question_ids,
                                            key=lambda question_id: question_id.value,
                                        )
                                        if action.patch
                                        else []
                                    ),
                                    day_theme=action.day_theme,
                                )
                                for d in action.affected_dates
                            ],
                        ],
                    }
                )
            if execution.inventory_snapshot is not None:
                retained_inventory = workspace_domain.inventory or RetainedInventory()
                workspace_domain = workspace_domain.model_copy(
                    update={
                        "inventory": retained_inventory.model_copy(
                            update={"snapshot_json": execution.inventory_snapshot.model_dump_json()}
                        )
                    }
                )
            workspace = workspace.model_copy(
                update={"payload_json": workspace_domain.model_dump_json()}
            )
        elif approve and isinstance(action, ScopedItineraryReplan) and action.scope == "dates":
            workspace_domain = workspace_domain.model_copy(update={"updated_at": now})
            workspace = workspace.model_copy(
                update={"payload_json": workspace_domain.model_dump_json()}
            )
        commit_session = (
            current
            if profile_update is not None
            else _advance_session_snapshot(store, user.id, session_id, now=now)
        )
        outcome_payload: dict[str, Any] = {
            "proposal_id": proposal_id,
            "decision": "approved" if approve else "rejected",
        }
        if explanation is not None:
            outcome_payload["explanation"] = explanation
        finished = store.commit_post_plan_operation(
            user_id=user.id,
            session_id=session_id,
            event_id=body.client_event_id,
            fingerprint=operation.fingerprint,
            expected_workspace_version=operation.reserved_workspace_version
            or loaded.snapshot.version,
            workspace=workspace,
            session=commit_session,
            report_json=report_json,
            outcome_json=json.dumps(outcome_payload, sort_keys=True),
            updated_at=now,
            profile_update=profile_update,
            profile_section=profile_section,
            profile_base_fingerprint=profile_base_fingerprint,
        )
        outcome = {
            "operation_id": finished.operation_id,
            "proposal_id": proposal_id,
            "status": finished.status,
            "decision": "approved" if approve else "rejected",
            "result_id": finished.result_id,
        }
        if explanation is not None:
            outcome["explanation"] = explanation
        return outcome
    finally:
        mark_finished(operation.operation_id)


@router.post("/actions/{proposal_id}/approve", responses=_POST_PLAN_ERRORS)
def approve_action(
    session_id: str,
    proposal_id: str,
    body: DecisionIn,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> dict[str, Any]:
    try:
        return _decision(
            session_id, proposal_id, body, approve=True, request=request, user=user, store=store
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/actions/{proposal_id}/reject", responses=_POST_PLAN_ERRORS)
def reject_action(
    session_id: str,
    proposal_id: str,
    body: DecisionIn,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> dict[str, Any]:
    try:
        return _decision(
            session_id, proposal_id, body, approve=False, request=request, user=user, store=store
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post(
    "/workspace/revisions",
    response_model=WorkspaceRevisionOut,
    status_code=201,
    responses=_POST_PLAN_ERRORS,
)
def save_workspace_revision(
    session_id: str,
    body: WorkspaceRevisionIn,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> WorkspaceRevisionOut:
    """Explicitly append the selected durable result; working approvals never autosave."""
    require_csrf(request)
    try:
        loaded = _loaded(store, user, session_id)
        if loaded.snapshot.version != body.expected_workspace_version:
            raise _error("STALE_WORKSPACE", "Reload the workspace before saving.", 409)
        trip_id = loaded.snapshot.saved_trip_id
        if trip_id is None:
            raise _error("SESSION_NOT_ATTACHED", "Attach this session to a saved trip first.", 409)
        fingerprint = trip_event_fingerprint(
            "append_revision",
            trip_id=trip_id,
            fields={"session_id": session_id, "result_id": loaded.snapshot.current_result_id},
        )
        revision = store.add_revision(
            user_id=user.id,
            trip_id=trip_id,
            trace_id=loaded.report.trace_id,
            report_json=loaded.result.report_json,
            now=now_utc(),
            client_event_id=body.client_event_id,
            request_fingerprint=fingerprint,
        )
        return WorkspaceRevisionOut(
            trip_id=trip_id, revision=revision.revision, result_id=loaded.snapshot.current_result_id
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _map_error(exc) from exc
