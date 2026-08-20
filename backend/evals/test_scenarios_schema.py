from pathlib import Path

import yaml


def test_scenarios_yaml_loads_and_is_valid() -> None:
    path = Path(__file__).parent / "scenarios.yaml"
    assert path.exists()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "scenarios" in data
    scenarios = data["scenarios"]
    assert len(scenarios) >= 12

    seen_ids = set()
    for s in scenarios:
        assert "id" in s
        assert "name" in s
        assert "request" in s
        assert "expect" in s
        assert s["expect"] in {"ok", "needs_clarification", "capability_absent", "error"}
        assert s["id"] not in seen_ids, f"Duplicate scenario id: {s['id']}"
        seen_ids.add(s["id"])
