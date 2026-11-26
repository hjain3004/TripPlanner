"""Server-owned facts override the intake model (runtime LLM design, section 3 and 4).

Offline: scripted model, real knowledge base, real pipeline and (where noted) the real API.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agents.llm import (
    LLMBudgetExceeded,
    LLMCallError,
    LLMInvalidResponse,
    LLMProviderUnavailable,
    ScriptedLLMClient,
)
from agents.models import (
    CriticVerdict,
    DraftItinerary,
    ExplainerOutput,
    ItineraryDay,
    PipelineStatus,
    TripSpec,
)
from agents.pipeline import run_pipeline
from agents.structured_input import (
    StructuredInputRejected,
    StructuredTripInput,
    apply_authoritative_fields,
    project_structured_trip_spec,
    render_structured_raw_request,
)
from api.main import app, get_booking_date, get_kb, get_llm, get_trace_dir
from core.db import SEEDS_DIR, KnowledgeBase, load_kb, seed_database
from core.models import UserWallet
from evals.a4_support import (
    PlanningKit,
    confirm,
    run_interview,
    signed_in_client,
    wait_for_job,
)


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _kb(tmp_path: Path) -> KnowledgeBase:
    db_path = tmp_path / "tripwise.sqlite"
    seed_database(SEEDS_DIR, db_path)
    return load_kb(db_path)


def _structured(**updates: Any) -> StructuredTripInput:
    base: dict[str, Any] = {
        "home_country": "IN",
        "origin_city": "del",
        "destination_city": "SIN",
        "start_date": date(2026, 8, 1),
        "end_date": date(2026, 8, 5),
        "travelers": 2,
        "budget_minor": 25_000_000,
        "budget_currency": "inr",
        "style": "balanced",
        "interests": [" museums ", "food", "food", ""],
        "pace": "relaxed",
        "dietary": ["vegetarian"],
        "wallet": UserWallet(card_ids=["hdfc-infinia"], points_balances={"voyager-prime": 5000}),
        "objective": "max_savings",
    }
    base.update(updates)
    return StructuredTripInput(**base)


def _model_spec(**updates: Any) -> TripSpec:
    base: dict[str, Any] = {
        "home_country": "IN",
        "origin_city": "DEL",
        "destination_city": "SIN",
        "start_date": date(2026, 8, 1),
        "end_date": date(2026, 8, 5),
        "travelers": 2,
        "budget_minor": 25_000_000,
        "budget_currency": "INR",
        "style": "balanced",
        "interests": ["nightlife"],
        "pace": "packed",
        "dietary": [],
        "wallet": UserWallet(card_ids=["hdfc-infinia"], points_balances={"voyager-prime": 5000}),
    }
    base.update(updates)
    return TripSpec(**base)


def _itinerary() -> DraftItinerary:
    return DraftItinerary(
        hotel_area_id="marina_bay",
        days=[ItineraryDay(date=date(2026, 8, 1 + i), items=[]) for i in range(4)],
    )


class Recording(ScriptedLLMClient):
    """A scripted client that remembers the user prompt of every call, per node."""

    def __init__(self, scripts: dict[str, list[object]]) -> None:
        super().__init__(scripts)
        self.prompts: dict[str, list[str]] = {}

    def complete_json(self, *, node: str, user: str, **kwargs: Any) -> Any:
        self.prompts.setdefault(node, []).append(user)
        return super().complete_json(node=node, user=user, **kwargs)


def _trip_line(planner_prompt: str) -> str:
    """The planner's 'Trip: {...}' line, without the POI rows that follow it."""
    return next(line for line in planner_prompt.splitlines() if line.startswith("Trip:"))


def _scripts(spec: TripSpec, **overrides: list[object]) -> dict[str, list[object]]:
    scripts: dict[str, list[object]] = {
        "intake": [spec],
        "planner": [_itinerary()],
        "critic": [CriticVerdict(passed=True)],
        "explainer": [ExplainerOutput(summary="s", itinerary_overview="i", payment_overview="p")],
    }
    scripts.update(overrides)
    return scripts


# --- structured input ----------------------------------------------------------------------- #


def test_structured_input_projects_to_a_normalized_trip_spec(tmp_path: Path) -> None:
    spec = project_structured_trip_spec(_structured(), _kb(tmp_path))
    assert (spec.origin_city, spec.destination_city, spec.budget_currency) == ("DEL", "SIN", "INR")
    assert spec.interests == ["museums", "food"]  # trimmed, deduplicated, empties dropped
    assert (spec.pace, spec.dietary, spec.unresolved) == ("relaxed", ["vegetarian"], [])
    assert spec.wallet.card_ids == ["hdfc-infinia"]


