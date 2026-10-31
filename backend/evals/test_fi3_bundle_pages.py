"""What the operator sees and receives for a bundle (the web surface of bundle v2).

The page and the JSON used to say ``applicable``. They now report internal consistency only,
state that nothing is authorized, name the open decisions, and show a stored legacy (v1)
bundle as legacy instead of failing to parse it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from evals.test_fi2_extraction import NOW
from evals.test_fi3_bundle_v2 import V1, _approve, _persist
from evals.test_fi3_review_activation import runtime
from ingestion.review_app import ReviewAppConfig, SessionRegistry, create_review_app

PORT = 8765
ORIGIN = f"http://127.0.0.1:{PORT}"
SAME_ORIGIN = {"origin": ORIGIN}


def _client(tmp_path: Path) -> tuple[TestClient, Any, Any, str]:
    _store, service, planner, proposal_id = runtime(tmp_path)
    _approve(service, proposal_id)
    sessions = SessionRegistry(now=lambda: NOW)
    app = create_review_app(
        service=service, planner=planner, sessions=sessions, config=ReviewAppConfig(port=PORT)
    )
    client = TestClient(app, base_url=ORIGIN, follow_redirects=False)
    token = sessions.issue_login_token("alice")
    login = client.post("/review/login", data={"token": token}, headers=SAME_ORIGIN)
    assert login.status_code == 303
    return client, sessions, planner, proposal_id


def _csrf(sessions: Any) -> str:
    (session,) = sessions._sessions.values()
    return str(session.csrf_token)


def test_the_bundles_endpoint_reports_consistency_and_no_authorization(tmp_path: Path) -> None:
    client, sessions, _planner, _pid = _client(tmp_path)
    response = client.post(
        "/review/bundles",
        data={"csrf_token": _csrf(sessions), "client_event_id": "bundle-page-event-0001"},
        headers=SAME_ORIGIN,
    )
    body = response.json()
    assert body["dry_run_consistent"] is True and body["activation_authorized"] is False
    assert "applicable" not in body


def test_the_bundle_page_shows_status_authorization_and_blockers(tmp_path: Path) -> None:
    client, sessions, _planner, _pid = _client(tmp_path)
    created = client.post(
        "/review/bundles",
        data={"csrf_token": _csrf(sessions), "client_event_id": "bundle-page-event-0001"},
        headers=SAME_ORIGIN,
    ).json()
    page = client.get("/review/bundle", params={"id": created["bundle_sha256"]}).text
    assert "Activation authorized: False" in page
    assert "Unresolved decisions: D1, D2" in page
    assert "Dry-run consistent: True" in page and "not readiness to apply" in page
    assert "confirmed_unchanged" in page and "blocked by D1" in page
    assert "Applicable" not in page


def test_a_stored_v1_bundle_renders_as_legacy_instead_of_failing(tmp_path: Path) -> None:
    client, _sessions, planner, proposal_id = _client(tmp_path)
    _record, bundle = planner.build(
        proposal_ids=(proposal_id,), curator_id="alice", client_event_id="bundle-page-event-0002"
    )
    body: dict[str, Any] = json.loads(bundle.model_dump_json())
    body["schema_version"] = V1
    body["applicable"] = True
    for key in ("activation_authorized", "unresolved_decisions", "dry_run_consistent"):
        del body[key]
    for entry in body["entries"]:
        for key in ("evidenced_fields", "provenance_candidate", "blocked_by"):
            del entry[key]
    digest = _persist(planner, body, proposal_id, "legacy-v1-page-0001")
    response = client.get("/review/bundle", params={"id": digest})
    assert response.status_code == 200
    assert "legacy v1 bundle: never consistent" in response.text
    assert "Dry-run consistent: False" in response.text
    assert "Activation authorized: False" in response.text
