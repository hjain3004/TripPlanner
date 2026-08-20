from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).parent.parent


def test_fetch_module_is_never_imported_outside_itself_and_tests() -> None:
    offenders = []
    for pkg in ("core", "agents", "api"):
        for path in (BACKEND / pkg).rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                elif isinstance(node, ast.Import):
                    names.extend(a.name for a in node.names)
                if any("gateway.reference.fx.fetch" in n for n in names):
                    offenders.append(str(path))
    assert offenders == []


def test_fetch_targets_only_the_allowlisted_host() -> None:
    from gateway.reference.fx.fetch import ALLOWED_HOST, FX_URL

    assert ALLOWED_HOST == "api.frankfurter.dev"
    assert FX_URL.startswith(f"https://{ALLOWED_HOST}/")


def test_fetch_rejects_a_url_pointed_at_a_different_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """The allowlist check must be a real assertion, not a vacuous
    constant-against-itself comparison -- prove it actually rejects a
    mismatched host rather than merely restating the constant."""
    import gateway.reference.fx.fetch as fetch_module

    monkeypatch.setattr(fetch_module, "FX_URL", "https://evil.example/v2/rates")
    with pytest.raises(RuntimeError):
        fetch_module.fetch(Path("/tmp/should-not-be-written.json"))
