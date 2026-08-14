"""Production code must not contain placeholders.

Phase I5 shipped `agents/discovery/controller.py` with this:

    # Simulated model loop. In reality, we would call the LLM, and the LLM
    # would call tools.
    if hasattr(llm, "execute_planner"):
        done = llm.execute_planner(spec, registry, state)
    else:
        done = True

`execute_planner` was defined nowhere, so in production the branch was never
taken and the discovery loop exited immediately having done nothing. The whole
test suite was green, because the tests injected a mock that supplied the
method. The phase was reported complete.

The itinerary design section 15 already forbids this in prose: "The
implementation plans must not contain 'wire later,' placeholder components or
skipped validation." Prose did not stop it. This test does.

Scope is production packages only. Tests may legitimately stub, simulate and
monkeypatch — that is what tests are for.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).parent.parent
PRODUCTION_PACKAGES = ("core", "agents", "api", "gateway")

# Phrases that mean "this is not really implemented". Matched case-insensitively
# against source text. Deliberately prose-level: a stub announces itself in a
# comment long before it announces itself in behavior.
#
# Kept high-signal on purpose. The first run of this guard also flagged
# `TODO` (three logged SQLite-ceiling notes in gateway/evidence/store.py, all
# recorded in DEVIATIONS.md), `XXX` (matching the literal `overture:xxx` in an
# example comment), and `for now` (an accurate M1 docstring in
# core/optimizer/normalize.py describing behavior that genuinely exists).
# Those are known debt and honest prose, not unimplemented code. A guard that
# cries wolf gets deleted, so they are out — what remains all means "this does
# not actually do the thing".
STUB_MARKERS = (
    r"in reality",
    r"simulated\b",
    r"we would call",
    r"would call the",
    r"the real system would",
    r"wire[ -]later",
    r"wired later",
    r"placeholder",
    r"not implemented yet",
    r"NotImplementedError",
)

_MARKER_RE = re.compile("|".join(STUB_MARKERS), re.IGNORECASE)


def _production_sources() -> list[Path]:
    files: list[Path] = []
    for package in PRODUCTION_PACKAGES:
        files.extend(sorted((BACKEND / package).rglob("*.py")))
    return [p for p in files if "__pycache__" not in p.parts]


# Known gaps, each with a DEVIATIONS.md row. This list must only ever shrink —
# adding to it is how a guard dies. Keyed by "<relative path>:<line>" is too
# brittle across edits, so it is keyed by file and the guard reports the line.
KNOWN_GAPS: set[str] = set()


def test_production_code_contains_no_stub_markers() -> None:
    offenders: list[str] = []
    for path in _production_sources():
        rel = path.relative_to(BACKEND)
        if str(rel) in KNOWN_GAPS:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = _MARKER_RE.search(line)
            if match:
                offenders.append(f"{rel}:{lineno}: {match.group(0)!r} in {line.strip()!r}")

    assert offenders == [], (
        "placeholder markers found in production code — implement it or remove the "
        "code, do not ship an announced stub:\n  " + "\n  ".join(offenders)
    )


def test_the_guard_actually_scans_something() -> None:
    """Anti-vacuity: a guard that scans zero files passes forever.

    Three phases of this project shipped tests that were green because their
    fixtures never reached the interesting branch. This asserts the scan has
    real input.
    """
    sources = _production_sources()
    assert len(sources) > 30, f"expected the production packages, found {len(sources)} files"
    assert any(p.name == "planner.py" for p in sources)
    assert any("discovery" in p.parts for p in sources)


def test_the_known_gap_list_is_not_a_dumping_ground() -> None:
    """An allowlist that grows is a guard that has been switched off.

    If this fails because someone added an entry, the right move is almost
    always to implement the thing, not to raise the number.
    """
    assert len(KNOWN_GAPS) <= 1, f"known-gap list grew to {len(KNOWN_GAPS)}: {sorted(KNOWN_GAPS)}"
