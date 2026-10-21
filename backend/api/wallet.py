"""Authenticated, user-scoped wallet routes (spec 17 §3-4).

Separate from the read-only deterministic kernel routes (``/plan*``,
``/places/search``): this family mutates account state and therefore requires the
session cookie and CSRF on every state change.

Two invariants the handlers exist to protect:

* **Authority comes from the session, never the payload.** Every request model is
  ``extra="forbid"``, so a body carrying ``user_id`` is rejected outright rather
  than quietly ignored, and the store is always called with ``user.id``.
* **``UserWallet`` stays derived.** ``GET /account/wallet/projection`` folds the
  stored rows on read. There is deliberately no endpoint that writes it.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import OperationalError

from accounts.cards import (
    CardProductOut,
    UnknownCardProductError,
    assert_known_card_id,
    list_card_products,
)
from accounts.models import User, WalletEntry
from accounts.projection import build_user_wallet
from accounts.store import (
    UNSET,
    AccountStore,
    StaleWalletEntryError,
    WalletEntryNotFoundError,
    WalletIdempotencyConflictError,
)
from api.auth import current_user, get_store, now_utc, require_csrf
from core.db import DB_PATH, KnowledgeBase, load_kb
from core.models import UserWallet

router = APIRouter(prefix="/account", tags=["account"])

# Fields a client may patch. Anything else on the entry (id, user_id, card_id,
# added_at, version) is immutable through this API.
PATCHABLE = ("nickname", "last4", "statement_day", "opened_on", "points_balances")


def get_kb() -> KnowledgeBase:
    """Load the seeded knowledge base.

    Declared here rather than imported from ``api.main`` because ``main``
    imports this router, and importing back would be circular.
    """
    return load_kb(DB_PATH)


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message}
    )


def _not_found() -> HTTPException:
    """One fixed response for "missing" and "not yours" alike.

    Varying the body or status between the two would turn this endpoint into an
    oracle for another user's entry ids.
    """
    return _error(
        status.HTTP_404_NOT_FOUND,
        "wallet_entry_not_found",
        "No such wallet entry.",
    )


class WalletEntryOut(BaseModel):
    """Display-safe projection of one stored wallet row."""

    model_config = ConfigDict(extra="forbid")

    id: str
    card_id: str
    nickname: str
    last4: str | None
    statement_day: int | None
    opened_on: date | None
    points_balances: dict[str, int]
    added_at: str
    version: int

    @classmethod
    def of(cls, entry: WalletEntry) -> WalletEntryOut:
        return cls(
            id=entry.id,
            card_id=entry.card_id,
            nickname=entry.nickname,
            last4=entry.last4,
            statement_day=entry.statement_day,
            opened_on=entry.opened_on,
            points_balances=dict(entry.points_balances),
            added_at=entry.added_at.isoformat(),
            version=entry.version,
        )


class WalletEntryCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_id: str
    nickname: str
    last4: str | None = None
    statement_day: int | None = None
    opened_on: date | None = None
    points_balances: dict[str, int] | None = None
    client_event_id: str | None = None


class WalletEntryPatchIn(BaseModel):
    """Patch body. Omitted fields are left alone; explicit ``null`` clears one."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    nickname: str | None = None
    last4: str | None = None
    statement_day: int | None = None
    opened_on: date | None = None
    points_balances: dict[str, int] | None = None
    client_event_id: str | None = None


def _patch_kwargs(payload: WalletEntryPatchIn) -> dict[str, Any]:
    """Translate HTTP patch semantics into the store's UNSET sentinel.

    ``model_fields_set`` is what distinguishes "field absent from the JSON" from
    "field present and null" — without it every partial patch would null the
    fields the caller never mentioned.
    """
    provided = payload.model_fields_set
    return {
        name: getattr(payload, name) if name in provided else UNSET
        for name in PATCHABLE
    }


