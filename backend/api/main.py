from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agents.llm import HostedFreeTier, LLMClient
from agents.models import (
    FinalReport,
    PipelineStatus,
    PlaceSearchRequest,
    PlaceSearchResponse,
    PlanJobStatus,
    RecomputeRequest,
    RefreshProseRequest,
    TripIntakeRequest,
)
from agents.pipeline import run_pipeline
from agents.recompute import recompute_itinerary, refresh_prose
from agents.search import search_catalog_places
from api.job_manager import job_manager
from core.db import DB_PATH, KnowledgeBase, load_kb, seed_database
from gateway.catalog.regions import get_region
from gateway.places.protocol import PlaceProviderAdapter
from gateway.places.registry import ProviderRegistry, get_default_place_registry

TRACE_DIR = Path(__file__).resolve().parents[1] / ".traces"

app = FastAPI(
    title="TripPlanner Kernel API",
    version="0.3.0",
    description="Kernel MVP API over local curated sample data.",
)

# Without this, a browser's preflight OPTIONS /plan gets 405 and the POST never
# fires - exactly what happened the first time the real frontend talked to the
# real backend. Every prior test missed it: MSW intercepts inside the browser and
# the Playwright suites ran against mocks, so no real preflight was ever sent.
#
# Explicit origins, not "*": the wildcard cannot be combined with credentials,
# and this API will carry a session once spec 17 accounts land. Override with
# TRIPWISE_CORS_ORIGINS (comma-separated) for other hosts.
_DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv("TRIPWISE_CORS_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


def get_kb() -> KnowledgeBase:
    if not DB_PATH.exists():
        seed_database()
    return load_kb(DB_PATH)


def get_llm() -> LLMClient:
    return HostedFreeTier()


def get_booking_date() -> date:
    return date.today()


def get_trace_dir() -> Path:
    return TRACE_DIR


def get_place_registry() -> ProviderRegistry:
    return get_default_place_registry()


PlaceProviderResolver = Callable[[PlaceSearchRequest], PlaceProviderAdapter | None]


def build_place_provider_resolver(
    registry: ProviderRegistry,
    adapters: Mapping[str, PlaceProviderAdapter],
    *,
    active_profile: str = "student_noncommercial",
) -> PlaceProviderResolver:
    """Resolve an optional place provider through registry eligibility.

    The production adapter map is empty until live provider activation is approved.
    Tests may supply fixture adapters explicitly, but still pass through registry
    profile/domain/country/quota eligibility.
    """

    def _resolve(request: PlaceSearchRequest) -> PlaceProviderAdapter | None:
        dest_iata = request.destination.strip().upper()
        region = get_region(dest_iata)
        if region is None:
            return None

        for entry in registry.select_providers(
            active_profile=active_profile,
            domain="poi",
            country=region.country_code,
        ):
            adapter = adapters.get(entry.provider_id)
            if adapter is not None:
                return adapter
        return None

    return _resolve


def get_place_provider_resolver(
    registry: Annotated[ProviderRegistry, Depends(get_place_registry)],
) -> PlaceProviderResolver:
    return build_place_provider_resolver(
        registry=registry,
        adapters={},
        active_profile="student_noncommercial",
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/plan", status_code=202)
def plan(
    request: TripIntakeRequest,
    kb: Annotated[KnowledgeBase, Depends(get_kb)],
    llm: Annotated[LLMClient, Depends(get_llm)],
    registry: Annotated[ProviderRegistry, Depends(get_place_registry)],
    booking_date: Annotated[date, Depends(get_booking_date)],
    trace_dir: Annotated[Path, Depends(get_trace_dir)],
) -> dict[str, str]:
    job_id = job_manager.create_job()
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, request, kb, llm, registry, booking_date, trace_dir),
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id}


@app.get("/plan/{job_id}", response_model=PlanJobStatus)
def get_job_status(job_id: str) -> PlanJobStatus:
    state = job_manager.get_job(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return state.to_status(job_id)


@app.post("/plan/recompute", response_model=FinalReport)
def recompute_plan(
    request: RecomputeRequest,
    kb: Annotated[KnowledgeBase, Depends(get_kb)],
    booking_date: Annotated[date, Depends(get_booking_date)],
) -> FinalReport:
    try:
        return recompute_itinerary(
            request.trip_spec,
            request.itinerary,
            request.edit,
            kb,
            booking_date=booking_date,
            previous_freshness=request.previous_freshness,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/plan/refresh-prose", response_model=FinalReport)
def refresh_prose_plan(
    request: RefreshProseRequest,
    kb: Annotated[KnowledgeBase, Depends(get_kb)],
    llm: Annotated[LLMClient, Depends(get_llm)],
    booking_date: Annotated[date, Depends(get_booking_date)],
) -> FinalReport:
    try:
        return refresh_prose(
            request.trip_spec,
            request.itinerary,
            request.kernel_result,
            kb,
            llm,
            booking_date=booking_date,
            previous_freshness=request.previous_freshness,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/places/search", response_model=PlaceSearchResponse)
def search_places(
    request: PlaceSearchRequest,
    kb: Annotated[KnowledgeBase, Depends(get_kb)],
    provider_resolver: Annotated[PlaceProviderResolver, Depends(get_place_provider_resolver)],
) -> PlaceSearchResponse:
    try:
        provider_adapter = provider_resolver(request)
        return search_catalog_places(request, kb, provider_adapter=provider_adapter)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc



def _run_job(
    job_id: str,
    request: TripIntakeRequest,
    kb: KnowledgeBase,
    llm: LLMClient,
    registry: ProviderRegistry,
    booking_date: date,
    trace_dir: Path,
) -> None:
    try:

        def on_stage(stage_index: int, stage: str) -> None:
            job_manager.set_stage(job_id, stage_index, stage)

        result = run_pipeline(
            request.raw_request,
            kb,
            llm,
            registry,
            booking_date=booking_date,
            trace_dir=trace_dir,
            on_stage=on_stage,
        )
        if result.status == PipelineStatus.NEEDS_CLARIFICATION:
            job_manager.complete(job_id, "needs_clarification", unresolved=result.unresolved)
        elif result.status == PipelineStatus.ERROR:
            job_manager.complete(
                job_id,
                "failed",
                error={
                    "code": "PIPELINE_ERROR",
                    "message": result.error or "Unknown pipeline error",
                    "trace_id": result.trace_id,
                },
            )
        else:
            job_manager.complete(job_id, "complete", report=result.report)
    except Exception as exc:
        job_manager.complete(
            job_id,
            "failed",
            error={
                "code": "INTERNAL_ERROR",
                "message": str(exc),
                "trace_id": "",
            },
        )


if __name__ == "__main__":
    import argparse
    import json
    import sys

    from fastapi.openapi.utils import get_openapi

    parser = argparse.ArgumentParser()
    parser.add_argument("--export-schema", type=str)
    args = parser.parse_args()

    if args.export_schema:
        schema = get_openapi(
            title=app.title,
            version=app.version,
            openapi_version=app.openapi_version,
            description=app.description,
            routes=app.routes,
        )
        with open(args.export_schema, "w") as f:
            json.dump(schema, f, indent=2)
        print(f"Exported schema to {args.export_schema}")
        sys.exit(0)
