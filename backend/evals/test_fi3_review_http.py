"""HTTP-level checks for the FI3 loopback review app.

These use Starlette's ``TestClient``, which is not a browser: it sends exactly the headers a
test gives it. So ``Origin`` is set by hand below, and
``test_referrer_policy_lets_browsers_send_the_real_origin`` pins the one response header that
decides what a real browser sends. A real-browser run is what found that header wrong
(``Referrer-Policy: no-referrer`` makes browsers send ``Origin: null`` on same-origin form
POSTs, which the strict origin check rejects); see ``reports/integration_fi3_welcome_pdf.md``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from evals.test_fi2_extraction import NOW
from evals.test_fi3_review_activation import runtime
from ingestion.review_app import ReviewAppConfig, SessionRegistry, create_review_app

PORT = 8765
ORIGIN = f"http://127.0.0.1:{PORT}"
SAME_ORIGIN = {"origin": ORIGIN}


@pytest.fixture
def review(tmp_path: Path):  # type: ignore[no-untyped-def]
    store, service, planner, proposal_id = runtime(tmp_path)
    sessions = SessionRegistry(now=lambda: NOW)
    app = create_review_app(
        service=service, planner=planner, sessions=sessions, config=ReviewAppConfig(port=PORT)
    )
    client = TestClient(app, base_url=ORIGIN, follow_redirects=False)
    return client, sessions, store, proposal_id


def _login(client: TestClient, sessions: SessionRegistry) -> None:
    token = sessions.issue_login_token("alice")
    response = client.post("/review/login", data={"token": token}, headers=SAME_ORIGIN)
    assert response.status_code == 303 and response.headers["location"] == "/review/proposals"


def _field(page: str, name: str) -> str:
    match = re.search(rf"name='{name}' value='([^']*)'", page)
    assert match is not None, f"form field {name!r} not rendered"
    return match.group(1)


def test_login_inspect_and_approve_over_http_is_durable(review) -> None:  # type: ignore[no-untyped-def]
    client, sessions, store, proposal_id = review
    _login(client, sessions)

    queue = client.get("/review/proposals")
    assert queue.status_code == 200 and proposal_id in queue.text

    page = client.get("/review/proposal", params={"id": proposal_id}).text
    form = {
        "csrf_token": _field(page, "csrf_token"),
        "client_event_id": _field(page, "client_event_id"),
        "proposal_id": _field(page, "proposal_id"),
        "expected_version": _field(page, "expected_version"),
        "reason": "reviewed synthetic fixture over HTTP",
        "curator_confidence": "0.90",
        "action": "approve",
    }
    posted = client.post("/review/decision", data=form, headers=SAME_ORIGIN)
    assert posted.status_code == 303

    (decision,) = store.list_decisions(proposal_id)
    assert decision.status == "approved" and decision.reviewer_id == "alice"

    # The same form submitted again (a double click, a retry) is a replay, not a second decision.
    again = client.post("/review/decision", data=form, headers=SAME_ORIGIN)
    assert again.status_code == 303
    assert len(store.list_decisions(proposal_id)) == 1


def test_origin_host_and_csrf_guards_stay_strict(review) -> None:  # type: ignore[no-untyped-def]
    client, sessions, store, proposal_id = review

    for headers in ({"origin": "null"}, {"origin": "http://evil.example"}, {}):
        refused = client.post("/review/login", data={"token": "x"}, headers=headers)
        assert refused.status_code == 403 and "invalid_origin" in refused.text

    wrong_host = client.get("/review/login", headers={"host": "evil.example"})
    assert wrong_host.status_code == 400 and "invalid_host" in wrong_host.text

    _login(client, sessions)
    page = client.get("/review/proposal", params={"id": proposal_id}).text
    form = {
        "csrf_token": "not-the-session-token",
        "client_event_id": _field(page, "client_event_id"),
        "proposal_id": proposal_id,
        "expected_version": _field(page, "expected_version"),
        "reason": "forged",
        "curator_confidence": "0.90",
        "action": "approve",
    }
    forged = client.post("/review/decision", data=form, headers=SAME_ORIGIN)
    assert forged.status_code == 403 and "csrf_failed" in forged.text
    assert store.list_decisions(proposal_id) == []


def test_referrer_policy_lets_browsers_send_the_real_origin(review) -> None:  # type: ignore[no-untyped-def]
    client, *_ = review
    headers = client.get("/review/login").headers
    # Not "no-referrer": that makes a real browser send `Origin: null` on our own same-origin
    # form POSTs, and the origin check above (correctly) refuses `null`.
    assert headers["referrer-policy"] == "same-origin"
    assert headers["x-frame-options"] == "DENY"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["cache-control"] == "no-store"
    assert "form-action 'self'" in headers["content-security-policy"]