def test_structured_input_reports_every_reason_at_once(tmp_path: Path) -> None:
    bad = _structured(
        origin_city="XXX",
        end_date=date(2026, 8, 1),
        wallet=UserWallet(card_ids=["not-a-card"]),
    )
    with pytest.raises(StructuredInputRejected) as error:
        project_structured_trip_spec(bad, _kb(tmp_path))
    text = "; ".join(error.value.unresolved)
    assert "end date must be after the start date" in text
    assert "trip must be 3 to 7 nights" in text
    assert "unknown card id: not-a-card" in text
    assert "unsupported route: XXX->SIN" in text


def test_structured_input_rejects_unknown_fields_and_non_positive_travelers() -> None:
    with pytest.raises(ValidationError):
        StructuredTripInput.model_validate({**_structured().model_dump(), "extra": 1})
    with pytest.raises(ValidationError):
        _structured(travelers=0)


def test_rendered_request_is_deterministic_sorted_json() -> None:
    one = render_structured_raw_request(_structured())
    two = render_structured_raw_request(
        StructuredTripInput.model_validate(_structured().model_dump())
    )
    assert one == two
    body = json.loads(one.split("\n", 1)[1])
    assert list(body) == sorted(body)


def test_authority_replaces_preferences_and_flags_identity_drift(tmp_path: Path) -> None:
    authority = project_structured_trip_spec(_structured(), _kb(tmp_path))
    updated, mismatched = apply_authoritative_fields(_model_spec(), authority)
    assert mismatched == []
    assert (updated.interests, updated.pace, updated.dietary) == (
        ["museums", "food"],
        "relaxed",
        ["vegetarian"],
    )
    drifted, mismatched = apply_authoritative_fields(
        _model_spec(travelers=3, wallet=UserWallet(card_ids=[])), authority
    )
    assert mismatched == ["travelers", "wallet"]
    assert drifted.travelers == 3  # the caller decides what a mismatch means


# --- the pipeline ---------------------------------------------------------------------------- #


