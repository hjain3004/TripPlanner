from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException

from agents.llm import HostedFreeTier, LLMClient
from agents.models import PlanRequest, PlanResponse
from agents.pipeline import run_pipeline
from core.db import DB_PATH, KnowledgeBase, load_kb, seed_database

TRACE_DIR = Path(__file__).resolve().parents[1] / ".traces"

app = FastAPI(
    title="TripPlanner Kernel API",
    version="0.2.0",
    description="Kernel MVP API over local curated sample data.",
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/plan", response_model=PlanResponse)
def plan(
    request: PlanRequest,
    kb: KnowledgeBase = Depends(get_kb),
    llm: LLMClient = Depends(get_llm),
    booking_date: date = Depends(get_booking_date),
    trace_dir: Path = Depends(get_trace_dir),
) -> PlanResponse:
    try:
        return run_pipeline(
            request.raw_request,
            kb,
            llm,
            booking_date=booking_date,
            trace_dir=trace_dir,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
