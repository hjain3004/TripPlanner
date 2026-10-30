"""Authenticated welcome-window status for a held card (spec 18 Case A, backend slice).

``POST /account/wallet/{entry_id}/welcome-status`` answers: for a card this user holds and
a stored plan revision this user owns, where does the card's welcome window stand and
what does the plan's spend on that card mean for it?

Invariants the handler exists to protect:

* **Authority comes from the session, never the payload.** The wallet entry and the trip
  are resolved through owner-scoped store calls; the request model is ``extra="forbid"``.
* **Wrong owner is indistinguishable from missing.** Each resource answers a foreign id
  exactly as it answers one that does not exist.
* **Trip amounts are server-owned.** They are read from the stored revision's computed
  optimizer result. The request carries no trip amount, date or assignment — the only
  client-supplied financial figure is the optional prior qualifying spend, which is
  reported back as user-entered and unverified.
* **Read-only.** Nothing is written, so there is no idempotency key. The route still
  requires CSRF: it is a cookie-authenticated POST carrying a financial figure.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.exc import OperationalError

from accounts.models import ACCOUNTS_SCHEMA_VERSION, User
from accounts.store import AccountStore, UnknownRevisionError, UnknownTripError
from api.auth import current_user, get_store, now_utc, require_csrf
from api.saved_trips import AuthErrorResponse, RequestValidationErrorResponse
from api.wallet import get_kb
from core.db import KnowledgeBase
from welcome.catalog import OfferCatalog, shipped_offer_catalog
from welcome.models import WelcomeWindowReport
from welcome.status import StoredPlanUnreadableError, compute_welcome_status, parse_stored_plan

router = APIRouter(prefix="/account", tags=["welcome-status"])

WelcomeStatusErrorCode = Literal[
    "WALLET_ENTRY_NOT_FOUND",
    "TRIP_NOT_FOUND",
    "REVISION_NOT_FOUND",
    "REVISION_NOT_READABLE",
    "WELCOME_STATUS_UNAVAILABLE",
]


class WelcomeStatusApiErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: WelcomeStatusErrorCode
    message: str


class WelcomeStatusErrorResponse(BaseModel):
    """A typed welcome-status failure as it goes over the wire (wrapped in ``detail``)."""

    model_config = ConfigDict(extra="forbid")

    detail: WelcomeStatusApiErrorBody


_ERROR_MODELS: dict[int, Any] = {
    401: AuthErrorResponse,
    403: AuthErrorResponse,
    404: WelcomeStatusErrorResponse,
    409: WelcomeStatusErrorResponse,
    422: RequestValidationErrorResponse,
    503: WelcomeStatusErrorResponse,
}


def _error(status_code: int, code: WelcomeStatusErrorCode, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


class WelcomeStatusIn(BaseModel):
    """Which owned trip result to read, and the one optional figure only the user knows."""

    model_config = ConfigDict(extra="forbid")

    trip_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    revision: int = Field(ge=1, le=1_000_000)
    # Spend already made on this card inside the window, in the offer's currency.
    # Omitted/null means "I did not say" — it is never treated as zero.
    prior_qualifying_spend_minor: int | None = Field(default=None, ge=0, le=10**13)


def get_offer_catalog() -> OfferCatalog:
    """The shipped offer catalog. Tests and the demo override this dependency."""
    return shipped_offer_catalog()


def get_as_of() -> date:
    """Today's UTC date. Overridable so tests can pin the clock."""
    return now_utc().date()


@router.post(
    "/wallet/{entry_id}/welcome-status",
    response_model=WelcomeWindowReport,
    responses={
        code: {"model": model} for code, model in _ERROR_MODELS.items()
    },
)
def post_welcome_status(
    request: Request,
    entry_id: str,
    payload: WelcomeStatusIn,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
    kb: Annotated[KnowledgeBase, Depends(get_kb)],
    catalog: Annotated[OfferCatalog, Depends(get_offer_catalog)],
    as_of: Annotated[date, Depends(get_as_of)],
) -> WelcomeWindowReport:
    require_csrf(request)
    try:
        entries = store.wallet_entries(user.id)
        entry = next((e for e in entries if e.id == entry_id), None)
        if entry is None:
            raise _error(
                status.HTTP_404_NOT_FOUND, "WALLET_ENTRY_NOT_FOUND", "No such wallet entry."
            )
        try:
            stored = store.get_revision(user.id, payload.trip_id, payload.revision)
        except UnknownTripError as exc:
            raise _error(
                status.HTTP_404_NOT_FOUND, "TRIP_NOT_FOUND", "No such saved trip."
            ) from exc
        except UnknownRevisionError as exc:
            raise _error(
                status.HTTP_404_NOT_FOUND, "REVISION_NOT_FOUND", "No such revision."
            ) from exc
    except OperationalError as exc:
        # Lock contention or another operational fault. Never surface the driver
        # exception; the client should retry, not read a stack trace.
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "WELCOME_STATUS_UNAVAILABLE",
            "Welcome status is temporarily unavailable. Please retry.",
        ) from exc

    if stored.schema_version != ACCOUNTS_SCHEMA_VERSION:
        raise _error(
            status.HTTP_409_CONFLICT,
            "REVISION_NOT_READABLE",
            "This revision was stored under an older schema and is not read for welcome "
            "status.",
        )
    try:
        plan = parse_stored_plan(
            trip_id=payload.trip_id,
            revision=stored.revision,
            computed_at=stored.created_at.isoformat(),
            report_json=stored.report_json,
        )
    except StoredPlanUnreadableError as exc:
        raise _error(
            status.HTTP_409_CONFLICT,
            "REVISION_NOT_READABLE",
            "This revision has no readable computed assignments.",
        ) from exc

    return compute_welcome_status(
        wallet_entry_id=entry.id,
        card_id=entry.card_id,
        opened_on=entry.opened_on,
        kb=kb,
        selection=catalog.select_offer(entry.card_id, entry.opened_on),
        plan=plan,
        as_of=as_of,
        prior_spend_minor=payload.prior_qualifying_spend_minor,
        duplicate_card_entries=sum(1 for e in entries if e.card_id == entry.card_id) > 1,
    )
