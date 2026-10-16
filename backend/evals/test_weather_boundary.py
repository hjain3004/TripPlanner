"""G4 weather: structural boundary proofs.

These are architecture tests, not behaviour tests — they read source with
``ast`` and assert the walls the milestone promises:

* ``backend/core/`` (and everything outside the gateway) never imports the
  weather package, so weather cannot reach money arithmetic;
* the weather package never imports ``core``, ``api``, ``agents``,
  ``accounts``, ``planning``, ``evals`` or any travel/Gondola gateway code;
* the package contains no direct network or process access — the one module
  allowed to start a process (``stdio_transport``) does so only through the
  official ``mcp`` SDK, and nothing imports an HTTP/socket library;
* the HTTP contract and frontend know nothing about weather.
"""

from __future__ import annotations

import ast
import re
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

import gateway.weather as weather_pkg
from gateway.weather import contracts

BACKEND = Path(__file__).parent.parent
REPO = BACKEND.parent
WEATHER_DIR = Path(weather_pkg.__file__).parent
WEATHER_MODULES = sorted(WEATHER_DIR.glob("*.py"))

FORBIDDEN_NETWORK_AND_PROCESS = {
    "socket",
    "ssl",
    "select",
    "selectors",
    "urllib",
    "http",
    "httpx",
    "httpx2",
    "requests",
    "aiohttp",
    "websockets",
    "ftplib",
    "smtplib",
    "telnetlib",
    "subprocess",
    "multiprocessing",
    "ctypes",
    "importlib",
    "pickle",
    "marshal",
}
FORBIDDEN_INTERNAL_PREFIXES = (
    "core",
    "api",
    "agents",
    "accounts",
    "planning",
    "evals",
    "ingestion",
    "gateway.travel",
    "gateway.catalog",
    "gateway.reference",
    "gateway.evidence",
)


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def root(name: str) -> str:
    return name.split(".")[0]


# ``urllib.parse`` is pure string parsing (used to validate source URLs); every
# other ``urllib`` submodule can perform I/O and stays forbidden.
PURE_ALLOWED = {"urllib.parse"}


def is_forbidden_io(name: str) -> bool:
    return name not in PURE_ALLOWED and root(name) in FORBIDDEN_NETWORK_AND_PROCESS


def test_package_has_the_expected_modules() -> None:
    assert {p.name for p in WEATHER_MODULES} >= {
        "__init__.py",
        "adapter.py",
        "budget.py",
        "contracts.py",
        "errors.py",
        "normalize.py",
        "registry.py",
        "sanitize.py",
        "stdio_transport.py",
        "tool_policy.py",
        "transport.py",
        "upstream_pin.py",
    }


class TestNothingOutsideReachesWeather:
    @pytest.mark.parametrize(
        "area", ["core", "api", "agents", "accounts", "planning", "ingestion", "scripts"]
    )
    def test_no_other_backend_area_imports_weather(self, area: str) -> None:
        offenders = [
            str(p.relative_to(BACKEND))
            for p in (BACKEND / area).rglob("*.py")
            if any(
                n == "gateway.weather" or n.startswith("gateway.weather.") for n in imports_of(p)
            )
        ]
        assert offenders == []

    def test_other_gateway_packages_do_not_import_weather_either(self) -> None:
        offenders = []
        for sub in ("travel", "places", "catalog", "reference", "evidence"):
            for p in (BACKEND / "gateway" / sub).rglob("*.py"):
                if any(n.startswith("gateway.weather") for n in imports_of(p)):
                    offenders.append(str(p.relative_to(BACKEND)))
        assert offenders == []

    def test_core_still_imports_nothing_from_gateway(self) -> None:
        offenders = [
            str(p)
            for p in (BACKEND / "core").rglob("*.py")
            if any(n == "gateway" or n.startswith("gateway.") for n in imports_of(p))
        ]
        assert offenders == []

    def test_http_contract_and_frontend_know_nothing_about_weather(self) -> None:
        contract = (REPO / "contract" / "openapi.json").read_text().lower()
        for needle in ("open_meteo", "openmeteo", "open-meteo", "gateway.weather"):
            assert needle not in contract
        frontend_src = REPO / "frontend" / "src"
        if frontend_src.is_dir():
            for p in frontend_src.rglob("*"):
                if p.suffix in {".ts", ".tsx"} and "node_modules" not in p.parts:
                    text = p.read_text(errors="ignore").lower()
                    assert "open-meteo" not in text and "open_meteo" not in text, str(p)

    def test_weather_is_not_a_travel_inventory_domain(self) -> None:
        from typing import get_args

        from gateway.travel.registry import Domain

        assert "weather" not in get_args(Domain)


