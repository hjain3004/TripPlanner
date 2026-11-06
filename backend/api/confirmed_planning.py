"""Authenticated confirmed-brief handoff into the bounded gateway."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from agents.confirmed_trip import compile_confirmed_input
from agents.models import TripIntakeRequest
from api.job_manager import job_manager
from gateway.travel.adapters.sample import SampleAdapter
from gateway.travel.protocol import TravelProviderAdapter
from gateway.travel.registry import get_default_travel_registry
from gateway.travel.service import TravelInventoryService
from planning.contracts import PlanningSession


def build_travel_service(
    kb: object,
    *,
    plan_id: str,
    now: Callable[[], datetime],
    country: str = "IN",
    gondola_hotel_adapter: TravelProviderAdapter | None = None,
    gondola_adapter: TravelProviderAdapter | None = None,
) -> TravelInventoryService:
    """Default sample inventory, plus explicitly enabled Gondola evidence.

    An injected adapter is for controlled replay. It never sets an environment
    flag or creates credentials. Production startup's activation guard remains.
    """
    from core.db import KnowledgeBase
    from gateway.travel.adapters.gondola.dated_hotel_adapter import build_keychain_gondola_adapter
    from gateway.travel.registry import gondola_kill_switch_active, gondola_search_mode

    if not isinstance(kb, KnowledgeBase):
        raise TypeError("confirmed planning requires a KnowledgeBase")
    if gondola_adapter is not None and gondola_hotel_adapter is not None:
        raise ValueError("Supply one Gondola replay adapter")
    injected = gondola_adapter or gondola_hotel_adapter
    current = now()
    adapter = SampleAdapter(kb, now=lambda: current)
    registry = get_default_travel_registry().model_copy(deep=True)
    adapters: dict[str, TravelProviderAdapter] = {"sample_travel_adapter": adapter}
    gondola_entry = registry.get_entry("gondola")
    if not gondola_kill_switch_active() and (gondola_entry.enabled or injected is not None):
        if injected is not None:
            if injected.capabilities.provider_id != "gondola":
                raise ValueError("Gondola replay adapter must identify its provider")
            adapters["gondola"] = injected
        else:
            adapters["gondola"] = build_keychain_gondola_adapter(
                plan_id=plan_id, now=now, mode=gondola_search_mode()
            )
    registry.entries = [
        entry.model_copy(update={"enabled": entry.provider_id in adapters})
        for entry in registry.entries
    ]
    return TravelInventoryService(
        registry=registry,
        adapters=adapters,
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
