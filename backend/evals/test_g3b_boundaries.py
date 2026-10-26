"""Isolation and activation boundaries for the OpenBnB adapter.

These tests are the machine-checked version of "offline development only": nothing selects
the adapter by default, nothing in the package can reach a network or start a process,
no robots override or unvetted launcher exists in code, and no production module imports it.
"""

from __future__ import annotations

import ast
import asyncio
import re
import socket
import subprocess
from pathlib import Path

import pytest

from evals.g3b_support import NOW, request
from gateway.travel.adapters.openbnb.adapter import OpenBnBAdapter
from gateway.travel.adapters.openbnb.budget import OpenBnBCallBudget
from gateway.travel.adapters.openbnb.fixture_transport import FixtureOpenBnBTransport
from gateway.travel.adapters.openbnb.registry import (
    ENABLE_ENV,
    KILL_SWITCH_ENV,
    build_openbnb_adapter,
    build_openbnb_registry_entry,
    openbnb_enabled,
)
from gateway.travel.registry import TravelProviderRegistry, get_default_travel_registry

BACKEND = Path(__file__).parent.parent
PACKAGE = BACKEND / "gateway" / "travel" / "adapters" / "openbnb"
SOURCES = sorted(PACKAGE.glob("*.py"))


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


# --------------------------------------------------------------------------- #
# Activation
# --------------------------------------------------------------------------- #


def test_the_default_registry_has_no_openbnb_entry_whatever_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENABLE_ENV, "1")
    registry = get_default_travel_registry()
    assert all(entry.provider_id != "openbnb" for entry in registry.entries)
    for domain in ("hotel", "flight"):
        eligible = registry.select_providers(
            active_profile="student_noncommercial",
            domain=domain,
            country="SG",  # type: ignore[arg-type]
        )
        assert "openbnb" not in [e.provider_id for e in eligible]


def test_the_entry_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENABLE_ENV, raising=False)
    monkeypatch.delenv(KILL_SWITCH_ENV, raising=False)
    assert build_openbnb_registry_entry().enabled is False
    assert openbnb_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_only_an_explicit_truthy_flag_enables_it(value: str) -> None:
    assert build_openbnb_registry_entry({ENABLE_ENV: value}).enabled is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "enabled", "2"])
def test_anything_else_leaves_it_disabled(value: str) -> None:
    assert build_openbnb_registry_entry({ENABLE_ENV: value}).enabled is False


@pytest.mark.parametrize("kill", ["1", "true", "yes", "on"])
def test_the_kill_switch_wins_over_the_enable_flag(kill: str) -> None:
    env = {ENABLE_ENV: "1", KILL_SWITCH_ENV: kill}
    assert build_openbnb_registry_entry(env).enabled is False
    adapter = build_openbnb_adapter(
        transport=None, budget=OpenBnBCallBudget(), plan_id="p", now=lambda: NOW, env=env
    )
    assert adapter._enabled is False


def test_the_adapter_factory_enables_only_through_the_flag_pair() -> None:
    off = build_openbnb_adapter(
        transport=None, budget=OpenBnBCallBudget(), plan_id="p", now=lambda: NOW, env={}
    )
    on = build_openbnb_adapter(
        transport=None,
        budget=OpenBnBCallBudget(),
        plan_id="p",
        now=lambda: NOW,
        env={ENABLE_ENV: "1"},
    )
    assert (off._enabled, on._enabled) == (False, True)


def test_the_entry_shape_matches_the_reviewed_activation_profile() -> None:
    entry = build_openbnb_registry_entry({ENABLE_ENV: "1"})
    assert entry.allowed_profiles == {"student_noncommercial"}
    assert entry.domains == {"hotel"}
    assert entry.source_method == "scraper_wrapper"
    assert entry.live_data is False
    assert entry.monthly_cost_minor == 0
    registry = TravelProviderRegistry(entries=[*get_default_travel_registry().entries, entry])
    hotel = [
        e.provider_id
        for e in registry.select_providers(
            active_profile="student_noncommercial", domain="hotel", country="SG"
        )
    ]
    assert hotel == ["openbnb", "sample_travel_adapter"]  # sample stays the last resort
    commercial = registry.select_providers(
        active_profile="commercial_production", domain="hotel", country="SG"
    )
    assert "openbnb" not in [e.provider_id for e in commercial]
    assert "openbnb" not in [
        e.provider_id
        for e in registry.select_providers(
            active_profile="student_noncommercial", domain="flight", country="SG"
        )
    ]


def test_the_package_init_registers_nothing() -> None:
    assert (PACKAGE / "__init__.py").read_text().strip() == ""


