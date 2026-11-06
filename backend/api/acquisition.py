"""Authenticated card-acquisition assessment for an unheld card (spec 18 Case B).

``POST /account/trips/{trip_id}/revisions/{revision}/acquisition-assessment`` answers:
for a saved trip revision owned by the user, what published welcome offers exist for unheld cards,
what is their conditional value on this trip, and do they satisfy every timing, minimum spend,
and positive net value gate?

Invariants protected:
- **Authority comes from the session cookie, never the payload.** The trip is resolved
  through owner-scoped store calls; request models are ``extra="forbid"``.
- **Wrong owner is indistinguishable from missing.** Foreign trips/revisions answer 404
  identically to nonexistent records.
- **Trip amounts are server-owned.** Read from the stored revision's computed optimizer result.
- **Held-card strategy is unchanged.** Built entirely from held cards, presented separately.
- **Payment timing must be explicit.** Travel dates are not payment dates.
- **Read-only.** Nothing is written to database or wallet; CSRF required.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import OperationalError

from accounts.models import ACCOUNTS_SCHEMA_VERSION, User
from accounts.store import AccountStore, UnknownRevisionError, UnknownTripError
from api.auth import current_user, get_store, require_csrf
from api.saved_trips import AuthErrorResponse, RequestValidationErrorResponse
from api.wallet import get_kb
from api.welcome import get_as_of, get_offer_catalog
from core.db import KnowledgeBase
from welcome.acquisition import compute_acquisition_assessment
from welcome.catalog import OfferCatalog
from welcome.models import AcquisitionAssessmentIn, AcquisitionAssessmentReport
from welcome.status import StoredPlanUnreadableError, parse_stored_plan

router = APIRouter(prefix="/account", tags=["card-acquisition"])

AcquisitionErrorCode = Literal[
    "TRIP_NOT_FOUND",
    "REVISION_NOT_FOUND",
    "REVISION_NOT_READABLE",
    "ACQUISITION_ASSESSMENT_UNAVAILABLE",
]


class AcquisitionApiErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: AcquisitionErrorCode
    message: str


class AcquisitionErrorResponse(BaseModel):
    """A typed card-acquisition assessment failure over the wire (wrapped in ``detail``)."""

    model_config = ConfigDict(extra="forbid")

    detail: AcquisitionApiErrorBody


_ERROR_MODELS: dict[int, Any] = {
    401: AuthErrorResponse,
    403: AuthErrorResponse,
    404: AcquisitionErrorResponse,
    409: AcquisitionErrorResponse,
    422: RequestValidationErrorResponse,
    503: AcquisitionErrorResponse,
}


def _error(status_code: int, code: AcquisitionErrorCode, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


@router.post(
    "/acquisition/trips/{trip_id}/revisions/{revision}",
    response_model=AcquisitionAssessmentReport,
    responses={
        code: {"model": model} for code, model in _ERROR_MODELS.items()
    },
)
def post_acquisition_assessment(
    request: Request,
    trip_id: str,
    revision: int,
    payload: AcquisitionAssessmentIn,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
    kb: Annotated[KnowledgeBase, Depends(get_kb)],
    catalog: Annotated[OfferCatalog, Depends(get_offer_catalog)],
    as_of: Annotated[date, Depends(get_as_of)],
) -> AcquisitionAssessmentReport:
    require_csrf(request)
    try:
        entries = store.wallet_entries(user.id)
        user_held_card_ids = {e.card_id for e in entries}
        try:
            stored = store.get_revision(user.id, trip_id, revision)
        except UnknownTripError as exc:
            raise _error(
                status.HTTP_404_NOT_FOUND, "TRIP_NOT_FOUND", "No such saved trip."
            ) from exc
        except UnknownRevisionError as exc:
            raise _error(
                status.HTTP_404_NOT_FOUND, "REVISION_NOT_FOUND", "No such revision."
            ) from exc
    except OperationalError as exc:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "ACQUISITION_ASSESSMENT_UNAVAILABLE",
            "Card acquisition assessment is temporarily unavailable. Please retry.",
        ) from exc

    if stored.schema_version != ACCOUNTS_SCHEMA_VERSION:
        raise _error(
            status.HTTP_409_CONFLICT,
            "REVISION_NOT_READABLE",
            "This revision was stored under an older schema and is not read for "
            "acquisition assessment.",
        )
    try:
        plan = parse_stored_plan(
            trip_id=trip_id,
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

    return compute_acquisition_assessment(
        trip_id=trip_id,
        revision=revision,
        as_of=as_of,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids=user_held_card_ids,
        payload=payload,
    )
