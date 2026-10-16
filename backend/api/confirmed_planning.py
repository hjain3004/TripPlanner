"""Authenticated confirmed-brief handoff into the bounded gateway."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from agents.confirmed_trip import compile_confirmed_input
from agents.models import TripIntakeRequest
from api.job_manager import job_manager
from gateway.travel.adapters.sample import SampleAdapter
from gateway.travel.registry import get_default_travel_registry
from gateway.travel.service import TravelInventoryService
from planning.contracts import PlanningSession


def build_travel_service(
    kb: object,
    *,
    plan_id: str,
    now: Callable[[], datetime],
    country: str = "IN",
) -> TravelInventoryService:
    """Runtime factory: G3.4 is sample-only even if old live flags are set."""
    from core.db import KnowledgeBase

    if not isinstance(kb, KnowledgeBase):
        raise TypeError("confirmed planning requires a KnowledgeBase")
    current = now()
    adapter = SampleAdapter(kb, now=lambda: current)
    registry = get_default_travel_registry().model_copy(deep=True)
    registry.entries = [
        entry.model_copy(update={"enabled": entry.provider_id == "sample_travel_adapter"})
        for entry in registry.entries
    ]
    return TravelInventoryService(
        registry=registry,
        adapters={"sample_travel_adapter": adapter},
        plan_id=plan_id,
        country=country,
        now=now,
    )


def start_confirmed_job(session: PlanningSession, job_id: str) -> None:
    """Start one owner-bound process-local job from the persisted snapshot."""
    if not session.confirmed_briefs:
        raise ValueError("confirmed brief is required")
    from api.main import (
        _run_job,
        get_booking_date,
        get_kb,
        get_llm,
        get_place_registry,
        get_trace_dir,
    )

    snapshot = session.confirmed_briefs[-1]
    confirmed = compile_confirmed_input(snapshot)
    plan_id = f"{session.id}:revision:{snapshot.revision}"
    service = build_travel_service(
        get_kb(),
        plan_id=plan_id,
        country=session.home.home_country,
        now=lambda: datetime.now(UTC),
    )
    request = TripIntakeRequest(raw_request=confirmed.raw_request, wallet=session.wallet)
    job_manager.create_job(job_id, owner_id=session.user_id, session_id=session.id)
    import threading

    thread = threading.Thread(
        target=_run_job,
        args=(
            job_id,
            request,
            get_kb(),
            get_llm(),
            get_place_registry(),
            get_booking_date(),
            get_trace_dir(),
        ),
        kwargs={"confirmed_input": confirmed, "inventory_service": service},
        daemon=True,
    )
    thread.start()


def resolve_inventory_context(*, user_id: str, session_id: str, job_id: str) -> object:
    """Resolve ownership before a future scoped edit/refresh operation."""
    state = job_manager.get_job(job_id)
    if state is None or state.owner_id != user_id or state.session_id != session_id:
        raise LookupError("inventory context not found")
    return state
