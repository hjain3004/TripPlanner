import ast
from pathlib import Path

AGENTS = Path(__file__).parent.parent / "agents"
EXPECTED = {"intake", "planner", "critic", "explainer"}


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
    assert callers == EXPECTED, f"LLM call sites drifted: {callers}"
