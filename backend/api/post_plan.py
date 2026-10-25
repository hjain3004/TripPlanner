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
    UnknownPlanningSessionError,
)
from agents.post_plan_interpreter import (
    PostPlanInterpretationError,
    PostPlanInterpreter,
    get_post_plan_llm,
)
from api.auth import current_user, get_store, now_utc, require_csrf
from api.post_plan_service import (
    LoadedWorkspace,
    WorkspaceError,
    initialize_from_job,
    initialize_from_saved_revision,
    load_workspace,
    recover_interrupted,
)
from planning.contracts import PlanningSession
from planning.post_plan import (
    ExplainableRef,
    PostPlanAction,
    RoutingContext,
    RoutingDay,
    RoutingItem,
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


def _routing_context(report: Any) -> RoutingContext:
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
        ExplainableRef(kind="cost_line", ref_id=line.id, label=line.description)
        for line in report.costed_trip.lines
    )
    return RoutingContext(days=days, candidates=[], explainable=explainable, brief=report.trip_spec)


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
    if action.kind in {"scoped_itinerary_replan", "provider_invalidating_change"}:
        assert action.patch is not None
        return apply_brief_patch(before, action.patch)
    if action.kind == "wallet_or_objective_change":
        wallet = build_user_wallet(store.wallet_entries(user.id))
        return apply_wallet_or_objective(before, action, current_wallet=wallet)
    return before


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
        context = _routing_context(loaded.report)
        action: PostPlanAction
        if body.action is not None or (
            body.text is not None and classify_command(body.text, context) is not None
        ):
            action = _proposal_action(body, context)
        else:
            if body.text is None:
                raise _error("INVALID_ACTION", "An action or text is required.")
            operation = _reserve(
                store,
                user,
                session_id,
                body,
                kind="propose",
                action_kind=None,
                interpreter_calls=1,
                payload={"text": body.text},
            )
            try:
                action = PostPlanInterpreter(get_post_plan_llm()).interpret(context, body.text)
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
        after = _after_brief(loaded.workspace.brief, action, store, user)
        impact = compute_impact(
            loaded.workspace.brief,
            after,
            action=action,
            context=impact_context_from_routing(context),
        )
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
                    "action": action.model_dump(mode="json"),
                    "impact": impact.model_dump(mode="json"),
                },
            )
            if body.action is not None or classify_command(body.text or "", context) is not None
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
            session=current.model_copy(
                update={"version": current.version + 1, "updated_at": now_utc()}
            ),
            report_json=None,
            outcome_json=json.dumps(
                {
                    "action": action.model_dump(mode="json"),
                    "impact": impact.model_dump(mode="json"),
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
    current = store.get_planning_session_snapshot(user_id=user.id, session_id=session_id)
    assert current is not None
    now = now_utc()
    workspace = loaded.snapshot.model_copy(update={"updated_at": now})
    report_json = None
    if approve and action.kind == "deterministic_edit":
        from agents.post_plan_execution import recompute_confirmed_edit
        from api.main import get_kb

        report = recompute_confirmed_edit(loaded.report, action.edit, kb=get_kb(), now=now)
        report_json = report.model_dump_json()
        workspace = workspace.model_copy(update={"current_result_id": uuid4().hex})
    finished = store.commit_post_plan_operation(
        user_id=user.id,
        session_id=session_id,
        event_id=body.client_event_id,
        fingerprint=operation.fingerprint,
        expected_workspace_version=operation.reserved_workspace_version or loaded.snapshot.version,
        workspace=workspace,
        session=current.model_copy(update={"version": current.version + 1, "updated_at": now}),
        report_json=report_json,
        outcome_json=json.dumps(
            {"proposal_id": proposal_id, "decision": "approved" if approve else "rejected"},
            sort_keys=True,
        ),
        updated_at=now,
    )
    return {
        "operation_id": finished.operation_id,
        "proposal_id": proposal_id,
        "status": finished.status,
        "decision": "approved" if approve else "rejected",
        "result_id": finished.result_id,
    }


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
