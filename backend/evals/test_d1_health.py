"""D1: liveness and readiness. Readiness reflects local persistence only."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import accounts.db as accounts_db
import api.health as health
import core.db as core_db
from api.main import app
from api.runtime_config import ConfigError


@pytest.fixture
def stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    kb = tmp_path / "tripwise.sqlite"
    core_db.seed_database(core_db.SEEDS_DIR, kb)
    monkeypatch.setattr(core_db, "DB_PATH", kb)
    monkeypatch.setattr(accounts_db, "ACCOUNTS_DB_PATH", tmp_path / "accounts.sqlite")
    return tmp_path


def test_liveness_never_touches_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_db, "DB_PATH", Path("/nonexistent/kb.sqlite"))
    monkeypatch.setattr(accounts_db, "ACCOUNTS_DB_PATH", Path("/nonexistent/a.sqlite"))
    response = TestClient(app).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_ready_when_persistence_opens(stores: Path) -> None:
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"data_dir": "ok", "accounts_db": "ok", "knowledge_base": "ok"}


def test_ready_labels_the_deployment_as_sample_mode_with_no_live_provider(stores: Path) -> None:
    body = TestClient(app).get("/health/ready").json()
    assert body["provider_mode"] == "sample"
    assert body["live_providers_enabled"] == []


def test_not_ready_when_the_knowledge_base_is_missing(
    stores: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core_db, "DB_PATH", stores / "absent.sqlite")
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["knowledge_base"] == "failed"
    assert body["checks"]["accounts_db"] == "ok"


def test_not_ready_when_the_accounts_database_cannot_be_opened(
    stores: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(accounts_db, "ACCOUNTS_DB_PATH", Path("/nonexistent/dir/accounts.sqlite"))
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["accounts_db"] == "failed"


def test_failure_bodies_leak_no_paths_or_exception_text(
    stores: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(accounts_db, "ACCOUNTS_DB_PATH", Path("/nonexistent/secret-dir/a.sqlite"))
    monkeypatch.setattr(core_db, "DB_PATH", Path("/nonexistent/secret-dir/kb.sqlite"))
    text = TestClient(app).get("/health/ready").text
    assert "secret-dir" not in text and "nonexistent" not in text
    assert "Error" not in text and "Traceback" not in text


def test_provider_problems_never_make_the_sample_app_unready(
    stores: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> object:
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(health, "_enabled_live_providers", boom)
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 200
    assert response.json()["live_providers_enabled"] == "unknown"


def test_enabled_live_provider_flags_are_reported_not_hidden(
    stores: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIPWISE_GONDOLA_LIVE_ENABLED", "1")
    monkeypatch.delenv("TRIPWISE_GONDOLA_KILL_SWITCH", raising=False)
    body = TestClient(app).get("/health/ready").json()
    assert "gondola" in body["live_providers_enabled"]


def test_health_routes_stay_out_of_the_public_contract() -> None:
    paths = app.openapi()["paths"]
    assert "/health/live" not in paths and "/health/ready" not in paths


def test_existing_health_endpoint_is_unchanged() -> None:
    assert TestClient(app).get("/health").json() == {"status": "ok"}


class TestStartupValidationInLifespan:
    def test_invalid_production_config_stops_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TRIPWISE_ENV", "production")
        monkeypatch.delenv("TRIPWISE_DATA_DIR", raising=False)
        with pytest.raises(ConfigError), TestClient(app):
            pass

    def test_valid_config_initialises_the_accounts_schema_through_the_real_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db = tmp_path / "accounts.sqlite"
        monkeypatch.setattr(accounts_db, "ACCOUNTS_DB_PATH", db)
        monkeypatch.setenv("TRIPWISE_ENV", "production")
        monkeypatch.setenv("TRIPWISE_DATA_DIR", str(tmp_path))
        with TestClient(app):
            assert db.exists()


def test_open_meteo_flag_is_reported_without_importing_the_weather_package(
    stores: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIPWISE_OPEN_METEO_ENABLED", "1")
    monkeypatch.delenv("TRIPWISE_OPEN_METEO_KILL_SWITCH", raising=False)
    body = TestClient(app).get("/health/ready").json()
    assert "open_meteo" in body["live_providers_enabled"]
    monkeypatch.setenv("TRIPWISE_OPEN_METEO_KILL_SWITCH", "1")
    assert "open_meteo" not in TestClient(app).get("/health/ready").json()["live_providers_enabled"]
