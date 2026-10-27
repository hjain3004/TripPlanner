"""PDF process isolation against the REAL ``pdfplumber`` (not the synthetic double).

``test_fi1_pdf_isolation.py`` proves the process boundary with a deterministic stand-in for
the parser. This module proves the boundary also works with the actual library, and that the
isolated result equals what the previous in-process implementation produced.

It runs only where genuine ``pdfplumber`` is importable (the optional ``ingestion-local``
extra); everywhere else the whole module is SKIPPED with an explicit reason, never silently
passed. Run it with an interpreter that has the library, e.g. a task-owned virtualenv.

Fixtures: every PDF here is generated in-process from synthetic text by ``build_pdf`` (a
~30-line writer using the standard-14 Helvetica font), so no binary asset is stored, nothing
third-party is redistributed, and the bytes are deterministic. Limits of that choice are
stated in ``reports/pdf_real_library_compatibility.md``.

Nothing here proves exploit resistance or OS sandboxing: benign PDFs cannot.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import importlib.util
import io
import json
import os
import random
import subprocess
import sys
import threading
import time
import tomllib
import zlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from packaging.requirements import Requirement

from ingestion.artifacts import ContentAddressedStore
from ingestion.canonical import (
    ContentLimitError,
    UnsupportedContentError,
    _normalize_lines,
    acanonicalize_content,
    canonicalize_content,
)
from ingestion.contracts import EvidenceSpan, SnapshotBundle
from ingestion.evidence import EvidenceVerificationError, verify_evidence_span
from ingestion.pdf_isolation import (
    _BACKEND_ROOT,
    _CHILD_ENV,
    PdfPageOutOfRange,
    PdfProcessRunner,
    get_default_runner,
)

_SPEC = importlib.util.find_spec("pdfplumber")
pytestmark = pytest.mark.skipif(
    _SPEC is None,
    reason=(
        "real pdfplumber is not installed in this interpreter; run this module with an "
        "environment that has the declared optional dependency (pdfplumber>=0.11,<1)"
    ),
)

BACKEND = Path(__file__).parents[1]
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Synthetic PDF writer (deterministic, standard-14 font, optional Flate streams)
# --------------------------------------------------------------------------- #


def build_pdf(pages: list[list[str]], *, compress: bool = False) -> bytes:
    """A valid PDF whose page ``i`` shows ``pages[i]`` (one entry per line); ``[]`` is blank."""
    count = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(count))
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    for index, lines in enumerate(pages):
        content_ref = 5 + 2 * index
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_ref} 0 R >>"
            ).encode()
        )
        operations = ["BT", "/F1 12 Tf", "14 TL", "72 720 Td"] if lines else []
        for line in lines:
            raw = line.encode("cp1252")
            raw = raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
            operations.append("(" + raw.decode("latin-1") + ") Tj T*")
        if lines:
            operations.append("ET")
        stream = "\n".join(operations).encode("latin-1")
        header = b""
        if compress:
            stream = zlib.compress(stream)
            header = b" /Filter /FlateDecode"
        objects.append(
            b"<< /Length %d%s >>\nstream\n" % (len(stream), header) + stream + b"\nendstream"
        )
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


FEE = "Annual fee is INR 12,500."
UNICODE_LINES = [
    "Café crème — naïve üß €5",  # accents, em dash, euro
    "“quoted” ‘text’ • bullet",  # curly quotes, bullet
    "m² ™ ½ ª",  # NFKC-sensitive: superscript, TM, fraction, ordinal
]

FIXTURES: dict[str, bytes] = {
    "single_page": build_pdf([[FEE, "Forex markup is 2%."]]),
    "single_page_flate": build_pdf([[FEE, "Forex markup is 2%."]], compress=True),
    "three_pages": build_pdf([[FEE], ["Joining fee is INR 10,000."], ["Lounge access: 2 visits."]]),
    "blank_middle": build_pdf([[FEE], [], ["After a blank page."]]),
    "all_blank": build_pdf([[], []]),
    "unicode": build_pdf([UNICODE_LINES]),
    "paragraph": build_pdf([[f"Line {n}: " + "word " * 12 for n in range(40)]]),
    "spacing": build_pdf([["Two  spaces   and\ttabs", "", "", "after blank lines"]]),
}
GOOD = FIXTURES["three_pages"]


# --------------------------------------------------------------------------- #
# The previous in-process behaviour, copied verbatim from base commit c925d98
# (ingestion/canonical.py::canonicalize_pdf and ingestion/evidence.py page check).
# This is the reference "real-library extraction/normalization" the isolation must equal.
# --------------------------------------------------------------------------- #


def legacy_canonicalize_pdf(data: bytes, *, max_chars: int, max_pages: int) -> str:
    try:
        pdfplumber = __import__("pdfplumber")
    except ImportError as error:  # pragma: no cover - module is skipped without the library
        raise UnsupportedContentError(
            "PDF canonicalization requires the optional ingestion-local extra"
        ) from error
    try:
        with pdfplumber.open(io.BytesIO(data)) as document:
            if len(document.pages) > max_pages:
                raise ContentLimitError(f"PDF exceeds {max_pages} page limit")
            text = "\n".join(page.extract_text() or "" for page in document.pages)
    except ContentLimitError:
        raise
    except Exception as error:
        raise UnsupportedContentError("PDF could not be parsed safely") from error
    return _normalize_lines(text, max_chars=max_chars)


def legacy_page_text(data: bytes, page_number: int) -> str | None:
    """The old evidence check's page text, or ``None`` when the page is out of range."""
    pdfplumber = __import__("pdfplumber")
    with pdfplumber.open(io.BytesIO(data)) as document:
        if page_number > len(document.pages):
            return None
        text: str = document.pages[page_number - 1].extract_text() or ""
        return text


