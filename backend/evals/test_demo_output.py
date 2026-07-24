"""Demo command reproduces the committed §8 fixture byte-for-byte (Gate M1)."""

from __future__ import annotations

from pathlib import Path

from core.optimizer import optimize
from core.optimizer.__main__ import render
from core.optimizer.demo_data import demo_kb, demo_trip, demo_wallet

_FIXTURE = Path(__file__).parent / "golden" / "demo_expected_output.txt"


def test_demo_output_matches_committed_fixture() -> None:
    produced = render(optimize(demo_trip(), demo_wallet(), demo_kb()))
    expected = _FIXTURE.read_text()
    assert produced == expected


def test_demo_output_render_is_stable() -> None:
    r1 = render(optimize(demo_trip(), demo_wallet(), demo_kb()))
    r2 = render(optimize(demo_trip(), demo_wallet(), demo_kb()))
    assert r1 == r2
