"""Durable CP3 budget, consent, auth, replay and concurrent session acceptance."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from fastapi.testclient import TestClient

import api.conversation as conversation
from accounts.store import AccountStore
from agents.interview_assistant import get_interview_llm
from agents.llm import LLMCallError, ScriptedLLMClient
from api.auth import get_store, now_utc
from api.main import app
from evals.test_cp1_policy import _answer_core, _flight, _food, _start
from evals.test_cp2_api import _client, _csrf
from planning.answers import QuestionId
from planning.assistance import AssistanceRequestRecord
from planning.contracts import PlanningSession, PlanningSessionStatus
from planning.policy import record_assistant_suggestions
from planning.repository import PlanningSessionRepository


@pytest.fixture(autouse=True)
def clean_overrides() -> Any:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _setup(
    tmp_path: Path, *, reviewing: bool = False, last_core: bool = False
) -> tuple[TestClient, AccountStore, PlanningSession]:
    client, store = _client(tmp_path)
    user = store.get_user_by_email("traveler@example.com")
    assert user
    session = _answer_core(_start(), food=_food(["local cuisine"]), flight=_flight(None))
    if reviewing:
        session = record_assistant_suggestions(
            session,
            [],
            assistance_status="degraded",
            llm_calls=0,
            expected_version=session.version,
            now=session.updated_at,
        )
        # A real CP2 review can be used with a second semantic request.
        session = session.model_copy(
            update={"status": PlanningSessionStatus.REVIEWING, "current_question_id": None}
        )
    if last_core:
        answers = dict(session.answers)
        del answers[QuestionId.HARD_CONSTRAINTS]
        session = session.model_copy(
            update={
                "answers": answers,
                "processed_event_ids": session.processed_event_ids[:-1],
                "status": PlanningSessionStatus.INTERVIEWING,
                "current_question_id": QuestionId.HARD_CONSTRAINTS,
            }
        )
    now = now_utc()
    session = PlanningSession.model_validate(
        session.model_copy(
            update={
                "id": "cp3-session",
                "user_id": user.id,
                "created_at": now,
                "updated_at": now,
                "expires_at": now + timedelta(days=30),
            }
        ).model_dump()
    )
    PlanningSessionRepository(store).create(session)
    return client, store, session


def _review() -> dict[str, Any]:
    return {
        "acknowledgement": "Your local food interests deserve a closer look.",
        "acknowledgement_answer_ids": ["experiences_and_food"],
        "question_ids": ["food_depth"],
        "wording": {"food_depth": "Which local dishes should shape your days?"},
        "contradictions": [],
    }


def _interpret_body(version: int, **changes: Any) -> dict[str, Any]:
    return {
        "question_id": "daily_rhythm",
        "expected_version": version,
        "text": "Slow mornings, quiet evenings and no day trips.",
        "client_event_id": "semantic-1",
        **changes,
    }


def _candidate() -> dict[str, Any]:
    return {
        "question_id": "daily_rhythm",
        "payload": {
            "pace": "relaxed",
            "day_start": "late",
            "evening_style": "quiet",
            "downtime_minutes": None,
            "transit_tolerance_minutes": None,
            "day_trip_appetite": "none",
        },
    }


def test_eighth_answer_runs_one_review_and_replay_never_calls_again(tmp_path: Path) -> None:
    client, store, session = _setup(tmp_path, last_core=True)
    llm = ScriptedLLMClient({"interview_review": [_review()]})
    app.dependency_overrides[get_interview_llm] = lambda: llm
    body = {
        "question_id": "hard_constraints",
        "expected_version": session.version,
        "payload": {"has_constraints": False},
        "client_event_id": "eighth",
    }
    response = client.post(
        f"/planning/sessions/{session.id}/answers", json=body, headers=_csrf(client)
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["assistance_status"] == "complete"
    assert result["interview_llm_calls"] == 1
    assert result["current_question"]["id"] == "food_depth"
    assert result["current_question"]["prompt"] == "Which local dishes should shape your days?"
    assert any(event["kind"] == "assistant_acknowledgement" for event in result["events"])
    replay = client.post(
        f"/planning/sessions/{session.id}/answers", json=body, headers=_csrf(client)
    )
    assert replay.json() == result
    reopened = AccountStore.open(tmp_path / "accounts.sqlite")
    persisted = PlanningSessionRepository(reopened).get(
        user_id=session.user_id, session_id=session.id
    )
    assert persisted and persisted.interview_llm_calls == 1
    assert llm.invocations["interview_review"] == 1
    assert store.get_travel_preferences(session.user_id) is None


def test_interpretation_is_only_a_candidate_and_replays_after_reopen(tmp_path: Path) -> None:
    client, store, session = _setup(tmp_path, reviewing=True)
    llm = ScriptedLLMClient({"interview_interpret": [_candidate()]})
    app.dependency_overrides[get_interview_llm] = lambda: llm
    body = _interpret_body(session.version)
    response = client.post(
        f"/planning/sessions/{session.id}/interpret", json=body, headers=_csrf(client)
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["pending_answer"]["payload"]["pace"] == "relaxed"
    assert result["answers"]["daily_rhythm"]["payload"]["pace"] == "moderate"
    app.dependency_overrides[get_store] = lambda: AccountStore.open(tmp_path / "accounts.sqlite")
    replay = client.post(
        f"/planning/sessions/{session.id}/interpret", json=body, headers=_csrf(client)
    )
    assert replay.json() == result
    assert llm.invocations["interview_interpret"] == 1
    snapshot = store.get_planning_session_snapshot(user_id=session.user_id, session_id=session.id)
    assert snapshot and body["text"] not in snapshot.payload_json
    assert "interview_interpret" not in snapshot.payload_json


@pytest.mark.parametrize(
    "changes",
    [{"text": "Change my pace"}, {"question_id": "flight_preferences"}, {"expected_version": 999}],
)
def test_semantic_event_id_cannot_be_reused_for_another_request(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    client, _, session = _setup(tmp_path, reviewing=True)
    llm = ScriptedLLMClient({"interview_interpret": [_candidate()]})
    app.dependency_overrides[get_interview_llm] = lambda: llm
    body = _interpret_body(session.version)
    assert (
        client.post(
            f"/planning/sessions/{session.id}/interpret", json=body, headers=_csrf(client)
        ).status_code
        == 200
    )
    conflict = client.post(
        f"/planning/sessions/{session.id}/interpret",
        json={**body, **changes},
        headers=_csrf(client),
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert llm.invocations["interview_interpret"] == 1


@pytest.mark.parametrize(
    "failure,diagnostic",
    [
        (LLMCallError("token-secret"), "unavailable"),
        ({"question_ids": ["book_flight"]}, "invalid_response"),
    ],
)
def test_failed_review_is_truthfully_degraded_and_not_retried(
    tmp_path: Path, failure: Any, diagnostic: str
) -> None:
    client, _, session = _setup(tmp_path, last_core=True)
    llm = ScriptedLLMClient({"interview_review": [failure]})
    app.dependency_overrides[get_interview_llm] = lambda: llm
    body = {
        "question_id": "hard_constraints",
        "expected_version": session.version,
        "payload": {"has_constraints": False},
        "client_event_id": "eighth",
    }
    response = client.post(
        f"/planning/sessions/{session.id}/answers", json=body, headers=_csrf(client)
    )
    assert response.status_code == 200
    assert response.json()["assistance_status"] == "degraded"
    assert diagnostic in response.json()["assistance_diagnostics"]
    assert response.json()["interview_llm_calls"] == 1
    assert response.json()["current_question"]["id"] == "flight_tradeoff"
    assert "token-secret" not in response.text
    assert llm.invocations["interview_review"] == 1


def test_pre_checkpoint_interpretation_reserves_the_second_call_for_adaptive_review(
    tmp_path: Path,
) -> None:
    client, _, session = _setup(tmp_path, last_core=True)
    # Ask for interpretation of the current hard-constraint control.
    llm = ScriptedLLMClient(
        {
            "interview_interpret": [
                {"question_id": "hard_constraints", "payload": {"has_constraints": False}}
            ],
            "interview_review": [_review()],
        }
    )
    app.dependency_overrides[get_interview_llm] = lambda: llm
    body = _interpret_body(session.version, question_id="hard_constraints", text="No constraints")
    first = client.post(
        f"/planning/sessions/{session.id}/interpret", json=body, headers=_csrf(client)
    ).json()
    assert first["interview_llm_calls"] == 1
    denied = client.post(
        f"/planning/sessions/{session.id}/interpret",
        json={**body, "client_event_id": "semantic-2", "expected_version": first["version"]},
        headers=_csrf(client),
    )
    assert denied.status_code == 200
    assert denied.json()["interview_llm_calls"] == 1
    assert "budget_exhausted" in denied.json()["assistance_diagnostics"]
    final = client.post(
        f"/planning/sessions/{session.id}/answers",
        json={
            "question_id": "hard_constraints",
            "expected_version": denied.json()["version"],
            "payload": {"has_constraints": False},
            "client_event_id": "eighth",
        },
        headers=_csrf(client),
    )
    assert final.status_code == 200, final.text
    assert final.json()["interview_llm_calls"] == 2
    assert final.json()["assistance_status"] == "complete"


def test_two_connections_race_for_one_call_and_leave_a_consistent_audit(tmp_path: Path) -> None:
    client, _, session = _setup(tmp_path, reviewing=True)
    entered, release = Event(), Event()

    class BlockingClient(ScriptedLLMClient):
        def complete_json(self, **kwargs: Any) -> Any:
            entered.set()
            assert release.wait(10)
            return super().complete_json(**kwargs)

    llm = BlockingClient({"interview_interpret": [_candidate()]})
    app.dependency_overrides[get_interview_llm] = lambda: llm
    # Each dependency resolution opens a separate SQLite connection/engine.
    app.dependency_overrides[get_store] = lambda: AccountStore.open(tmp_path / "accounts.sqlite")
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            client.post,
            f"/planning/sessions/{session.id}/interpret",
            json=_interpret_body(session.version),
            headers=_csrf(client),
        )
        assert entered.wait(10)
        second = executor.submit(
            client.post,
            f"/planning/sessions/{session.id}/interpret",
            json=_interpret_body(session.version, client_event_id="other-event"),
            headers=_csrf(client),
        )
        loser = second.result(timeout=10)
        release.set()
        winner = first.result(timeout=10)
    assert winner.status_code == 200, winner.text
    assert loser.status_code == 409, loser.text
    assert loser.json()["detail"]["code"] == "STALE_SESSION"
    persisted = PlanningSessionRepository(AccountStore.open(tmp_path / "accounts.sqlite")).get(
        user_id=session.user_id, session_id=session.id
    )
    assert persisted and persisted.interview_llm_calls == 1
    assert len(persisted.assistance_requests) == 1
    assert len({event.id for event in persisted.events}) == len(persisted.events)


def test_interpretation_requires_csrf_and_only_supports_current_or_review_questions(
    tmp_path: Path,
) -> None:
    client, _, session = _setup(tmp_path, last_core=True)
    path = f"/planning/sessions/{session.id}/interpret"
    assert client.post(path, json=_interpret_body(session.version)).status_code == 403
    invalid = client.post(path, json=_interpret_body(session.version), headers=_csrf(client))
    assert invalid.status_code == 422


def test_structured_answers_make_no_call_before_the_eighth_decision(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    llm = ScriptedLLMClient({"interview_review": [{}]})
    app.dependency_overrides[get_interview_llm] = lambda: llm
    current = client.post("/planning/sessions", headers=_csrf(client)).json()
    exemplar = _answer_core(_start())
    for index, (question_id, answer) in enumerate(exemplar.answers.items()):
        current = client.post(
            f"/planning/sessions/{current['id']}/answers",
            json={
                "question_id": question_id.value,
                "expected_version": current["version"],
                "payload": answer.payload.model_dump(mode="json") if answer.payload else None,
                "client_event_id": f"typed-{index}",
            },
            headers=_csrf(client),
        ).json()
        assert sum(llm.invocations.values()) == int(index == 7)
    assert current["assistance_status"] == "complete"


def test_two_call_ceiling_survives_reopen_and_new_events(tmp_path: Path) -> None:
    client, _, session = _setup(tmp_path, last_core=True)
    llm = ScriptedLLMClient(
        {
            "interview_review": [_review()],
            "interview_interpret": [
                {"question_id": "food_depth", "payload": {"detail": "Local cuisine"}}
            ],
        }
    )
    app.dependency_overrides[get_interview_llm] = lambda: llm
    reviewed = client.post(
        f"/planning/sessions/{session.id}/answers",
        json={
            "question_id": "hard_constraints",
            "expected_version": session.version,
            "payload": {"has_constraints": False},
            "client_event_id": "eighth",
        },
        headers=_csrf(client),
    ).json()
    body = _interpret_body(reviewed["version"], question_id="food_depth", text="Local cuisine")
    interpreted = client.post(
        f"/planning/sessions/{session.id}/interpret", json=body, headers=_csrf(client)
    ).json()
    assert interpreted["interview_llm_calls"] == 2
    app.dependency_overrides[get_store] = lambda: AccountStore.open(tmp_path / "accounts.sqlite")
    denied = client.post(
        f"/planning/sessions/{session.id}/interpret",
        json={**body, "expected_version": interpreted["version"], "client_event_id": "new-event"},
        headers=_csrf(client),
    ).json()
    assert denied["interview_llm_calls"] == 2
    assert "budget_exhausted" in denied["assistance_diagnostics"]
    assert sum(llm.invocations.values()) == 2


def test_conflicting_answers_block_planning_until_explicit_amendment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, session = _setup(tmp_path, last_core=True)
    response = _review()
    response["contradictions"] = [
        {
            "answer_ids": ["daily_rhythm", "experiences_and_food"],
            "clarification": "Please review how your daily pace fits your food priorities.",
        }
    ]
    app.dependency_overrides[get_interview_llm] = lambda: ScriptedLLMClient(
        {"interview_review": [response]}
    )
    current = client.post(
        f"/planning/sessions/{session.id}/answers",
        json={
            "question_id": "hard_constraints",
            "expected_version": session.version,
            "payload": {"has_constraints": False},
            "client_event_id": "eighth",
        },
        headers=_csrf(client),
    ).json()
    while current["current_question"]:
        current = client.post(
            f"/planning/sessions/{session.id}/skip",
            json={
                "question_id": current["current_question"]["id"],
                "expected_version": current["version"],
                "client_event_id": f"skip-{current['version']}",
            },
            headers=_csrf(client),
        ).json()
    assert current["status"] == "reviewing"
    started = []
    monkeypatch.setattr(conversation, "_start_legacy_job", lambda *args: started.append(args))
    blocked = client.post(
        f"/planning/sessions/{session.id}/confirm",
        json={
            "expected_version": current["version"],
            "brief": current["brief"],
            "client_event_id": "confirm",
        },
        headers=_csrf(client),
    )
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["detail"]["code"] == "UNRESOLVED_CONTRADICTIONS"
    assert not started
    amended = client.post(
        f"/planning/sessions/{session.id}/amend",
        json={
            "question_id": "daily_rhythm",
            "expected_version": current["version"],
            "payload": current["answers"]["daily_rhythm"]["payload"],
            "client_event_id": "review-conflict",
        },
        headers=_csrf(client),
    ).json()
    assert not amended["contradictions"]
    confirmed = client.post(
        f"/planning/sessions/{session.id}/confirm",
        json={
            "expected_version": amended["version"],
            "brief": amended["brief"],
            "client_event_id": "confirm",
        },
        headers=_csrf(client),
    )
    assert confirmed.status_code == 202, confirmed.text
    assert len(started) == 1


def test_read_does_not_cancel_an_inflight_review(tmp_path: Path) -> None:
    client, store, session = _setup(tmp_path)
    # Simulate the reservation committed just before a live call begins.
    from agents.interview_assistant import compact_state
    from api.interview_assistance import fingerprint

    request_hash = fingerprint(compact_state(session))
    reserved = session.model_copy(
        update={
            "interview_llm_calls": 1,
            "assistance_requests": {
                f"review:{request_hash}": AssistanceRequestRecord(fingerprint=request_hash)
            },
            "version": session.version + 1,
        }
    )
    PlanningSessionRepository(store).save(reserved, expected_version=session.version)
    observed = client.get(f"/planning/sessions/{session.id}").json()
    assert observed["status"] == "awaiting_assistant"
    assert observed["assistance_pending"] is True
    assert observed["version"] == reserved.version


def test_interrupted_review_resumes_without_another_llm_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, session = _setup(tmp_path)
    from agents.interview_assistant import compact_state
    from api.interview_assistance import fingerprint

    request_hash = fingerprint(compact_state(session))
    reserved = session.model_copy(
        update={
            "interview_llm_calls": 1,
            "assistance_requests": {
                f"review:{request_hash}": AssistanceRequestRecord(fingerprint=request_hash)
            },
            "version": session.version + 1,
        }
    )
    PlanningSessionRepository(store).save(reserved, expected_version=session.version)
    monkeypatch.setattr(conversation, "now_utc", lambda: session.updated_at + timedelta(seconds=31))
    observed = client.get(f"/planning/sessions/{session.id}").json()
    assert observed["status"] == "interviewing"
    assert observed["interview_llm_calls"] == 1
    assert "interrupted" in observed["assistance_diagnostics"]


def test_interpretation_is_user_scoped(tmp_path: Path) -> None:
    client, _, session = _setup(tmp_path, reviewing=True)
    outsider = TestClient(app, base_url="https://testserver")
    outsider.post(
        "/auth/register", json={"email": "outsider@example.com", "password": "long-password-123"}
    )
    outsider.post(
        "/auth/login", json={"email": "outsider@example.com", "password": "long-password-123"}
    )
    denied = outsider.post(
        f"/planning/sessions/{session.id}/interpret",
        json=_interpret_body(session.version),
        headers=_csrf(outsider),
    )
    assert denied.status_code == 404


def test_interpretation_success_cannot_claim_a_failed_adaptive_review_completed(
    tmp_path: Path,
) -> None:
    client, _, session = _setup(tmp_path, last_core=True)
    llm = ScriptedLLMClient(
        {
            "interview_review": [LLMCallError("unavailable")],
            "interview_interpret": [
                {"question_id": "flight_tradeoff", "payload": {"detail": "Prefer nonstop flights"}}
            ],
        }
    )
    app.dependency_overrides[get_interview_llm] = lambda: llm
    reviewed = client.post(
        f"/planning/sessions/{session.id}/answers",
        json={
            "question_id": "hard_constraints",
            "expected_version": session.version,
            "payload": {"has_constraints": False},
            "client_event_id": "eighth",
        },
        headers=_csrf(client),
    ).json()
    assert reviewed["assistance_status"] == "degraded"
    response = client.post(
        f"/planning/sessions/{session.id}/interpret",
        json=_interpret_body(
            reviewed["version"], question_id="flight_tradeoff", text="Prefer nonstop flights"
        ),
        headers=_csrf(client),
    )
    assert response.status_code == 200
    assert response.json()["pending_answer"] is not None
    assert response.json()["assistance_status"] == "degraded"


def test_interrupted_interpretation_exposes_pending_state_and_recovers_on_poll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, session = _setup(tmp_path, last_core=True)
    reserved = session.model_copy(
        update={
            "interview_llm_calls": 1,
            "assistance_requests": {
                "interpret:interrupted": AssistanceRequestRecord(fingerprint="request")
            },
            "version": session.version + 1,
        }
    )
    PlanningSessionRepository(store).save(reserved, expected_version=session.version)
    assert client.get(f"/planning/sessions/{session.id}").json()["assistance_pending"] is True
    monkeypatch.setattr(conversation, "now_utc", lambda: session.updated_at + timedelta(seconds=40))
    recovered = client.get(f"/planning/sessions/{session.id}").json()
    assert recovered["assistance_pending"] is False
    assert "interrupted" in recovered["assistance_diagnostics"]
    response = client.post(
        f"/planning/sessions/{session.id}/answers",
        json={
            "question_id": "hard_constraints",
            "expected_version": recovered["version"],
            "payload": {"has_constraints": False},
            "client_event_id": "typed-after-recovery",
        },
        headers=_csrf(client),
    )
    assert response.status_code == 200, response.text
    assert response.json()["interview_llm_calls"] == 2


@pytest.mark.parametrize("changed", [False, True])
def test_backtracking_reuses_identical_review_and_never_resets_call_budget(
    tmp_path: Path, changed: bool
) -> None:
    client, _, session = _setup(tmp_path, last_core=True)
    llm = ScriptedLLMClient({"interview_review": [_review()]})
    app.dependency_overrides[get_interview_llm] = lambda: llm
    path = f"/planning/sessions/{session.id}"
    first = client.post(
        f"{path}/answers",
        json={
            "question_id": "hard_constraints",
            "expected_version": session.version,
            "payload": {"has_constraints": False},
            "client_event_id": "eighth",
        },
        headers=_csrf(client),
    )
    assert first.status_code == 200, first.text
    before = first.json()
    back = client.post(
        f"{path}/back",
        json={"expected_version": before["version"], "client_event_id": "back"},
        headers=_csrf(client),
    )
    assert back.status_code == 200, back.text
    assert back.json()["current_question"]["id"] == "hard_constraints"
    payload = (
        {"has_constraints": True, "accessibility": ["step-free access"]}
        if changed
        else {"has_constraints": False}
    )
    second = client.post(
        f"{path}/answers",
        json={
            "question_id": "hard_constraints",
            "expected_version": back.json()["version"],
            "payload": payload,
            "client_event_id": "eighth-again",
        },
        headers=_csrf(client),
    )
    assert second.status_code == 200, second.text
    after = second.json()
    assert after["interview_llm_calls"] == 1
    assert llm.invocations["interview_review"] == 1
    assert after["assistance_status"] == ("degraded" if changed else "complete")
    assert {e["id"] for e in before["events"]} <= {e["id"] for e in after["events"]}
    reopened = AccountStore.open(tmp_path / "accounts.sqlite")
    persisted = PlanningSessionRepository(reopened).get(
        user_id=session.user_id, session_id=session.id
    )
    assert persisted is not None
    assert persisted.interview_llm_calls == 1
    assert len([key for key in persisted.assistance_requests if key.startswith("review:")]) == (
        2 if changed else 1
    )