Outcome = tuple[str, str]


def outcome(call: Callable[[], str]) -> Outcome:
    try:
        return "ok", call()
    except Exception as error:
        return type(error).__name__, str(error)


def gone(pid: int, wait: float = 3.0) -> bool:
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)  # a zombie still answers, so this also proves the child was reaped
        except ProcessLookupError:
            return True
        time.sleep(0.02)
    return False


_RUNNERS: list[PdfProcessRunner] = []


@pytest.fixture
def runner() -> PdfProcessRunner:
    """A runner with production defaults and NO search path: nothing can shadow the library."""
    fresh = PdfProcessRunner(max_concurrent=2)
    _RUNNERS.append(fresh)
    return fresh


@pytest.fixture(autouse=True)
def no_worker_survives() -> Any:
    yield
    for each in _RUNNERS:
        assert each.live_count() == 0
        assert all(gone(pid) for pid in each.spawned_pids), "a PDF worker outlived its request"


def isolated(
    mode: str, runner: PdfProcessRunner, data: bytes, *, max_chars: int = 20_000, max_pages: int = 8
) -> Outcome:
    if mode == "sync":
        return outcome(
            lambda: runner.canonicalize(
                data, max_chars=max_chars, max_pages=max_pages, timeout_seconds=60
            )
        )
    return outcome(
        lambda: asyncio.run(
            runner.acanonicalize(data, max_chars=max_chars, max_pages=max_pages, timeout_seconds=60)
        )
    )


# --------------------------------------------------------------------------- #
# 1. The worker really uses the installed library
# --------------------------------------------------------------------------- #


def _diagnostic_child(code: str) -> subprocess.CompletedProcess[str]:
    """The production child configuration (same interpreter, ``-I``, rebuilt environment)
    running a read-only import diagnostic instead of the worker."""
    return subprocess.run(
        [sys.executable, "-I", "-c", code, str(_BACKEND_ROOT)],
        env=_CHILD_ENV,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )


def test_the_child_resolves_the_installed_library_and_never_the_synthetic_double() -> None:
    probe = (
        "import sys, json; sys.path.append(sys.argv[1]); "
        "import pdfplumber, pdfminer, PIL, pypdfium2; import ingestion.pdf_worker as w; "
        "print(json.dumps({'pdfplumber': pdfplumber.__file__, 'version': pdfplumber.__version__,"
        " 'pdfminer': pdfminer.__file__, 'worker': w.__file__,"
        " 'has_double_path': any('pdf_double' in p for p in sys.path),"
        " 'env_keys': sorted(__import__('os').environ)}))"
    )
    facts = json.loads(_diagnostic_child(probe).stdout)
    assert "site-packages" in facts["pdfplumber"] and "pdf_double" not in facts["pdfplumber"]
    assert "site-packages" in facts["pdfminer"]
    assert facts["worker"].endswith("ingestion/pdf_worker.py")
    assert facts["has_double_path"] is False
    assert facts["version"] == importlib.metadata.version("pdfplumber")
    print("RESOLVED", json.dumps(facts, indent=1))


