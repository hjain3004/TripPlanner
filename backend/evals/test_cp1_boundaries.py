from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


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
