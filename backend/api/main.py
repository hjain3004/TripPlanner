from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from accounts.models import User
from accounts.store import AccountStore, DuplicateEmailError
from api.auth import (
    SESSION_COOKIE,
    clear_session_cookies,
    current_user,
    get_store,
    new_csrf_token,
    now_utc,
    require_csrf,
    set_session_cookies,
)

from agents.llm import HostedFreeTier, LLMClient
from agents.models import (
    PIPELINE_STAGES,
    PipelineStatus,
    PlanJobStatus,
    TripIntakeRequest,
)
from agents.pipeline import run_pipeline
from api.job_manager import job_manager
from core.db import DB_PATH, KnowledgeBase, load_kb, seed_database

TRACE_DIR = Path(__file__).resolve().parents[1] / ".traces"

app = FastAPI(
    title="TripPlanner Kernel API",
    version="0.3.0",
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


@app.post("/plan", status_code=202)
def plan(
    request: TripIntakeRequest,
    kb: KnowledgeBase = Depends(get_kb),
    llm: LLMClient = Depends(get_llm),
    booking_date: date = Depends(get_booking_date),
    trace_dir: Path = Depends(get_trace_dir),
) -> dict[str, str]:
    job_id = job_manager.create_job()
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, request, kb, llm, booking_date, trace_dir),
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


def _run_job(
    job_id: str,
    request: TripIntakeRequest,
    kb: KnowledgeBase,
    llm: LLMClient,
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
            booking_date=booking_date,
            trace_dir=trace_dir,
            on_stage=on_stage,
        )
        if result.status == PipelineStatus.NEEDS_CLARIFICATION:
            job_manager.complete(
                job_id, "needs_clarification", unresolved=result.unresolved
            )
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


class CredentialsIn(BaseModel):
    email: str
    password: str = Field(min_length=12)


class UserOut(BaseModel):
    id: str
    email: str
    status: str


@app.post("/auth/register", status_code=201, response_model=UserOut)
def register(
    body: CredentialsIn, store: AccountStore = Depends(get_store)
) -> UserOut:
    now = now_utc()
    try:
        user = store.create_user(email=body.email, now=now)
    except DuplicateEmailError:
        # Deliberately uninformative: registration must not confirm which
        # emails already exist.
        raise HTTPException(status_code=409, detail="Registration failed")
    store.set_password(user.id, body.password, now=now)
    return UserOut(id=user.id, email=user.email, status=user.status)


@app.post("/auth/login", response_model=UserOut)
def login(
    body: CredentialsIn,
    response: Response,
    store: AccountStore = Depends(get_store),
) -> UserOut:
    now = now_utc()
    user = store.authenticate(body.email, body.password, now=now)
    if user is None:
        # One message for absent-user, wrong-password and locked-out alike.
        raise HTTPException(status_code=401, detail="Invalid credentials")
    session, raw_token = store.create_session(user.id, now=now)
    set_session_cookies(response, raw_token, new_csrf_token(), session.expires_at)
    return UserOut(id=user.id, email=user.email, status=user.status)


@app.post("/auth/logout", status_code=204)
def logout(
    request: Request, store: AccountStore = Depends(get_store)
) -> Response:
    require_csrf(request)
    now = now_utc()
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = store.session_for_token(token, now=now)
        if session is not None:
            store.revoke_session(session.id, now=now)
    response = Response(status_code=204)
    clear_session_cookies(response)
    return response


@app.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email, status=user.status)