def test_the_production_runner_has_no_search_path_seam_enabled(runner: PdfProcessRunner) -> None:
    assert "--search-path" not in runner.worker_command
    assert not any("pdf_double" in part for part in runner.worker_command)
    assert runner.worker_command[:3] == [sys.executable, "-I", "-c"]


def test_only_the_real_library_can_read_a_real_pdf_and_the_double_format_is_rejected(
    runner: PdfProcessRunner,
) -> None:
    assert isolated("sync", runner, FIXTURES["single_page"]) == (
        "ok",
        f"{FEE}\nForex markup is 2%.",
    )
    # The synthetic double would accept this; the real library must refuse it.
    kind, message = isolated("sync", runner, b"%PDF-DOUBLE\nok\nhello")
    assert (kind, message) == ("UnsupportedContentError", "PDF could not be parsed safely")


def test_the_installed_version_satisfies_the_declared_requirement() -> None:
    declared = tomllib.loads((BACKEND / "pyproject.toml").read_text())
    requirement = next(
        Requirement(item)
        for item in declared["project"]["optional-dependencies"]["ingestion-local"]
        if item.lower().startswith("pdfplumber")
    )
    installed = importlib.metadata.version("pdfplumber")
    assert installed in requirement.specifier, f"{installed} violates {requirement}"


def test_the_child_environment_is_rebuilt_and_does_not_inherit_the_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PDF_VERIFY_CANARY", "do-not-leak")
    monkeypatch.setenv("PYTHONPATH", "/nonexistent-shadow")
    facts = _diagnostic_child(
        "import os, sys; print(sorted(os.environ)); print(sys.flags.isolated)"
    )
    keys, isolated_flag = facts.stdout.strip().splitlines()
    assert "PDF_VERIFY_CANARY" not in keys and "PYTHONPATH" not in keys
    assert isolated_flag == "1"


# --------------------------------------------------------------------------- #
# 2. Canonicalization parity with the previous real-library behaviour
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_isolated_canonicalization_equals_the_previous_in_process_result(
    runner: PdfProcessRunner, name: str
) -> None:
    data = FIXTURES[name]
    reference = outcome(lambda: legacy_canonicalize_pdf(data, max_chars=20_000, max_pages=8))
    assert reference[0] == "ok", f"the reference failed on {name}: {reference}"
    assert isolated("sync", runner, data) == reference


@pytest.mark.parametrize("name", ["single_page", "blank_middle", "unicode"])
def test_the_async_path_gives_the_same_real_library_result(
    runner: PdfProcessRunner, name: str
) -> None:
    data = FIXTURES[name]
    assert isolated("async", runner, data) == outcome(
        lambda: legacy_canonicalize_pdf(data, max_chars=20_000, max_pages=8)
    )


def test_expected_text_for_the_plain_documents(runner: PdfProcessRunner) -> None:
    """Parity alone could hide two identically-wrong results, so pin the real values too."""
    assert isolated("sync", runner, FIXTURES["three_pages"]) == (
        "ok",
        f"{FEE}\nJoining fee is INR 10,000.\nLounge access: 2 visits.",
    )
    assert isolated("sync", runner, FIXTURES["blank_middle"]) == (
        "ok",
        f"{FEE}\nAfter a blank page.",
    )
    assert isolated("sync", runner, FIXTURES["all_blank"]) == ("ok", "")
    assert isolated("sync", runner, FIXTURES["single_page_flate"]) == (
        "ok",
        f"{FEE}\nForex markup is 2%.",
    )


