"""Authenticated post-plan proposals and approvals (CP4 Tasks 5 and 7).

The router is intentionally thin: deterministic routing and typed validation happen
before the optional interpreter, while all state changes go through the durable account
store reservation/commit boundary.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from accounts.models import PostPlanOperation, User
from accounts.projection import build_user_wallet
from accounts.store import (
    AccountStore,
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
from agents.post_plan_execution import (
    recompute_confirmed_report,
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
from planning.brief import profile_group_from_answer
from planning.contracts import PlanningSession
from planning.post_plan import (
    DayOverride,
    ExplainableRef,
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
_ACTION = TypeAdapter(PostPlanAction)


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
    text: str | None = Field(default=None, max_length=2000)
    action: dict[str, Any] | None = None

    def model_post_init(self, __context: Any) -> None:
        if (self.text is None) == (self.action is None):
            raise ValueError("provide exactly one of text or action")


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


@router.post("/workspace", response_model=PostPlanWorkspaceOut)
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


@router.get("/workspace", response_model=PostPlanWorkspaceOut)
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


@router.post("/actions", response_model=ActionProposalOut)
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
        after = _after_brief(loaded.workspace.brief, action, store, user)
        impact = compute_impact(
            loaded.workspace.brief,
            after,
            action=action,
            context=impact_context_from_routing(context),
        )
        proposal_payload: dict[str, Any] = {
            "action": action.model_dump(mode="json"),
            "impact": impact.model_dump(mode="json"),
        }
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
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _map_error(exc) from exc


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
            "workspace": body.expected_workspace_version,
            "session": body.expected_session_version,
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
        if approve and action.kind == "wallet_or_objective_change":
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
            from agents.post_plan_execution import PostPlanExecutionResult
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
            from agents.post_plan_execution import PostPlanExecutionResult

            execution = PostPlanExecutionResult(report=report, brief=loaded.workspace.brief)
        if execution is not None:
            report_json = execution.report.model_dump_json()
            workspace = workspace.model_copy(update={"current_result_id": uuid4().hex})
            workspace_domain = workspace_domain.model_copy(
                update={"brief": execution.brief, "updated_at": now}
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
            workspace_domain = workspace_domain.model_copy(
                update={
                    "day_overrides": [
                        *workspace_domain.day_overrides,
                        *[
                            DayOverride(
                                date=d,
                                question_ids=action.patch.question_ids if action.patch else [],
                            )
                            for d in action.affected_dates
                        ],
                    ],
                    "updated_at": now,
                }
            )
            workspace = workspace.model_copy(
                update={"payload_json": workspace_domain.model_dump_json()}
            )
        commit_session = (
            current
            if profile_update is not None
            else _advance_session_snapshot(store, user.id, session_id, now=now)
        )
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
            outcome_json=json.dumps(
                {"proposal_id": proposal_id, "decision": "approved" if approve else "rejected"},
                sort_keys=True,
            ),
            updated_at=now,
            profile_update=profile_update,
            profile_section=profile_section,
            profile_base_fingerprint=profile_base_fingerprint,
        )
        return {
            "operation_id": finished.operation_id,
            "proposal_id": proposal_id,
            "status": finished.status,
            "decision": "approved" if approve else "rejected",
            "result_id": finished.result_id,
        }
    finally:
        mark_finished(operation.operation_id)


@router.post("/actions/{proposal_id}/approve")
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


@router.post("/actions/{proposal_id}/reject")
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


@router.post("/workspace/revisions", response_model=WorkspaceRevisionOut, status_code=201)
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