# --------------------------------------------------------------------------- #
# Isolation
# --------------------------------------------------------------------------- #


def test_no_production_module_imports_the_openbnb_package() -> None:
    offenders: list[str] = []
    for path in BACKEND.rglob("*.py"):
        relative = path.relative_to(BACKEND)
        if (
            relative.parts[0] in {"evals", ".venv", "catalogs"}
            or PACKAGE in path.parents
            or ".venv" in relative.parts
        ):
            continue
        if any("openbnb" in name for name in _imports(path)):
            offenders.append(str(relative))
    assert offenders == []


def test_the_package_never_imports_a_network_or_process_library() -> None:
    forbidden = {
        "socket",
        "subprocess",
        "urllib",
        "http",
        "httpx",
        "httpx2",
        "requests",
        "aiohttp",
        "ssl",
        "ftplib",
        "smtplib",
        "webbrowser",
        "shutil",
        "pickle",
        "marshal",
    }
    for path in SOURCES:
        # urllib.parse is pure string handling (link validation); the rest of urllib is I/O.
        used = {name.split(".")[0] for name in _imports(path) if name != "urllib.parse"}
        assert not (used & forbidden), f"{path.name} imports {used & forbidden}"


def test_the_mcp_sdk_is_imported_only_lazily_and_only_by_the_live_transport() -> None:
    for path in SOURCES:
        tree = ast.parse(path.read_text())
        module_level = [
            node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        eager = [
            ast.unparse(node)
            for node in module_level
            if "mcp" in ast.unparse(node).split(" ")[1].split(".")[0:1]
            and ast.unparse(node).split(" ")[1].split(".")[0] == "mcp"
        ]
        assert eager == [], f"{path.name} imports the MCP SDK at module load"
        if path.name != "mcp_client.py":
            assert not any(n.split(".")[0] == "mcp" for n in _imports(path))


def test_code_strings_contain_no_robots_override_launcher_or_evasion_vocabulary() -> None:
    banned = (
        "ignorerobots",
        "ignore-robots",
        "ignore_robots",
        "npx",
        "proxy",
        "captcha",
        "user-agent",
        "stealth",
        "rotate",
    )
    for path in SOURCES:
        tree = ast.parse(path.read_text())
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                lowered = node.value.casefold()
                hits = [word for word in banned if word in lowered]
                if path.name == "mcp_client.py" and node.value == "IGNORE_ROBOTS_TXT":
                    hits = []  # the launch pins this env var to "false" (asserted elsewhere)
                # The policy module must *name* the forbidden key to refuse it.
                if path.name == "tool_policy.py":
                    hits = [h for h in hits if h not in {"ignorerobots"}]
                assert not hits, f"{path.name}: {node.value!r} mentions {hits}"


def test_the_only_sqlite_use_is_the_call_counter_and_nothing_writes_files() -> None:
    for path in SOURCES:
        names = _imports(path)
        text = path.read_text()
        if path.name != "budget.py":
            assert "sqlite3" not in names, path.name
        for token in ("write_text", "write_bytes", ".mkdir(", "tempfile", "os.makedirs"):
            assert token not in text, f"{path.name} uses {token}"
        # A real ``open(`` call (not a longer name such as ``_assert_open(``).
        assert re.search(r"(?<![\w.])open\(", text) is None, f"{path.name} calls open()"


def test_no_secret_markers_in_the_package() -> None:
    for path in [*SOURCES, *PACKAGE.glob("fixtures/*.json")]:
        text = path.read_text()
        for marker in ("sk_live", "api_key=", "Authorization: Bearer ", "secret="):
            assert marker not in text, f"{path.name} contains {marker}"


# --------------------------------------------------------------------------- #
# Behaviour under a hostile environment
# --------------------------------------------------------------------------- #


def test_a_full_offline_flow_touches_no_socket_no_process_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("OpenBnB offline flow must not reach the network or a process")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden)
    monkeypatch.chdir(tmp_path)

    transport = FixtureOpenBnBTransport(
        {"airbnb_search": "search_success", "airbnb_listing_details": "details_success"},
        now=lambda: NOW,
    )
    adapter = OpenBnBAdapter(
        transport=transport, budget=OpenBnBCallBudget(), plan_id="p", now=lambda: NOW, enabled=True
    )
    quotes = asyncio.run(adapter.search_hotels(request()))
    assert quotes
    asyncio.run(adapter.enrich_with_coordinates(quotes[0], request()))
    assert list(tmp_path.iterdir()) == []  # no raw cache, no ledger file, nothing retained