def test_unicode_survives_and_nfkc_is_applied_exactly_as_before(runner: PdfProcessRunner) -> None:
    kind, text = isolated("sync", runner, FIXTURES["unicode"])
    assert kind == "ok"
    assert "Café crème — naïve üß €5" in text  # kept as-is
    assert "“quoted”" in text
    # NFKC: m² -> m2, ™ -> TM, ½ -> 1⁄2 (fraction slash), ª -> a
    assert "m2 TM 1⁄2 a" in text
    assert text == legacy_canonicalize_pdf(FIXTURES["unicode"], max_chars=20_000, max_pages=8)


# --------------------------------------------------------------------------- #
# 3. Page-specific evidence verification
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["three_pages", "blank_middle", "unicode", "single_page_flate"])
def test_page_text_equals_the_previous_per_page_extraction(
    runner: PdfProcessRunner, name: str
) -> None:
    data = FIXTURES[name]
    pages = len(legacy_page_pages(data))
    for number in range(1, pages + 1):
        assert runner.page_text(data, page_number=number, timeout_seconds=60) == legacy_page_text(
            data, number
        )
    with pytest.raises(PdfPageOutOfRange):
        runner.page_text(data, page_number=pages + 1, timeout_seconds=60)
    assert legacy_page_text(data, pages + 1) is None


def legacy_page_pages(data: bytes) -> list[str]:
    pdfplumber = __import__("pdfplumber")
    with pdfplumber.open(io.BytesIO(data)) as document:
        return [page.extract_text() or "" for page in document.pages]


def _snapshot(tmp_path: Path, raw: bytes) -> tuple[SnapshotBundle, ContentAddressedStore]:
    canonical = legacy_canonicalize_pdf(raw, max_chars=20_000, max_pages=8)
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    raw_ref = artifacts.put(raw, media_type="application/pdf")
    normalized = artifacts.put(canonical.encode(), media_type="text/plain")
    snapshot = SnapshotBundle(
        snapshot_id="snapshot:real-pdf:1",
        target_id="watch:real-pdf",
        captured_at=NOW,
        raw_artifact=raw_ref,
        normalized_artifact=normalized,
        raw_sha256=raw_ref.sha256,
        normalized_sha256=normalized.sha256,
        canonical_markdown=canonical,
    )
    return snapshot, artifacts


def _span(snapshot: SnapshotBundle, quote: str, page: int) -> EvidenceSpan:
    start = snapshot.canonical_markdown.index(quote)
    return EvidenceSpan(
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.normalized_sha256,
        quote=quote,
        normalized_start=start,
        normalized_end=start + len(quote),
        field_path="annual_fee_minor",
        verification="exact",
        artifact_kind="pdf",
        page_number=page,
    )


def test_evidence_verification_with_the_real_library_is_page_specific(tmp_path: Path) -> None:
    snapshot, artifacts = _snapshot(tmp_path, GOOD)
    default = get_default_runner()  # the production runner, nothing injected
    _RUNNERS.append(default)
    verify_evidence_span(_span(snapshot, FEE, 1), snapshot=snapshot, artifacts=artifacts)
    verify_evidence_span(
        _span(snapshot, "Joining fee is INR 10,000.", 2), snapshot=snapshot, artifacts=artifacts
    )
    verify_evidence_span(
        _span(snapshot, "Lounge access: 2 visits.", 3), snapshot=snapshot, artifacts=artifacts
    )
    with pytest.raises(EvidenceVerificationError, match="not present on the cited page"):
        verify_evidence_span(
            _span(snapshot, "Joining fee is INR 10,000.", 1), snapshot=snapshot, artifacts=artifacts
        )
    with pytest.raises(EvidenceVerificationError, match="outside the artifact"):
        verify_evidence_span(_span(snapshot, FEE, 9), snapshot=snapshot, artifacts=artifacts)


def test_evidence_on_a_blank_page_is_rejected_not_accepted(tmp_path: Path) -> None:
    snapshot, artifacts = _snapshot(tmp_path, FIXTURES["blank_middle"])
    with pytest.raises(EvidenceVerificationError, match="not present on the cited page"):
        verify_evidence_span(_span(snapshot, FEE, 2), snapshot=snapshot, artifacts=artifacts)


