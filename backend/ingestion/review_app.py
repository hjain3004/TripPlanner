from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ingestion.activation import ActivationPlanner
from ingestion.review import ReviewService
from ingestion.review_html import (
    render_bundle,
    render_error,
    render_login,
    render_proposal,
    render_queue,
)
from ingestion.review_types import DecisionRequest
from ingestion.storage import AlreadyDecidedError, IdempotencyConflictError, StaleVersionError


@dataclass(frozen=True)
class ReviewAppConfig:
    port: int
    max_body_bytes: int = 65536
    session_idle: timedelta = timedelta(minutes=30)
    session_absolute: timedelta = timedelta(hours=8)
    login_ttl: timedelta = timedelta(minutes=10)
    max_login_failures: int = 5

    @property
    def allowed_hosts(self) -> tuple[str, ...]:
        return (f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}")

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        return tuple(f"http://{host}" for host in self.allowed_hosts)


@dataclass
class Session:
    curator_id: str
    csrf_token: str
    created_at: datetime
    last_seen: datetime


class SessionRegistry:
    def __init__(self, *, now: Callable[[], datetime]) -> None:
        self.now = now
        self._login: dict[str, tuple[str, datetime, int]] = {}
        self._sessions: dict[str, Session] = {}

    def issue_login_token(self, curator_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self._login[token] = (curator_id, self.now(), 0)
        return token

    def exchange(self, token: str) -> tuple[str, str] | None:
        item = self._login.pop(token, None)
        if item is None or self.now() - item[1] > timedelta(minutes=10):
            return None
        session = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        self._sessions[session] = Session(item[0], csrf, self.now(), self.now())
        return session, csrf

    def resolve(self, session_token: str) -> Session | None:
        session = self._sessions.get(session_token)
        if session is None:
            return None
        if self.now() - session.last_seen > timedelta(
            minutes=30
        ) or self.now() - session.created_at > timedelta(hours=8):
            self._sessions.pop(session_token, None)
            return None
        session.last_seen = self.now()
        return session

    def revoke(self, session_token: str) -> None:
        self._sessions.pop(session_token, None)


ROUTES = frozenset(
    {
        ("GET", "/review/login"),
        ("POST", "/review/login"),
        ("POST", "/review/logout"),
        ("GET", "/review/proposals"),
        ("GET", "/review/proposal"),
        ("POST", "/review/decision"),
        ("GET", "/review/snapshot/raw"),
        ("POST", "/review/bundles"),
        ("GET", "/review/bundle"),
        ("GET", "/review/bundle/download"),
        ("GET", "/review/static/review.css"),
    }
)


def create_review_app(
    *,
    service: ReviewService,
    planner: ActivationPlanner,
    sessions: SessionRegistry,
    config: ReviewAppConfig,
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    async def form_body(request: Request) -> dict[str, str]:
        values = parse_qs(
            (await request.body()).decode("utf-8"),
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=200,
        )
        return {key: items[-1] for key, items in values.items()}

    @app.middleware("http")
    async def security(request: Request, call_next: Callable[..., object]) -> Response:
        host = request.headers.get("host", "")
        if host not in config.allowed_hosts:
            response = HTMLResponse(render_error(400, "invalid_host"), status_code=400)
        elif (
            request.method == "POST"
            and int(request.headers.get("content-length", "0")) > config.max_body_bytes
        ):
            response = HTMLResponse(render_error(413, "body_too_large"), status_code=413)
        elif (
            request.method == "POST" and request.headers.get("origin") not in config.allowed_origins
        ):
            response = HTMLResponse(render_error(403, "invalid_origin"), status_code=403)
        else:
            response = await call_next(request)  # type: ignore[misc]
        # `no-referrer` makes browsers send `Origin: null` on same-origin form POSTs
        # (Fetch standard), which the strict origin check above would reject; `same-origin`
        # still sends no Referer cross-origin and keeps the real Origin on our own forms.
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "same-origin",
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; style-src 'self' "
                "'unsafe-inline'; form-action 'self'; base-uri 'none'",
            }
        )
        return response

    def session_for(request: Request) -> Session | None:
        return sessions.resolve(request.cookies.get("fi3_review_session", ""))

    @app.get("/review/login", response_class=HTMLResponse)
    async def login() -> str:
        return render_login()

    @app.post("/review/login", response_class=HTMLResponse)
    async def login_post(request: Request) -> Response:
        form = await form_body(request)
        exchanged = sessions.exchange(form.get("token", ""))
        if exchanged is None:
            return HTMLResponse(render_login("invalid_login"), status_code=403)
        token, _csrf = exchanged
        response = RedirectResponse("/review/proposals", status_code=303)
        response.set_cookie(
            "fi3_review_session", token, httponly=True, samesite="strict", path="/review"
        )
        return response

    @app.post("/review/logout")
    async def logout(request: Request) -> Response:
        session = session_for(request)
        if session is None or request.headers.get("x-csrf-token") != session.csrf_token:
            return HTMLResponse(render_error(403, "csrf_failed"), status_code=403)
        sessions.revoke(request.cookies.get("fi3_review_session", ""))
        return RedirectResponse("/review/login", status_code=303)

    @app.get("/review/proposals", response_class=HTMLResponse)
    async def proposals(request: Request) -> Response:
        if session_for(request) is None:
            return RedirectResponse("/review/login", status_code=303)
        return HTMLResponse(render_queue(service.list_queue()))

    @app.get("/review/proposal", response_class=HTMLResponse)
    async def proposal(request: Request) -> Response:
        if session_for(request) is None:
            return RedirectResponse("/review/login", status_code=303)
        try:
            ctx = service.context(request.query_params.get("id", ""))
        except KeyError:
            return HTMLResponse(render_error(404, "not_found"), status_code=404)
        session = session_for(request)
        assert session is not None
        return HTMLResponse(
            render_proposal(
                ctx, csrf_token=session.csrf_token, client_event_id=secrets.token_urlsafe(18)
            )
        )

    @app.post("/review/decision")
    async def decision(request: Request) -> Response:
        session = session_for(request)
        if session is None:
            return HTMLResponse(render_error(401, "login_required"), status_code=401)
        form = await form_body(request)
        if form.get("csrf_token", "") != session.csrf_token:
            return HTMLResponse(render_error(403, "csrf_failed"), status_code=403)
        try:
            edit_values = []
            if form.get("edit_field_path"):
                edit_values.append(
                    {
                        "field_path": form["edit_field_path"],
                        "action": "set",
                        "proposed_raw_value": form.get("edit_raw_value"),
                        "quote": form.get("edit_quote"),
                        "snapshot_id": form.get("edit_snapshot_id"),
                        "occurrence": form.get("edit_occurrence"),
                        "page_number": form.get("edit_page_number"),
                    }
                )
            req = DecisionRequest.model_validate(
                {
                    "proposal_id": form.get("proposal_id"),
                    "action": form.get("action"),
                    "reason": form.get("reason"),
                    "expected_version": form.get("expected_version"),
                    "client_event_id": form.get("client_event_id"),
                    "curator_confidence": form.get("curator_confidence"),
                    "edits": edit_values,
                }
            )
            service.decide(req, curator_id=session.curator_id)
        except (AlreadyDecidedError, StaleVersionError, IdempotencyConflictError) as error:
            return HTMLResponse(render_error(409, str(error)), status_code=409)
        except Exception as error:
            return HTMLResponse(render_error(422, str(error)), status_code=422)
        return RedirectResponse(f"/review/proposal?id={req.proposal_id}", status_code=303)

    @app.get("/review/snapshot/raw", response_class=HTMLResponse)
    async def raw(request: Request) -> Response:
        if session_for(request) is None:
            return RedirectResponse("/review/login", status_code=303)
        snapshot = service.store.get_snapshot(request.query_params.get("id", ""))
        if snapshot is None:
            return HTMLResponse(render_error(404, "not_found"), status_code=404)
        from ingestion.review_html import h

        return HTMLResponse(f"<pre>{h(snapshot.canonical_markdown)}</pre>")

    @app.get("/review/static/review.css")
    async def css() -> Response:
        return Response(
            "body{font-family:system-ui;max-width:70rem;margin:2rem auto}mark{background:#ffd}",
            media_type="text/css",
        )

    @app.post("/review/bundles")
    async def bundles(request: Request) -> Response:
        session = session_for(request)
        if session is None:
            return JSONResponse({"error": "login_required"}, status_code=401)
        form = await form_body(request)
        if form.get("csrf_token", "") != session.csrf_token:
            return JSONResponse({"error": "csrf_failed"}, status_code=403)
        record, bundle = planner.build(
            proposal_ids=None,
            curator_id=session.curator_id,
            client_event_id=form.get("client_event_id", ""),
        )
        return JSONResponse(
            {"bundle_sha256": record.bundle_sha256, "applicable": bundle.applicable},
            status_code=303,
            headers={"Location": f"/review/bundle?id={record.bundle_sha256}"},
        )

    @app.get("/review/bundle", response_class=HTMLResponse)
    async def bundle(request: Request) -> Response:
        if session_for(request) is None:
            return RedirectResponse("/review/login", status_code=303)
        bundle_id = request.query_params.get("id", "")
        record_json = service.store.get_activation_bundle(bundle_id)
        if record_json is None:
            return HTMLResponse(render_error(404, "not_found"), status_code=404)
        from ingestion.activation import ActivationBundleRecord

        record = ActivationBundleRecord.model_validate_json(record_json)
        body = planner.artifacts.read(record.artifact)
        from ingestion.activation import ActivationBundle

        bundle = ActivationBundle.model_validate_json(body)
        report = planner.dry_run(bundle_id)
        session = session_for(request)
        assert session is not None
        return HTMLResponse(
            render_bundle(
                record,
                bundle,
                report,
                csrf_token=session.csrf_token,
                client_event_id=secrets.token_urlsafe(18),
            )
        )

    @app.get("/review/bundle/download")
    async def download(request: Request) -> Response:
        if session_for(request) is None:
            return RedirectResponse("/review/login", status_code=303)
        bundle_id = request.query_params.get("id", "")
        record_json = service.store.get_activation_bundle(bundle_id)
        if record_json is None:
            return Response("not found", status_code=404)
        record = __import__(
            "ingestion.activation", fromlist=["ActivationBundleRecord"]
        ).ActivationBundleRecord.model_validate_json(record_json)
        return Response(
            planner.artifacts.read(record.artifact),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{bundle_id}.json"'},
        )

    return app
