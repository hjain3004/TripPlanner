import ast
from pathlib import Path


def test_core_does_not_import_gateway_or_agents() -> None:
    core_dir = Path(__file__).parent.parent / "core"
    for py_file in core_dir.rglob("*.py"):
        with open(py_file, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("gateway"), f"{py_file.name} imports gateway"
                    assert not alias.name.startswith("agents"), f"{py_file.name} imports agents"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert not node.module.startswith("gateway"), f"{py_file.name} imports gateway"
                    assert not node.module.startswith("agents"), f"{py_file.name} imports agents"


def test_gateway_evidence_has_no_network_or_secrets() -> None:
    evidence_dir = Path(__file__).parent.parent / "gateway" / "evidence"
    banned = {"requests", "httpx", "urllib.request", "socket", "mcp"}

    for py_file in evidence_dir.rglob("*.py"):
        with open(py_file, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    base_mod = alias.name.split(".")[0]
                    assert base_mod not in banned, (
                        f"{py_file.name} imports banned module {base_mod}"
                    )
                    # check urllib.request specifically
                    assert not alias.name.startswith("urllib.request"), (
                        f"{py_file.name} imports urllib.request"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    base_mod = node.module.split(".")[0]
                    assert base_mod not in banned, (
                        f"{py_file.name} imports banned module {base_mod}"
                    )
                    assert not node.module.startswith("urllib.request"), (
                        f"{py_file.name} imports urllib.request"
                    )
                    if node.module == "urllib":
                        assert not any(alias.name == "request" for alias in node.names), (
                            f"{py_file.name} imports urllib.request"
                        )