def _handle(call: Any) -> Any:
    """Run a store call, mapping its typed failures onto typed HTTP responses.

    Order matters: ``WalletEntryNotFoundError``, ``StaleWalletEntryError`` and
    ``WalletIdempotencyConflictError`` are all ``ValueError`` subclasses, so the
    broad ``ValueError`` arm has to come last or it would swallow them and
    report a 422 for a genuine 404 or 409.
    """
    try:
        return call()
    except WalletEntryNotFoundError as exc:
        raise _not_found() from exc
    except StaleWalletEntryError as exc:
        raise _error(
            status.HTTP_409_CONFLICT,
            "wallet_version_conflict",
            "This wallet entry changed since you loaded it. Reload and retry.",
        ) from exc
    except WalletIdempotencyConflictError as exc:
        raise _error(
            status.HTTP_409_CONFLICT,
            "wallet_event_conflict",
            "This client event id was already used for a different request.",
        ) from exc
    except UnknownCardProductError as exc:
        raise _error(
            422,
            "unknown_card_product",
            "That card product is not available.",
        ) from exc
    except OperationalError as exc:
        # Lock contention or another operational fault. Never surface the driver
        # exception; the client should retry, not read a stack trace.
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "wallet_unavailable",
            "The wallet is temporarily unavailable. Please retry.",
        ) from exc
    except ValueError as exc:
        raise _error(
            422,
            "wallet_entry_invalid",
            "That wallet entry is not valid.",
        ) from exc


@router.get("/card-products", response_model=list[CardProductOut])
def get_card_products(
    _user: Annotated[User, Depends(current_user)],
    kb: Annotated[KnowledgeBase, Depends(get_kb)],
) -> list[CardProductOut]:
    return list_card_products(kb)


@router.get("/wallet", response_model=list[WalletEntryOut])
def get_wallet(
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> list[WalletEntryOut]:
    return [WalletEntryOut.of(e) for e in store.wallet_entries(user.id)]


# Declared before /wallet/{entry_id} so the literal path wins the match.
@router.get("/wallet/projection", response_model=UserWallet)
def get_wallet_projection(
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> UserWallet:
    """Derive the kernel's ``UserWallet`` from stored rows. Never stored itself."""
    return build_user_wallet(store.wallet_entries(user.id))


@router.post("/wallet", response_model=WalletEntryOut, status_code=201)
def create_wallet_entry(
    request: Request,
    payload: WalletEntryCreateIn,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
    kb: Annotated[KnowledgeBase, Depends(get_kb)],
) -> WalletEntryOut:
    require_csrf(request)

    def call() -> WalletEntry:
        assert_known_card_id(kb, payload.card_id)
        return store.add_wallet_entry(
            user_id=user.id,
            card_id=payload.card_id,
            nickname=payload.nickname,
            now=now_utc(),
            last4=payload.last4,
            statement_day=payload.statement_day,
            opened_on=payload.opened_on,
            points_balances=payload.points_balances,
            client_event_id=payload.client_event_id,
        )

    return WalletEntryOut.of(_handle(call))


@router.patch("/wallet/{entry_id}", response_model=WalletEntryOut)
def patch_wallet_entry(
    request: Request,
    entry_id: str,
    payload: WalletEntryPatchIn,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> WalletEntryOut:
    require_csrf(request)

    def call() -> WalletEntry:
        return store.update_wallet_entry(
            user_id=user.id,
            entry_id=entry_id,
            expected_version=payload.expected_version,
            client_event_id=payload.client_event_id,
            now=now_utc(),
            **_patch_kwargs(payload),
        )

    return WalletEntryOut.of(_handle(call))


@router.delete("/wallet/{entry_id}", status_code=204)
def delete_wallet_entry(
    request: Request,
    entry_id: str,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
    client_event_id: str | None = None,
) -> Response:
    require_csrf(request)

    def call() -> bool:
        return store.remove_wallet_entry(
            user_id=user.id,
            entry_id=entry_id,
            client_event_id=client_event_id,
            now=now_utc(),
        )

    if not _handle(call):
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