class TestWeatherImportsNothingInternalOrDangerous:
    @pytest.mark.parametrize("path", WEATHER_MODULES, ids=lambda p: p.name)
    def test_no_internal_or_forbidden_imports(self, path: Path) -> None:
        for name in imports_of(path):
            assert not is_forbidden_io(name), f"{path.name} imports {name}"
            assert not any(
                name == pref or name.startswith(pref + ".") for pref in FORBIDDEN_INTERNAL_PREFIXES
            ), f"{path.name} imports {name}"

    def test_only_the_stdio_transport_touches_mcp_or_anyio(self) -> None:
        users = {
            p.name for p in WEATHER_MODULES if {root(n) for n in imports_of(p)} & {"mcp", "anyio"}
        }
        assert users == {"stdio_transport.py"}

    def test_environment_is_read_only_by_the_registry(self) -> None:
        # ``os`` use is confined: the registry snapshots env once; the stdio
        # transport only needs path/exec checks and /dev/null.
        users = {p.name for p in WEATHER_MODULES if "os" in {root(n) for n in imports_of(p)}}
        assert users <= {"registry.py", "stdio_transport.py"}
        for p in WEATHER_MODULES:
            if p.name == "registry.py":
                continue
            assert "os.environ" not in p.read_text(), p.name
            assert "getenv" not in p.read_text(), p.name

    def test_sqlite_is_confined_to_the_budget_ledger(self) -> None:
        users = {p.name for p in WEATHER_MODULES if "sqlite3" in imports_of(p)}
        assert users == {"budget.py"}

    @pytest.mark.parametrize("path", WEATHER_MODULES, ids=lambda p: p.name)
    def test_no_dynamic_code_execution(self, path: Path) -> None:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"eval", "exec", "compile", "__import__"}, path.name

    @pytest.mark.parametrize("path", WEATHER_MODULES, ids=lambda p: p.name)
    def test_no_wall_clock_or_randomness_in_the_data_path(self, path: Path) -> None:
        text = path.read_text()
        assert "datetime.now" not in text and "datetime.utcnow" not in text, path.name
        assert "time.time()" not in text, path.name
        assert "import random" not in text and "import uuid" not in text, path.name

    def test_files_are_opened_only_where_expected(self) -> None:
        # Replay fixtures (transport), devnull + lockfile/manifest (stdio_transport).
        users = set()
        for p in WEATHER_MODULES:
            tree = ast.parse(p.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func
                    if (isinstance(fn, ast.Name) and fn.id == "open") or (
                        isinstance(fn, ast.Attribute)
                        and fn.attr in {"read_text", "read_bytes", "write_text", "write_bytes"}
                    ):
                        users.add(p.name)
        assert users <= {"transport.py", "stdio_transport.py"}
        for p in WEATHER_MODULES:
            tree = ast.parse(p.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in {"write_text", "write_bytes"}:
                    pytest.fail(f"{p.name} writes files")


class TestNoMoneyArithmetic:
    MONEY_WORDS = re.compile(
        r"(?i)(price|fare|fee|amount|currency|points|reward|cashback|minor|basis|micro)"
    )

    def _fields(self) -> list[tuple[str, str]]:
        found = []
        for name in dir(contracts):
            obj = getattr(contracts, name)
            fields = getattr(obj, "model_fields", None)
            if isinstance(fields, dict) and getattr(obj, "__module__", "") == contracts.__name__:
                found.extend((name, field) for field in fields)
        return found

    def test_no_evidence_or_request_field_is_money_shaped(self) -> None:
        fields = self._fields()
        assert len(fields) > 30
        assert [f for f in fields if self.MONEY_WORDS.search(f[1])] == []

    def test_weather_evidence_carries_no_integer_money_types(self) -> None:
        # Provider numbers are floats in physical units (°C, mm, km/h); there is
        # no Money/minor-unit type anywhere in the package namespace.
        for module in WEATHER_MODULES:
            text = module.read_text()
            assert "Money" not in text, module.name
            assert "_minor" not in text.replace("monthly_cost_minor", ""), module.name


class TestNoDirectNetworkOrProcessAtRuntime:
    def test_offline_flows_never_open_sockets_or_processes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio
        import subprocess

        from gateway.weather.adapter import OpenMeteoWeatherAdapter
        from gateway.weather.budget import WeatherCallBudget
        from gateway.weather.contracts import CurrentAndForecastRequest, WeatherLocation
        from gateway.weather.transport import FixtureWeatherTransport

        def boom(*args: object, **kwargs: object) -> None:
            raise AssertionError("weather offline path touched the network or spawned a process")

        for target in ("connect", "bind", "sendto"):
            monkeypatch.setattr(socket.socket, target, boom)
        monkeypatch.setattr(socket, "getaddrinfo", boom)
        monkeypatch.setattr(socket, "create_connection", boom)
        monkeypatch.setattr(subprocess, "Popen", boom)

        adapter = OpenMeteoWeatherAdapter(
            transport=FixtureWeatherTransport("singapore_ok"),
            budget=WeatherCallBudget(),
            plan_id="p",
            now=lambda: datetime(2026, 10, 14, 6, 0, tzinfo=UTC),
            enabled=True,
        )
        outcome = asyncio.run(
            adapter.get_context(
                CurrentAndForecastRequest(
                    location=WeatherLocation(latitude=1.35, longitude=103.82), forecast_days=7
                )
            )
        )
        assert outcome.status == "available"

    def test_default_registry_never_enables_anything_on_import(self) -> None:
        from gateway.weather.registry import get_default_weather_registry

        assert get_default_weather_registry({}).select(active_profile="student_noncommercial") == []
