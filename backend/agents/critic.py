from __future__ import annotations

from agents.llm import LLMClient, complete_with_repair
from agents.models import CriticResult, CriticVerdict, DraftItinerary, EstimatorResult, TripSpec
from agents.retrieval import CITY_BY_IATA
from core.db import KnowledgeBase


def _critic_system() -> str:
    return (
        "You are the TripPlanner critic. Return only CriticVerdict JSON. "
        "Check hours/closed-day conflicts, same-day geography scatter, pace overload, "
        "budget overshoot over 15%, dietary conflicts, and unsupported claims. "
        "Do not add facts that are absent from the provided artifacts."
    )


def _critic_user(
    spec: TripSpec, itinerary: DraftItinerary, estimate: EstimatorResult, kb: KnowledgeBase
) -> str:
    city = CITY_BY_IATA.get(spec.destination_city, spec.destination_city)
    pois = [
        {
            "id": poi.id,
            "area": poi.area,
            "tags": poi.tags,
            "duration_min": poi.typical_duration_min,
            "open_hours": poi.open_hours,
            "description": poi.description,
        }
        for poi in kb.pois(city)
    ]
    return (
        "TripSpec:\n"
        f"{spec.model_dump_json()}\n"
        "DraftItinerary:\n"
        f"{itinerary.model_dump_json()}\n"
        "CostedTrip:\n"
        f"{estimate.costed_trip.model_dump_json()}\n"
        "POI reference rows:\n"
        f"{pois}"
    )


def run_critic(
    spec: TripSpec,
    itinerary: DraftItinerary,
    estimate: EstimatorResult,
    kb: KnowledgeBase,
    llm: LLMClient,
) -> CriticResult:
    try:
        verdict = complete_with_repair(
            llm,
            node="critic",
            system=_critic_system(),
            user=_critic_user(spec, itinerary, estimate, kb),
            schema=CriticVerdict,
            temperature=0.0,
            max_tokens=1024,
            timeout_s=20,
        )
    except Exception:
        return CriticResult(
            verdict=CriticVerdict(passed=True, issues=[]),
            caveats=["Critic unavailable; itinerary was not LLM-reviewed."],
        )
    return CriticResult(verdict=verdict)
