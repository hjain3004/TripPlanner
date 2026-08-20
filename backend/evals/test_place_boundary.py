from __future__ import annotations

import ast
from pathlib import Path


def test_places_gateway_ast_boundary() -> None:
    places_dir = Path("gateway/places")
    if not places_dir.exists():
        return

    forbidden_imports = {
        "requests",
        "httpx",
        "urllib.request",
        "socket",
        "mcp",
    }

    violations = []

    for filepath in places_dir.rglob("*.py"):
        try:
            tree = ast.parse(filepath.read_text(encoding="utf-8"), filename=str(filepath))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        base_module = alias.name.split(".")[0]
                        if base_module in forbidden_imports:
                            violations.append(f"{filepath}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        base_module = node.module.split(".")[0]
                        if base_module in forbidden_imports:
                            violations.append(f"{filepath}: from {node.module} import ...")
        except Exception as e:
            violations.append(f"{filepath}: failed to parse ({e})")

    assert not violations, "Found forbidden network/MCP imports in gateway/places:\n" + "\n".join(
        violations
    )
