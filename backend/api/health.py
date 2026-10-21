"""Liveness and readiness for process supervisors (container health checks).

* ``/health/live``  - the process is up. Touches nothing.
* ``/health/ready`` - local persistence can be opened: the data directory is
  writable, the accounts database opens through its real schema path, and the seeded
  knowledge base loads. Provider state is *reported* but can never make the
  sample-mode application unready.

Both are infrastructure endpoints and are intentionally kept out of the public
OpenAPI contract. Failure bodies name checks only - never paths or exception text.
"""

from __future__ import annotations

import tempfile
from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import text

import accounts.db as accounts_db
import core.db as core_db
from api.runtime_config import flagged_live_providers
from core.runtime_paths import data_dir

router = APIRouter(tags=["infrastructure"], include_in_schema=False)


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "alive"}


def _check_data_dir() -> bool:
    root = data_dir() or accounts_db.ACCOUNTS_DB_PATH.parent
    try:
        with tempfile.TemporaryFile(dir=root):
            return True
    except OSError:
        return False


def _check_accounts_db() -> bool:
    try:
        engine = accounts_db.create_accounts_engine(accounts_db.ACCOUNTS_DB_PATH)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1 FROM users LIMIT 1"))
            return True
        finally:
            engine.dispose()
    except Exception:
        return False


def _check_knowledge_base() -> bool:
    try:
        path = core_db.DB_PATH
        return path.exists() and bool(core_db.load_kb(path).cards)
    except Exception:
        return False


def _enabled_live_providers() -> list[str]:
    from gateway.places.registry import get_default_place_registry
    from gateway.travel.registry import get_default_travel_registry

    enabled = {
        e.provider_id for e in get_default_travel_registry().entries if e.enabled and e.live_data
    }
    enabled |= {
        e.provider_id
        for e in get_default_place_registry().entries
        if e.enabled and e.provider_id == "tripadvisor_terra"
    }
    # Open-Meteo is reported from its enable flag: the API layer must not import
    # gateway.weather (a G4 boundary enforced by test_weather_boundary).
    enabled |= set(flagged_live_providers())
    return sorted(enabled)


@router.get("/health/ready")
def ready(response: Response) -> dict[str, Any]:
    checks = {
        "data_dir": "ok" if _check_data_dir() else "failed",
        "accounts_db": "ok" if _check_accounts_db() else "failed",
        "knowledge_base": "ok" if _check_knowledge_base() else "failed",
    }
    ok = all(v == "ok" for v in checks.values())
    try:
        live_providers: list[str] | str = _enabled_live_providers()
    except Exception:
        live_providers = "unknown"  # reported, never fatal
    if not ok:
        response.status_code = 503
    return {
        "status": "ready" if ok else "not_ready",
        "checks": checks,
        "provider_mode": "sample",
        "live_providers_enabled": live_providers,
    }
