import ast
from pathlib import Path

AGENTS = Path(__file__).parent.parent / "agents"
EXPECTED = {"intake", "planner", "critic", "explainer"}
TARGET_PLATFORM_CALLERS = {"interview_assistant", "post_plan_interpreter"}


def test_exactly_four_llm_call_sites_exist() -> None:
    """CLAUDE.md non-negotiable 5, Tier F. search_places is a TOOL inside the
    planner call site, never a fifth call site."""
    callers = set()
    for path in sorted(AGENTS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = getattr(fn, "attr", None) or getattr(fn, "id", None)
                if name in ("complete_json", "complete_with_repair"):
                    if path.stem != "llm":
                        callers.add(path.stem)
    # The approved conversational design §4.2 specifies CP3 outside the
    # frozen Kernel graph. It does not authorize any other additional caller.
    assert callers == EXPECTED | TARGET_PLATFORM_CALLERS, f"LLM call sites drifted: {callers}"


def test_kernel_import_graph_cannot_reach_the_interview_assistant() -> None:
    """Transitive imports from the kernel pipeline retain its four call sites."""
    pending = [AGENTS / "pipeline.py"]
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited or not path.is_file():
            continue
        visited.add(path)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = (
                    [f"agents.{item.name}" for item in node.names]
                    if node.module == "agents"
                    else [node.module]
                )
            for module in modules:
                if module.startswith("agents."):
                    pending.append(
                        AGENTS / (module.removeprefix("agents.").replace(".", "/") + ".py")
                    )
    reached = {path.name for path in visited}
    assert "interview_assistant.py" not in reached
    assert "post_plan_interpreter.py" not in reached
    callers: set[str] = set()
    for path in visited:
        if path.stem == "llm":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name in {"complete_json", "complete_with_repair"}:
                    callers.add(path.stem)
    assert callers == EXPECTED
