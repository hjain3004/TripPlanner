"""Determinism gate (spec 02 §9.11, 04 §1): identical input ⇒ byte-identical output."""

from __future__ import annotations

from pathlib import Path

from core.optimizer import optimize
from core.optimizer.demo_data import demo_kb, demo_trip, demo_wallet
from evals._harness import golden_files, load_case


def test_determinism_demo_serialized_bytes_identical() -> None:
    first = optimize(demo_trip(), demo_wallet(), demo_kb()).model_dump_json()
    second = optimize(demo_trip(), demo_wallet(), demo_kb()).model_dump_json()
    assert first == second
    assert first.encode() == second.encode()


def test_determinism_every_golden_stable() -> None:
    for path in golden_files():
        a = load_case(path)["result"].model_dump_json()
        b = load_case(path)["result"].model_dump_json()
        assert a == b, f"non-deterministic output for {Path(path).stem}"
