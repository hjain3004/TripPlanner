import ast
from pathlib import Path

CATALOG = Path(__file__).parent.parent / "gateway" / "catalog"
NETWORK = {"requests", "httpx", "urllib", "socket", "aiohttp", "http", "ftplib"}
UPPER = {"agents", "api"}


def _imports(root: Path, banned: set[str]) -> list[str]:
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] in banned:
                        offenders.append(f"{path.name}: import {a.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in banned:
                    offenders.append(f"{path.name}: from {node.module}")
    return offenders


def test_catalog_package_contains_no_network_imports() -> None:
    assert _imports(CATALOG, NETWORK) == []


def test_catalog_does_not_import_agents_or_api() -> None:
    assert _imports(CATALOG, UPPER) == []