def test_pipeline_applies_a_structured_authority_over_the_model(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    authority = project_structured_trip_spec(_structured(), kb)
    llm = Recording(_scripts(_model_spec()))
    response = run_pipeline(
        render_structured_raw_request(_structured()),
        kb,
        llm,
        booking_date=date(2026, 7, 25),
        trace_dir=tmp_path,
        authority=authority,
    )
    assert response.status == PipelineStatus.OK
    trip_line = _trip_line(llm.prompts["planner"][0])
    assert "museums" in trip_line and "vegetarian" in trip_line
    assert "nightlife" not in trip_line  # the model's reading did not survive
    trace = json.loads((tmp_path / f"{response.trace_id}.json").read_text())
    (event,) = [e for e in trace if e["name"] == "authority"]
    assert sorted(event["attributes"]["overridden"]) == ["dietary", "interests", "pace"]


def test_pipeline_asks_for_clarification_when_the_model_contradicts_identity(
    tmp_path: Path,
) -> None:
    kb = _kb(tmp_path)
    authority = project_structured_trip_spec(_structured(), kb)
    llm = Recording(_scripts(_model_spec(travelers=5)))
    response = run_pipeline(
        "x", kb, llm, booking_date=date(2026, 7, 25), trace_dir=tmp_path, authority=authority
    )
    assert response.status == PipelineStatus.NEEDS_CLARIFICATION
    assert "travelers" in response.unresolved[0]
    assert "planner" not in llm.prompts  # nothing downstream ran on a contradicted spec


def test_a_supplied_wallet_replaces_the_models_reading(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    llm = Recording(_scripts(_model_spec(wallet=UserWallet(card_ids=[]))))
    wallet = UserWallet(card_ids=["hdfc-infinia"], points_balances={"voyager-prime": 777})
    response = run_pipeline(
        "x", kb, llm, booking_date=date(2026, 7, 25), trace_dir=tmp_path, wallet_override=wallet
    )
    assert response.status == PipelineStatus.OK
    assert '"voyager-prime":777' in llm.prompts["critic"][0]
    assert "hdfc-infinia" in llm.prompts["critic"][0]


def test_a_supplied_wallet_with_an_unknown_card_needs_clarification(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    llm = Recording(_scripts(_model_spec()))
    response = run_pipeline(
        "x",
        kb,
        llm,
        booking_date=date(2026, 7, 25),
        trace_dir=tmp_path,
        wallet_override=UserWallet(card_ids=["no-such-card"]),
    )
    assert response.status == PipelineStatus.NEEDS_CLARIFICATION
    assert response.unresolved == ["unknown card id: no-such-card"]


def _api_client(tmp_path: Path, llm: ScriptedLLMClient) -> TestClient:
    kb = _kb(tmp_path)
    app.dependency_overrides[get_kb] = lambda: kb
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_booking_date] = lambda: date(2026, 7, 25)
    app.dependency_overrides[get_trace_dir] = lambda: tmp_path
    return TestClient(app)


def _finish(client: TestClient, response: Any) -> dict[str, Any]:
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        job: dict[str, Any] = client.get(f"/plan/{job_id}").json()
        if job["status"] in ("complete", "needs_clarification", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_post_plan_no_longer_drops_the_wallet_it_was_given(tmp_path: Path) -> None:
    llm = Recording(_scripts(_model_spec(wallet=UserWallet(card_ids=[]))))
    client = _api_client(tmp_path, llm)
    job = _finish(
        client,
        client.post(
            "/plan",
            json={
                "raw_request": "Delhi to Singapore Aug 1-5",
                "wallet": {"card_ids": ["hdfc-infinia"], "points_balances": {}},
            },
        ),
    )
    assert job["status"] == "complete", job
    assert "hdfc-infinia" in llm.prompts["critic"][0]


def test_post_plan_with_an_unknown_wallet_card_needs_clarification(tmp_path: Path) -> None:
    client = _api_client(tmp_path, Recording(_scripts(_model_spec())))
    job = _finish(
        client,
        client.post(
            "/plan",
            json={"raw_request": "x", "wallet": {"card_ids": ["no-such-card"]}},
        ),
    )
    assert job["status"] == "needs_clarification"
    assert job["unresolved"] == ["unknown card id: no-such-card"]


def test_confirmed_brief_preferences_override_the_models_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    prompts: dict[str, list[str]] = {}
    original = kit.llm.complete_json

    def recording(*, node: str, user: str, **kwargs: Any) -> Any:
        prompts.setdefault(node, []).append(user)
        return original(node=node, user=user, **kwargs)

    kit.llm.complete_json = recording  # type: ignore[method-assign]
    kit.queue_run()
    # The model "reads" different preferences than the traveler confirmed.
    (scripted,) = kit.llm._scripts["intake"]
    assert isinstance(scripted, TripSpec)
    kit.llm._scripts["intake"][0] = scripted.model_copy(
        update={"interests": ["nightlife"], "pace": "packed", "dietary": ["vegan"]}
    )
    session = confirm(client, run_interview(client))
    job = wait_for_job(client, session["id"])
    assert job["status"] == "complete", job
    trip_line = _trip_line(prompts["planner"][0])
    assert '"interests":["food"]' in trip_line  # the brief's interest
    assert "nightlife" not in trip_line and "vegan" not in trip_line
    assert '"pace":"moderate"' in trip_line


# --- the critic ------------------------------------------------------------------------------ #


@pytest.mark.parametrize(
    ("failure", "cause"),
    [
        (LLMBudgetExceeded("cap", scope="per_plan"), "budget"),
        (LLMProviderUnavailable("down"), "provider"),
        (LLMCallError("boom"), "provider"),
        (LLMInvalidResponse("critic schema repair failed"), "invalid response"),
    ],
)
def test_critic_failures_are_named_and_never_recorded_as_a_pass(
    tmp_path: Path, failure: Exception, cause: str
) -> None:
    kb = _kb(tmp_path)
    llm = ScriptedLLMClient(_scripts(_model_spec(), critic=[failure]))
    response = run_pipeline("x", kb, llm, booking_date=date(2026, 7, 25), trace_dir=tmp_path)
    assert response.status == PipelineStatus.OK and response.report is not None
    assert (
        f"Critic unavailable ({cause}); itinerary was not LLM-reviewed." in response.report.caveats
    )
    trace = json.loads((tmp_path / f"{response.trace_id}.json").read_text())
    (critic,) = [e for e in trace if e["name"] == "critic"]
    assert critic["attributes"]["critic_skipped"] is True


def test_a_healthy_critic_is_not_marked_skipped(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    response = run_pipeline(
        "x",
        kb,
        ScriptedLLMClient(_scripts(_model_spec())),
        booking_date=date(2026, 7, 25),
        trace_dir=tmp_path,
    )
    trace = json.loads((tmp_path / f"{response.trace_id}.json").read_text())
    (critic,) = [e for e in trace if e["name"] == "critic"]
    assert critic["attributes"]["critic_skipped"] is False


def test_an_unexpected_critic_exception_is_a_bug_and_propagates(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    llm = ScriptedLLMClient(_scripts(_model_spec(), critic=[RuntimeError("bug")]))
    with pytest.raises(RuntimeError, match="bug"):
        run_pipeline("x", kb, llm, booking_date=date(2026, 7, 25), trace_dir=tmp_path)


def test_an_intake_budget_failure_carries_its_stable_error_code(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    llm = ScriptedLLMClient({"intake": [LLMBudgetExceeded("cap", scope="per_day")]})
    response = run_pipeline("x", kb, llm, booking_date=date(2026, 7, 25), trace_dir=tmp_path)
    assert response.status == PipelineStatus.ERROR
    assert response.error_code == "LLM_BUDGET_EXHAUSTED"
