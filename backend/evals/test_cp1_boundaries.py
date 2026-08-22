from __future__ import annotations

import ast
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from accounts.models import FORBIDDEN_FIELD_NAMES
from accounts.store import AccountStore
from core.models import UserWallet
from planning.contracts import TravelerHomeContext
from planning.policy import start_interview
from planning.repository import PlanningSessionRepository

BACKEND = Path(__file__).resolve().parents[1]

NOW = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)


def _first_party_imports(path: Path) -> set[str]:
    names: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _offenders(package: str, forbidden: set[str]) -> list[str]:
    root = BACKEND / package
    return [
        str(path.relative_to(BACKEND))
        for path in sorted(root.rglob("*.py"))
        if forbidden & _first_party_imports(path)
    ]


def test_planning_package_exists() -> None:
    assert (BACKEND / "planning" / "__init__.py").is_file()


def test_core_never_imports_planning_or_accounts() -> None:
    assert _offenders("core", {"planning", "accounts"}) == []


def test_accounts_never_imports_planning_agents_or_api() -> None:
    assert _offenders("accounts", {"planning", "agents", "api"}) == []


def test_planning_is_pure_domain_code() -> None:
    assert _offenders("planning", {"agents", "api", "gateway"}) == []


# --------------------------------------------------------------------------- #
# Task 7: non-vacuous architecture/privacy guards future milestones cannot    #
# accidentally bypass.                                                       #
# --------------------------------------------------------------------------- #


def test_planning_package_has_no_network_llm_provider_or_sql_imports() -> None:
    forbidden = {"agents", "api", "gateway", "httpx", "requests", "mcp", "sqlalchemy"}
    offenders = _offenders("planning", forbidden)
    assert offenders == [], offenders


def _changed_files_against_merge_base() -> list[str]:
    base = os.environ.get("CP1_MERGE_BASE")
    if not base:
        pytest.skip("CP1_MERGE_BASE is required for committed-diff assertions")
    completed = subprocess.run(
        ["git", "diff", "--name-only", base, "HEAD"],
        cwd=BACKEND.parent,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.splitlines()


def test_cp1_changes_no_public_contract_or_frozen_goldens() -> None:
    changed = _changed_files_against_merge_base()
    assert "contract/openapi.json" not in changed
    assert not any(path.startswith("backend/evals/golden/") for path in changed)


def test_stored_session_contains_no_forbidden_key_names(tmp_path: Path) -> None:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    store.create_user(email="traveler@example.com", now=NOW, user_id="u1")
    repository = PlanningSessionRepository(store)
    session = start_interview(
        user_id="u1",
        session_id="ps1",
        home=TravelerHomeContext(
            home_country="IN", home_currency="INR", default_origin="DEL"
        ),
        wallet=UserWallet(card_ids=["hdfc-infinia"]),
        profile_defaults=None,
        now=NOW,
        expires_at=NOW + timedelta(days=30),
    )
    repository.create(session)
    snapshot = store.get_planning_session_snapshot(user_id="u1", session_id="ps1")
    assert snapshot is not None
    lowered = snapshot.payload_json.casefold()
    for forbidden in FORBIDDEN_FIELD_NAMES:
        assert f'"{forbidden.casefold()}"' not in lowered


# -- Forbidden non-deterministic clock/id/randomness calls in planning/ ----- #

_FORBIDDEN_CALL_NAMES: frozenset[str] = frozenset(
    {"datetime.now", "date.today", "uuid4"}
)
_FORBIDDEN_CALL_PREFIXES: tuple[str, ...] = ("random.", "secrets.")


def _dotted_call_name(node: ast.expr) -> str | None:
    """Resolve a ``Name``/``Attribute`` call target to a dotted string.

    ``datetime.now`` resolves to ``"datetime.now"``; a bare ``uuid4`` name
    resolves to ``"uuid4"``; anything else (a call on an arbitrary
    expression, a subscript, ...) resolves to ``None`` and is ignored -- this
    is a static AST check, not a type checker, and false negatives on
    unresolvable call targets are acceptable because every actual call site
    in this codebase is a plain dotted or bare name.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_call_name(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def _nondeterministic_call_offenders(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dotted = _dotted_call_name(node.func)
        if dotted is None:
            continue
        if dotted in _FORBIDDEN_CALL_NAMES or dotted.startswith(_FORBIDDEN_CALL_PREFIXES):
            offenders.append(f"{path.relative_to(BACKEND)}:{node.lineno}: {dotted}(...)")
    return offenders


def test_planning_never_calls_a_nondeterministic_clock_or_id_source() -> None:
    """``datetime.now``/``date.today``/``uuid4``/``random.*``/``secrets.*`` calls
    in ``planning/`` production code would violate injected determinism: every
    timestamp and id must arrive from the caller, never be generated inline.

    This is an AST check, not a text/regex scan, specifically because
    ``planning/policy.py``'s own module docstring narrates these exact
    forbidden call shapes in prose (documenting that they are absent) -- a
    naive substring search would false-positive on that honest docstring.
    """
    root = BACKEND / "planning"
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        offenders.extend(_nondeterministic_call_offenders(path))
    assert offenders == [], offenders
