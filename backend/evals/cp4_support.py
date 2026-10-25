"""Shared builders for the CP4 post-plan tests (not itself a test module).

A small, fully synthetic confirmed trip — DEL to SIN, 2026-11-01 to 2026-11-05, four
itinerary days — with the routing and impact contexts a workspace would derive from it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from accounts.models import (
    PlanningSessionSnapshot,
    PostPlanOperation,
    PostPlanResult,
    PostPlanWorkspaceSnapshot,
)
from accounts.store import AccountStore
from core.models import UserWallet
from planning.answers import (
    BudgetObjectivePayload,
    DailyRhythmPayload,
    ExperiencesFoodPayload,
    FlightPreferencesPayload,
    HardConstraintsPayload,
    PurposePartyPayload,
    StayPreferencesPayload,
    TripEssentialsPayload,
)
from planning.contracts import TravelerHomeContext, TripBrief
from planning.post_plan import (
    DayOverride,
    ExplainableRef,
    ImpactContext,
    ImpactItem,
    RoutingContext,
    RoutingDay,
    RoutingItem,
    flight_fingerprint,
    hotel_fingerprint,
)

START = date(2026, 11, 1)  # a Sunday
HOTEL_AREA = "marina_bay"

GARDENS = RoutingItem(poi_id="poi:gardens", name="Gardens by the Bay")
MAXWELL = RoutingItem(poi_id="poi:maxwell", name="Maxwell Food Centre")
GALLERY = RoutingItem(poi_id="poi:gallery", name="National Gallery Singapore")
FLYER = RoutingItem(poi_id="poi:flyer", name="Singapore Flyer")
JEWEL = RoutingItem(poi_id="poi:jewel", name="Jewel Changi Airport")
SAFARI = RoutingItem(poi_id="poi:safari", name="Night Safari")

DAY_ITEMS: list[list[RoutingItem]] = [[GARDENS, MAXWELL], [GALLERY], [FLYER], []]


def make_brief(**overrides: Any) -> TripBrief:
    fields: dict[str, Any] = {
        "home": TravelerHomeContext(home_country="IN", home_currency="INR", default_origin="DEL"),
        "trip_essentials": TripEssentialsPayload(
            origin="DEL",
            destination="SIN",
            start_date=START,
            end_date=START + timedelta(days=4),
            travelers=2,
        ),
        "purpose_and_party": PurposePartyPayload(purpose="leisure", adults=2),
        "budget_and_objective": BudgetObjectivePayload(
            budget_minor=None,
            currency="INR",
            travel_style="balanced",
            objective="balanced",
            points_priority="best_value",
        ),
        "flight_preferences": FlightPreferencesPayload(
            cabin="economy", max_stops=0, schedule="no_preference"
        ),
        "stay_preferences": StayPreferencesPayload(
            room_count=1, location_price_tradeoff="balanced"
        ),
        "daily_rhythm": DailyRhythmPayload(
            pace="moderate",
            day_start="normal",
            evening_style="flexible",
            day_trip_appetite="none",
        ),
        "experiences_and_food": ExperiencesFoodPayload(
            interests=["food"], iconic_local_balance="balanced"
        ),
        "hard_constraints": HardConstraintsPayload(has_constraints=False),
        "wallet": UserWallet(card_ids=["hdfc-infinia"]),
    }
    fields.update(overrides)
    return TripBrief(**fields)


def routing_context(brief: TripBrief | None = None, **overrides: Any) -> RoutingContext:
    fields: dict[str, Any] = {
        "days": [
            RoutingDay(date=START + timedelta(days=index), items=list(items))
            for index, items in enumerate(DAY_ITEMS)
        ],
        "candidates": [JEWEL, SAFARI],
        "explainable": [
            ExplainableRef(kind="cost_line", ref_id="flight:SQ", label="Singapore Airlines flight"),
            ExplainableRef(kind="cost_line", ref_id="hotel:MBS", label="Marina Bay hotel"),
            ExplainableRef(
                kind="transfer_recommendation", ref_id="transfer:main", label="transfer plan"
            ),
        ],
        "brief": brief or make_brief(),
    }
    fields.update(overrides)
    return RoutingContext(**fields)


def impact_context(
    brief: TripBrief | None = None,
    *,
    day_overrides: list[DayOverride] | None = None,
    **overrides: Any,
) -> ImpactContext:
    brief = brief or make_brief()
    fields: dict[str, Any] = {
        "itinerary_dates": [START + timedelta(days=i) for i in range(4)],
        "items": [
            ImpactItem(poi_id=item.poi_id, day_index=index)
            for index, items in enumerate(DAY_ITEMS)
            for item in items
        ],
        "day_overrides": day_overrides or [],
        "retained_hotel_area_id": HOTEL_AREA,
        "flight_fingerprint": flight_fingerprint(brief),
        "hotel_fingerprint": hotel_fingerprint(brief, hotel_area_id=HOTEL_AREA),
    }
    fields.update(overrides)
    return ImpactContext(**fields)


# --------------------------------------------------------------------------- #
# Store-level helpers: a session with a workspace, and operations on it           #
# --------------------------------------------------------------------------- #

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
EXPIRES = NOW + timedelta(days=30)


def open_store(tmp_path: Path) -> AccountStore:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    store.create_user(email="alice@example.com", now=NOW, user_id="alice")
    store.create_user(email="bob@example.com", now=NOW, user_id="bob")
    return store


def planning_snapshot(
    session_id: str = "s1",
    user_id: str = "alice",
    *,
    version: int = 1,
    saved_trip_id: str | None = None,
    expires_at: datetime = EXPIRES,
) -> PlanningSessionSnapshot:
    return PlanningSessionSnapshot(
        id=session_id,
        user_id=user_id,
        status="complete",
        version=version,
        updated_at=NOW,
        expires_at=expires_at,
        saved_trip_id=saved_trip_id,
        payload_json="{}",
    )


def seed_workspace(
    store: AccountStore,
    *,
    user_id: str = "alice",
    session_id: str = "s1",
    result_id: str = "r1",
    report_json: str = '{"n":1}',
    saved_trip_id: str | None = None,
    expires_at: datetime = EXPIRES,
) -> PostPlanWorkspaceSnapshot:
    """A planning session with a version-1 workspace holding one accepted result."""
    store.create_planning_session_snapshot(
        planning_snapshot(session_id, user_id, saved_trip_id=saved_trip_id, expires_at=expires_at)
    )
    workspace = PostPlanWorkspaceSnapshot(
        session_id=session_id,
        user_id=user_id,
        version=1,
        current_result_id=result_id,
        created_at=NOW,
        updated_at=NOW,
        expires_at=expires_at,
        saved_trip_id=saved_trip_id,
        payload_json='{"state":"initial"}',
    )
    result = PostPlanResult(
        result_id=result_id,
        user_id=user_id,
        session_id=session_id,
        created_at=NOW,
        report_sha256="0" * 64,
        report_json=report_json,
    )
    operation = PostPlanOperation(
        operation_id=f"init-{session_id}",
        user_id=user_id,
        session_id=session_id,
        kind="initialize",
        event_id=f"init:{session_id}",
        event_source="system",
        fingerprint="init",
        status="complete",
        expected_workspace_version=0,
        expected_session_version=1,
        result_id=result_id,
        created_at=NOW,
        updated_at=NOW,
    )
    created, _ = store.create_post_plan_workspace(
        workspace=workspace, result=result, operation=operation
    )
    return created


def make_operation(
    kind: Literal["propose", "approve", "reject", "save"],
    event_id: str,
    *,
    user_id: str = "alice",
    session_id: str = "s1",
    fingerprint: str | None = None,
    workspace_version: int = 1,
    session_version: int = 1,
    proposal_id: str | None = None,
    action_kind: str | None = None,
    interpreter_calls: int = 0,
    planner_calls: int = 0,
    event_source: Literal["client", "system"] = "client",
    operation_id: str | None = None,
) -> PostPlanOperation:
    return PostPlanOperation(
        operation_id=operation_id or f"op-{event_id}",
        user_id=user_id,
        session_id=session_id,
        kind=kind,
        event_id=event_id,
        event_source=event_source,
        fingerprint=fingerprint or f"fp-{event_id}",
        status="reserved",
        expected_workspace_version=workspace_version,
        expected_session_version=session_version,
        proposal_id=proposal_id,
        action_kind=action_kind,
        interpreter_calls=interpreter_calls,
        planner_calls=planner_calls,
        created_at=NOW,
        updated_at=NOW,
    )


def run_operation(
    store: AccountStore,
    operation: PostPlanOperation,
    *,
    report_json: str | None = None,
    new_result_id: str | None = None,
    outcome_json: str = "{}",
) -> PostPlanOperation:
    """Reserve then commit an operation against the workspace's current versions."""
    user_id, session_id = operation.user_id, operation.session_id
    workspace = store.get_post_plan_workspace(user_id=user_id, session_id=session_id)
    session = store.get_planning_session_snapshot(user_id=user_id, session_id=session_id)
    assert workspace is not None and session is not None
    reserved = store.reserve_post_plan_operation(
        user_id=user_id,
        session_id=session_id,
        operation=operation,
        expected_workspace_version=workspace.version,
        expected_session_version=session.version,
    )
    assert reserved.reserved_workspace_version is not None
    result_id = new_result_id if report_json is not None else workspace.current_result_id
    assert result_id is not None
    return store.commit_post_plan_operation(
        user_id=user_id,
        session_id=session_id,
        event_id=operation.event_id,
        event_source=operation.event_source,
        fingerprint=operation.fingerprint,
        expected_workspace_version=reserved.reserved_workspace_version,
        workspace=workspace.model_copy(
            update={"current_result_id": result_id, "updated_at": NOW + timedelta(seconds=1)}
        ),
        session=session.model_copy(
            update={"version": session.version + 1, "updated_at": NOW + timedelta(seconds=1)}
        ),
        report_json=report_json,
        outcome_json=outcome_json,
    )