def test_evidence_verification_of_a_corrupt_pdf_fails_closed(tmp_path: Path) -> None:
    snapshot, artifacts = _snapshot(tmp_path, GOOD)
    broken = artifacts.put(GOOD[: len(GOOD) // 3], media_type="application/pdf")
    snapshot = snapshot.model_copy(update={"raw_artifact": broken, "raw_sha256": broken.sha256})
    with pytest.raises(EvidenceVerificationError, match="could not be verified"):
        verify_evidence_span(_span(snapshot, FEE, 1), snapshot=snapshot, artifacts=artifacts)


# --------------------------------------------------------------------------- #
# 4. Limits
# --------------------------------------------------------------------------- #


def test_page_limit_matches_the_previous_behaviour(runner: PdfProcessRunner) -> None:
    expected = outcome(lambda: legacy_canonicalize_pdf(GOOD, max_chars=20_000, max_pages=2))
    assert expected == ("ContentLimitError", "PDF exceeds 2 page limit")
    assert isolated("sync", runner, GOOD, max_pages=2) == expected
    assert isolated("sync", runner, GOOD, max_pages=3)[0] == "ok"  # exactly at the limit


def test_character_limit_boundary_matches_the_previous_behaviour(runner: PdfProcessRunner) -> None:
    exact = len(legacy_canonicalize_pdf(GOOD, max_chars=20_000, max_pages=8))
    assert isolated("sync", runner, GOOD, max_chars=exact)[0] == "ok"
    over = isolated("sync", runner, GOOD, max_chars=exact - 1)
    assert over == outcome(lambda: legacy_canonicalize_pdf(GOOD, max_chars=exact - 1, max_pages=8))
    assert over[0] == "ContentLimitError"


def test_a_realistically_sized_page_passes_the_reply_bound(runner: PdfProcessRunner) -> None:
    data = FIXTURES["paragraph"]
    reference = legacy_canonicalize_pdf(data, max_chars=20_000, max_pages=8)
    assert len(reference) > 2500  # 40 lines of ~70 characters: well beyond the toy cases
    assert isolated("sync", runner, data) == ("ok", reference)
    # Tightest legal bound: the reply limit derives from max_chars, so equal must still fit.
    assert isolated("sync", runner, data, max_chars=len(reference)) == ("ok", reference)


def test_the_input_byte_bound_applies_to_a_real_pdf_before_any_process_starts() -> None:
    small = PdfProcessRunner(max_concurrent=1, max_input_bytes=len(GOOD) - 1)
    _RUNNERS.append(small)
    kind, _ = outcome(
        lambda: small.canonicalize(GOOD, max_chars=1000, max_pages=5, timeout_seconds=10)
    )
    assert kind == "ContentLimitError" and small.spawned_pids == []
    exact = PdfProcessRunner(max_concurrent=1, max_input_bytes=len(GOOD))
    _RUNNERS.append(exact)
    assert exact.canonicalize(GOOD, max_chars=1000, max_pages=5, timeout_seconds=60).startswith(FEE)


def test_canonicalize_content_entry_point_uses_the_real_library_end_to_end() -> None:
    _RUNNERS.append(get_default_runner())
    text = canonicalize_content(GOOD, media_type="application/pdf", max_chars=500, max_pages=3)
    assert text == f"{FEE}\nJoining fee is INR 10,000.\nLounge access: 2 visits."
    assert asyncio.run(
        acanonicalize_content(
            FIXTURES["single_page"], media_type="application/pdf", max_chars=500, max_pages=1
        )
    ).startswith(FEE)


# --------------------------------------------------------------------------- #
# 5. Corrupt and truncated PDFs: typed failures, identical to the previous behaviour
# --------------------------------------------------------------------------- #

_RNG = random.Random(20261027)
CORRUPT: dict[str, bytes] = {
    "empty": b"",
    "plain_text": b"this is not a pdf at all",
    "header_only": b"%PDF-1.4\n",
    "header_and_eof": b"%PDF-1.4\n%%EOF\n",
    "random_bytes": _RNG.randbytes(2048),
    "html_in_disguise": b"<html><body>%PDF-1.4</body></html>",
    "truncated_10pct": GOOD[: len(GOOD) // 10],
    "truncated_33pct": GOOD[: len(GOOD) // 3],
    "truncated_90pct": GOOD[: len(GOOD) * 9 // 10],
    "xref_cut_off": GOOD[: GOOD.rindex(b"xref")],
    "last_20_bytes_removed": GOOD[:-20],
    "header_smashed": b"%PDX-1.4" + GOOD[8:],
    "middle_zeroed": GOOD[:200] + b"\x00" * 200 + GOOD[400:],
    "garbage_appended": GOOD + _RNG.randbytes(512),
}


@pytest.mark.parametrize("name", sorted(CORRUPT))
def test_corrupt_input_matches_the_previous_behaviour_and_is_always_typed(
    runner: PdfProcessRunner, name: str
) -> None:
    data = CORRUPT[name]
    reference = outcome(lambda: legacy_canonicalize_pdf(data, max_chars=20_000, max_pages=8))
    result = isolated("sync", runner, data)
    assert result == reference, f"{name}: isolated {result!r} != previous {reference!r}"
    assert result[0] in {"ok", "UnsupportedContentError", "ContentLimitError"}


def test_the_corrupt_corpus_genuinely_exercises_the_failure_path(runner: PdfProcessRunner) -> None:
    """Guards against a vacuous pass where the real library tolerated every damaged input."""
    results = [isolated("sync", runner, data) for data in CORRUPT.values()]
    failures = [r for r in results if r[0] == "UnsupportedContentError"]
    assert len(failures) >= 6, results
    assert all(r == ("UnsupportedContentError", "PDF could not be parsed safely") for r in failures)


@pytest.mark.parametrize("name", ["random_bytes", "truncated_33pct"])
def test_corrupt_input_is_typed_on_the_async_path_too(runner: PdfProcessRunner, name: str) -> None:
    assert isolated("async", runner, CORRUPT[name]) == outcome(
        lambda: legacy_canonicalize_pdf(CORRUPT[name], max_chars=20_000, max_pages=8)
    )


# --------------------------------------------------------------------------- #
# 6. Isolation keeps working with the real library loaded
# --------------------------------------------------------------------------- #


def test_a_deadline_during_real_library_start_up_kills_and_reaps_the_worker() -> None:
    impatient = PdfProcessRunner(max_concurrent=1)
    _RUNNERS.append(impatient)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        impatient.canonicalize(GOOD, max_chars=1000, max_pages=5, timeout_seconds=0.02)
    assert time.monotonic() - started < 3.0
    assert impatient.live_count() == 0 and all(gone(pid) for pid in impatient.spawned_pids)
    assert impatient.canonicalize(GOOD, max_chars=1000, max_pages=5, timeout_seconds=60)  # reusable


def test_cancelling_a_real_parse_kills_the_worker(runner: PdfProcessRunner) -> None:
    async def scenario() -> None:
        task = asyncio.ensure_future(
            runner.acanonicalize(GOOD, max_chars=1000, max_pages=5, timeout_seconds=60)
        )
        for _ in range(400):
            if runner.live_count() == 1:
                break
            await asyncio.sleep(0.005)
        assert runner.live_count() == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert runner.live_count() == 0


def test_concurrent_real_parses_respect_the_child_bound_and_stay_correct(
    runner: PdfProcessRunner,
) -> None:
    peak = 0
    stop = threading.Event()

    def sample() -> None:
        nonlocal peak
        while not stop.is_set():
            peak = max(peak, runner.live_count())
            time.sleep(0.002)

    watcher = threading.Thread(target=sample)
    watcher.start()
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(
                pool.map(
                    lambda _: runner.canonicalize(
                        FIXTURES["single_page"], max_chars=500, max_pages=1, timeout_seconds=120
                    ),
                    range(6),
                )
            )
    finally:
        stop.set()
        watcher.join()
    assert results == [f"{FEE}\nForex markup is 2%."] * 6
    assert 1 <= peak <= 2 and len(runner.spawned_pids) == 6


def test_failed_and_successful_runs_leave_no_workers_behind(runner: PdfProcessRunner) -> None:
    for data in (GOOD, CORRUPT["random_bytes"], FIXTURES["blank_middle"], CORRUPT["empty"]):
        isolated("sync", runner, data)
    isolated("async", runner, GOOD)
    assert runner.live_count() == 0
    assert len(runner.spawned_pids) == 5 and all(gone(pid) for pid in runner.spawned_pids)
