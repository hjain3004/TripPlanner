"""Offline end-to-end coverage for the four CP4 approval execution classes."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from accounts.models import PreferenceValue, TravelPreferenceProfile
from accounts.store import AccountStore
from api.main import app
from core.models import UserWallet
from evals.a4_support import PlanningKit, csrf, finished_plan, signed_in_client


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _workspace(client: object, session_id: str) -> dict[str, object]:
    response = client.get(f"/planning/sessions/{session_id}/workspace")  # type: ignore[union-attr]
    assert response.status_code == 200, response.text
    return dict(response.json())


def _session(client: object, session_id: str) -> dict[str, object]:
    response = client.get(f"/planning/sessions/{session_id}")  # type: ignore[union-attr]
    assert response.status_code == 200, response.text
    return dict(response.json())


def _propose_and_approve(
    client: object, session_id: str, action: dict[str, object], *, event: str
) -> dict[str, object]:
    workspace = _workspace(client, session_id)
    session = _session(client, session_id)
    headers = csrf(client)  # type: ignore[arg-type]
    proposed = client.post(  # type: ignore[union-attr]
        f"/planning/sessions/{session_id}/actions",
        headers=headers,
        json={
            "client_event_id": f"{event}-propose",
            "expected_session_version": session["version"],
            "expected_workspace_version": workspace["version"],
            "action": action,
        },
    )
    assert proposed.status_code == 200, proposed.text
    after_proposal = _workspace(client, session_id)
    after_session = _session(client, session_id)
    approved = client.post(  # type: ignore[union-attr]
        f"/planning/sessions/{session_id}/actions/{proposed.json()['proposal_id']}/approve",
        headers=csrf(client),  # type: ignore[arg-type]
        json={
            "client_event_id": f"{event}-approve",
            "expected_session_version": after_session["version"],
            "expected_workspace_version": after_proposal["version"],
        },
    )
    assert approved.status_code == 200, approved.text
    return dict(approved.json())


def _propose_only(
    client: object, session_id: str, action: dict[str, object], *, event: str
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    workspace = _workspace(client, session_id)
    session = _session(client, session_id)
    proposed = client.post(  # type: ignore[union-attr]
        f"/planning/sessions/{session_id}/actions",
        headers=csrf(client),  # type: ignore[arg-type]
        json={
            "client_event_id": f"{event}-propose",
            "expected_session_version": session["version"],
            "expected_workspace_version": workspace["version"],
            "action": action,
        },
    )
    assert proposed.status_code == 200, proposed.text
    return dict(proposed.json()), _workspace(client, session_id), _session(client, session_id)


def _plan_and_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[object, AccountStore, dict[str, object]]:
    client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    session, _job = finished_plan(client, kit, wallet=UserWallet(card_ids=[]))
    initialized = client.post(
        f"/planning/sessions/{session['id']}/workspace",
        headers=csrf(client),
        json={"source": "job"},
    )
    assert initialized.status_code == 200, initialized.text
    return client, store, session


def test_wallet_approval_recomputes_from_current_stored_wallet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, session = _plan_and_workspace(tmp_path, monkeypatch)
    user = store.get_user_by_email("traveler@example.com")
    assert user is not None
    store.add_wallet_entry(
        user_id=user.id,
        card_id="hdfc-infinia",
        nickname="Infinia",
        points_balances={"voyager-prime": 1000},
        now=session["updated_at"],  # type: ignore[arg-type]
    )
    result = _propose_and_approve(
        client,
        str(session["id"]),
        {"kind": "wallet_or_objective_change", "adopt_current_wallet": True},
        event="wallet",
    )
    assert result["decision"] == "approved"
    workspace = _workspace(client, str(session["id"]))
    assert workspace["report"]["trip_spec"]["wallet"]["card_ids"] == ["hdfc-infinia"]


def test_wallet_approval_rejects_a_changed_wallet_without_committing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, session = _plan_and_workspace(tmp_path, monkeypatch)
    proposal, proposed_workspace, proposed_session = _propose_only(
        client,
        str(session["id"]),
        {"kind": "wallet_or_objective_change", "adopt_current_wallet": True},
        event="wallet-stale",
    )
    user = store.get_user_by_email("traveler@example.com")
    assert user is not None
    store.add_wallet_entry(
        user_id=user.id,
        card_id="hdfc-infinia",
        nickname="Infinia",
        points_balances={},
        now=datetime.now(UTC),
    )
    approved = client.post(  # type: ignore[union-attr]
        f"/planning/sessions/{session['id']}/actions/{proposal['proposal_id']}/approve",
        headers=csrf(client),  # type: ignore[arg-type]
        json={
            "client_event_id": "wallet-stale-approve",
            "expected_session_version": proposed_session["version"],
            "expected_workspace_version": proposed_workspace["version"],
        },
    )
    assert approved.status_code == 409
    assert approved.json()["detail"]["code"] == "STALE_WALLET"
    assert _workspace(client, str(session["id"]))["current_result_id"] == proposed_workspace[
        "current_result_id"
    ]


def test_scoped_replan_approves_without_provider_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, session = _plan_and_workspace(tmp_path, monkeypatch)
    result = _propose_and_approve(
        client,
        str(session["id"]),
        {
            "kind": "scoped_itinerary_replan",
            "scope": "dates",
            "affected_dates": ["2026-11-01"],
            "day_theme": "nature escape",
        },
        event="scoped",
    )
    assert result["decision"] == "approved"


def test_approval_replay_returns_original_outcome_before_stale_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, session = _plan_and_workspace(tmp_path, monkeypatch)
    proposal, proposed_workspace, proposed_session = _propose_only(
        client,
        str(session["id"]),
        {"kind": "wallet_or_objective_change", "adopt_current_wallet": True},
        event="replay",
    )
    first = client.post(  # type: ignore[union-attr]
        f"/planning/sessions/{session['id']}/actions/{proposal['proposal_id']}/approve",
        headers=csrf(client),  # type: ignore[arg-type]
        json={
            "client_event_id": "replay-approve",
            "expected_session_version": proposed_session["version"],
            "expected_workspace_version": proposed_workspace["version"],
        },
    )
    assert first.status_code == 200, first.text
    second = client.post(  # type: ignore[union-attr]
        f"/planning/sessions/{session['id']}/actions/{proposal['proposal_id']}/approve",
        headers=csrf(client),  # type: ignore[arg-type]
        json={
            "client_event_id": "replay-approve",
            "expected_session_version": 0,
            "expected_workspace_version": 1,
        },
    )
    assert second.status_code == 200, second.text
    assert second.json() == first.json()


def test_explanation_approval_returns_a_deterministic_artifact_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, session = _plan_and_workspace(tmp_path, monkeypatch)
    report_lines = _workspace(client, str(session["id"]))["report"]["costed_trip"]["lines"]
    target_id = report_lines[0]["id"]  # type: ignore[index]
    result = _propose_and_approve(
        client,
        str(session["id"]),
        {
            "kind": "explanation_request",
            "target_kind": "cost_line",
            "target_id": target_id,
            "topic": "how_priced",
        },
        event="explain",
    )
    assert "explanation" in result
    assert "minor units" in str(result["explanation"])


def test_provider_invalidating_change_uses_sample_gateway_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, session = _plan_and_workspace(tmp_path, monkeypatch)
    result = _propose_and_approve(
        client,
        str(session["id"]),
        {
            "kind": "provider_invalidating_change",
            "patch": {
                "entries": [
                    {
                        "question_id": "trip_essentials",
                        "payload": {
                            "origin": "DEL",
                            "destination": "SIN",
                            "start_date": "2026-11-02",
                            "end_date": "2026-11-06",
                            "travelers": 2,
                            "date_flexibility_days": 0,
                        },
                    }
                ]
            },
        },
        event="provider",
    )
    assert result["decision"] == "approved"


def test_profile_approval_merges_one_section_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, session = _plan_and_workspace(tmp_path, monkeypatch)
    result = _propose_and_approve(
        client,
        str(session["id"]),
        {
            "kind": "profile_update_proposal",
            "section": "flight",
            "candidate": {
                "cabin": "economy",
                "max_stops": 0,
                "schedule": "morning",
                "airport_flexible": False,
                "checked_baggage": False,
                "seat": "window",
            },
        },
        event="profile",
    )
    assert result["decision"] == "approved"
    user = store.get_user_by_email("traveler@example.com")
    assert user is not None
    profile = AccountStore.open(tmp_path / "accounts.sqlite").get_travel_preferences(user.id)
    assert profile is not None
    assert profile.flight.seat is not None and profile.flight.seat.value == "window"


def test_profile_approval_conflicts_on_same_section_but_merges_unrelated_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, session = _plan_and_workspace(tmp_path, monkeypatch)
    user = store.get_user_by_email("traveler@example.com")
    assert user is not None
    now = datetime.now(UTC)
    store.put_travel_preferences(TravelPreferenceProfile(user_id=user.id, updated_at=now))
    proposal, proposed_workspace, proposed_session = _propose_only(
        client,
        str(session["id"]),
        {
            "kind": "profile_update_proposal",
            "section": "flight",
            "candidate": {
                "cabin": "economy",
                "max_stops": 0,
                "schedule": "morning",
                "airport_flexible": False,
                "checked_baggage": False,
                "seat": "window",
            },
        },
        event="profile-race",
    )
    current = store.get_travel_preferences(user.id)
    assert current is not None
    store.put_travel_preferences(
        current.model_copy(
            update={
                "stay": current.stay.model_copy(
                    update={
                        "location_price_tradeoff": PreferenceValue(
                            value="price", source="user_profile_edit", updated_at=now
                        )
                    }
                )
            }
        )
    )
    approved = client.post(  # type: ignore[union-attr]
        f"/planning/sessions/{session['id']}/actions/{proposal['proposal_id']}/approve",
        headers=csrf(client),  # type: ignore[arg-type]
        json={
            "client_event_id": "profile-race-approve",
            "expected_session_version": proposed_session["version"],
            "expected_workspace_version": proposed_workspace["version"],
        },
    )
    assert approved.status_code == 200, approved.text
    merged = store.get_travel_preferences(user.id)
    assert merged is not None
    assert merged.flight.seat is not None and merged.flight.seat.value == "window"
    assert (
        merged.stay.location_price_tradeoff is not None
        and merged.stay.location_price_tradeoff.value == "price"
    )

    proposal2, proposed_workspace2, proposed_session2 = _propose_only(
        client,
        str(session["id"]),
        {
            "kind": "profile_update_proposal",
            "section": "flight",
            "candidate": {
                "cabin": "economy",
                "max_stops": 0,
                "schedule": "evening",
                "airport_flexible": False,
                "checked_baggage": False,
                "seat": "aisle",
            },
        },
        event="profile-conflict",
    )
    changed = store.get_travel_preferences(user.id)
    assert changed is not None
    store.put_travel_preferences(
        changed.model_copy(update={"flight": changed.flight.model_copy(update={"seat": None})})
    )
    conflict = client.post(  # type: ignore[union-attr]
        f"/planning/sessions/{session['id']}/actions/{proposal2['proposal_id']}/approve",
        headers=csrf(client),  # type: ignore[arg-type]
        json={
            "client_event_id": "profile-conflict-approve",
            "expected_session_version": proposed_session2["version"],
            "expected_workspace_version": proposed_workspace2["version"],
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "PROFILE_SECTION_CONFLICT"
