"""Cookie, CSRF, and current-user plumbing for the auth endpoints (spec 17 §4).

The session cookie is httpOnly so no script can read it. The CSRF cookie is
deliberately NOT httpOnly: the app's own JS must read it and echo it in a
header, which an attacker's page cannot do. SameSite=Lax is a second layer,
not a substitute for the token.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, Response

from accounts.models import User
from accounts.store import AccountStore

SESSION_COOKIE = "tp_session"
CSRF_COOKIE = "tp_csrf"
CSRF_HEADER = "X-CSRF-Token"


def get_store() -> AccountStore:
    return AccountStore.open()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_session_cookies(
    response: Response, token: str, csrf_token: str, expires_at: datetime
) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        expires=expires_at,
    )
    # Not httpOnly by design — the SPA reads this and echoes it in CSRF_HEADER.
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        secure=True,
        samesite="lax",
        path="/",
        expires=expires_at,
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def require_csrf(request: Request) -> None:
    """Double-submit check. Call on every state-changing request."""
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(status_code=403, detail="CSRF check failed")


def current_user(
    request: Request, store: AccountStore = Depends(get_store)
) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = store.session_for_token(token, now=now_utc())
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = store.get_user(session.user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
