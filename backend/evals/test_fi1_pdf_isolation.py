"""FI1 PDF parsing runs in a killable child process.

Every test here drives a REAL child process through a deterministic synthetic ``pdfplumber``
double (``ingestion/fixtures/pdf_double``). Nothing asserts only that ``terminate()`` was
called: each hang test proves, from outside, that the child is dead, reaped, and that its
late side effects never happened.
"""

from __future__ import annotations

import ast
import asyncio
import os
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ingestion.artifacts import ContentAddressedStore
from ingestion.canonical import (
    ContentLimitError,
    UnsupportedContentError,
    _normalize_lines,
    acanonicalize_content,
    canonicalize_content,
)
from ingestion.contracts import (
    EvidenceSpan,
    FetchRequest,
    PageKind,
    SnapshotBundle,
    SourcePolicyRecord,
)
from ingestion.evidence import EvidenceVerificationError, verify_evidence_span
from ingestion.fetch import Crawl4AIBackend, ManualUploadBackend
from ingestion.pdf_isolation import PdfPageOutOfRange, PdfProcessRunner, use_runner
from ingestion.preflight import RobotsRules

BACKEND = Path(__file__).parents[1]
STUB = BACKEND / "ingestion" / "fixtures" / "pdf_double"
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def doc(directive: str, *pages: str) -> bytes:
    return b"%PDF-DOUBLE\n" + directive.encode() + b"\n" + "\f".join(pages).encode()


def gone(pid: int, wait: float = 3.0) -> bool:
    """True once ``pid`` no longer exists at all. A zombie still answers ``kill(pid, 0)``,
    so this also proves the child was reaped."""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def runner() -> PdfProcessRunner:
    return PdfProcessRunner(max_concurrent=2, search_paths=[STUB])


@pytest.fixture(params=["sync", "async"])
def mode(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def canon(
    mode: str,
    runner: PdfProcessRunner,
    data: bytes,
    *,
    max_chars: int = 10_000,
    max_pages: int = 5,
    timeout: float = 5.0,
) -> str:
    if mode == "sync":
        return runner.canonicalize(
            data, max_chars=max_chars, max_pages=max_pages, timeout_seconds=timeout
        )
    return asyncio.run(
        runner.acanonicalize(
            data, max_chars=max_chars, max_pages=max_pages, timeout_seconds=timeout
        )
    )


def page(
    mode: str, runner: PdfProcessRunner, data: bytes, number: int, timeout: float = 5.0
) -> str:
    if mode == "sync":
        return runner.page_text(data, page_number=number, timeout_seconds=timeout)
    return asyncio.run(runner.apage_text(data, page_number=number, timeout_seconds=timeout))


# --------------------------------------------------------------------------- #
# Behaviour is unchanged: same text, same typed errors
# --------------------------------------------------------------------------- #


def test_success_matches_the_in_process_normalization(mode: str, runner: PdfProcessRunner) -> None:
    pages = ["Annual  fee is\n\n\n\nINR 12,500.  ", "ﬁrst page ligature", ""]
    result = canon(mode, runner, doc("ok", *pages))
    assert result == _normalize_lines("\n".join(pages), max_chars=10_000)
    assert "first page ligature" in result  # NFKC applied exactly as before
    assert runner.live_count() == 0


def test_empty_text_is_an_empty_document_not_an_error(mode: str, runner: PdfProcessRunner) -> None:
    assert canon(mode, runner, doc("ok", "", "")) == ""


def test_the_page_limit_is_the_same_typed_error(mode: str, runner: PdfProcessRunner) -> None:
    with pytest.raises(ContentLimitError, match="PDF exceeds 2 page limit"):
        canon(mode, runner, doc("pages 3"), max_pages=2)


def test_the_normalized_character_limit_is_the_same_typed_error(
    mode: str, runner: PdfProcessRunner
) -> None:
    with pytest.raises(ContentLimitError, match="exceeds 10 characters"):
        canon(mode, runner, doc("ok", "y" * 50), max_chars=10)


def test_a_parser_exception_is_the_same_generic_unsupported_error(
    mode: str, runner: PdfProcessRunner
) -> None:
    with pytest.raises(UnsupportedContentError, match="PDF could not be parsed safely"):
        canon(mode, runner, doc("raise", "x"))
    with pytest.raises(UnsupportedContentError, match="PDF could not be parsed safely"):
        canon(mode, runner, b"not a pdf at all")


def test_a_missing_optional_dependency_is_the_same_typed_error(mode: str) -> None:
    bare = PdfProcessRunner(max_concurrent=1)  # no double on the path; pdfplumber is optional
    with pytest.raises(UnsupportedContentError, match="optional ingestion-local extra"):
        canon(mode, bare, doc("ok", "x"))
    assert bare.live_count() == 0


@pytest.mark.parametrize("directive", ["crash", "segv"])
def test_a_crashing_parser_is_unsupported_content_and_is_reaped(
    mode: str, runner: PdfProcessRunner, directive: str
) -> None:
    with pytest.raises(UnsupportedContentError, match="PDF could not be parsed safely"):
        canon(mode, runner, doc(directive, "x"))
    assert runner.live_count() == 0
    assert all(gone(pid) for pid in runner.spawned_pids)


def test_page_text_returns_the_cited_page_and_types_out_of_range(
    mode: str, runner: PdfProcessRunner
) -> None:
    data = doc("ok", "first", "second")
    assert page(mode, runner, data, 2) == "second"
    with pytest.raises(PdfPageOutOfRange):
        page(mode, runner, data, 3)
    with pytest.raises(UnsupportedContentError):
        page(mode, runner, doc("raise", "x"), 1)


# --------------------------------------------------------------------------- #
# A hung parser really dies
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("directive", ["hang-sleep", "hang-busy", "hang-ignore-term"])
def test_a_hung_parser_is_killed_and_reaped_at_the_deadline(
    mode: str, runner: PdfProcessRunner, directive: str
) -> None:
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        canon(mode, runner, doc(directive, "x"), timeout=0.6)
    assert time.monotonic() - started < 3.0
    (pid,) = runner.spawned_pids
    assert gone(pid), "the parser process is still alive or an unreaped zombie"
    assert runner.live_count() == 0


def test_the_whole_process_group_dies_including_a_grandchild(
    mode: str, runner: PdfProcessRunner, tmp_path: Path
) -> None:
    pidfile = tmp_path / "grandchild.pid"
    with pytest.raises(TimeoutError):
        canon(mode, runner, doc(f"grandchild {pidfile}", "x"), timeout=1.5)
    grandchild = int(pidfile.read_text())
    assert gone(grandchild), "a process the parser spawned survived the timeout"
    assert all(gone(pid) for pid in runner.spawned_pids)


def test_a_helper_left_holding_the_pipe_neither_delays_the_reply_nor_survives(
    mode: str, runner: PdfProcessRunner, tmp_path: Path
) -> None:
    pidfile = tmp_path / "helper.pid"
    started = time.monotonic()
    with pytest.raises(UnsupportedContentError, match="PDF could not be parsed safely"):
        canon(mode, runner, doc(f"grandchild-then-raise {pidfile}", "x"), timeout=20.0)
    assert time.monotonic() - started < 5.0  # the reply line ended the wait, not EOF
    assert gone(int(pidfile.read_text())), "a helper the parser spawned outlived the request"
    assert all(gone(pid) for pid in runner.spawned_pids)


def test_a_timed_out_parser_never_performs_its_late_side_effect(
    mode: str, runner: PdfProcessRunner, tmp_path: Path
) -> None:
    marker = tmp_path / "late.txt"
    with pytest.raises(TimeoutError):
        canon(mode, runner, doc(f"late-write 1.0 {marker}", "x"), timeout=0.4)
    time.sleep(1.5)
    assert not marker.exists()


def test_caller_cancellation_kills_the_child(runner: PdfProcessRunner, tmp_path: Path) -> None:
    pidfile = tmp_path / "grandchild.pid"

    async def scenario() -> None:
        task = asyncio.ensure_future(
            runner.acanonicalize(
                doc(f"grandchild {pidfile}", "x"), max_chars=100, max_pages=1, timeout_seconds=30
            )
        )
        for _ in range(200):  # wait until the parser is demonstrably running
            if pidfile.exists() and runner.spawned_pids:
                break
            await asyncio.sleep(0.02)
        assert runner.live_count() == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert runner.live_count() == 0
    assert all(gone(pid) for pid in runner.spawned_pids)
    assert gone(int(pidfile.read_text()))


def test_a_cancelled_slow_parser_never_writes_late(
    runner: PdfProcessRunner, tmp_path: Path
) -> None:
    marker = tmp_path / "late.txt"

    async def scenario() -> None:
        task = asyncio.ensure_future(
            runner.acanonicalize(
                doc(f"late-write 1.0 {marker}", "x"), max_chars=100, max_pages=1, timeout_seconds=30
            )
        )
        await asyncio.sleep(0.4)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    time.sleep(1.5)
    assert not marker.exists()


# --------------------------------------------------------------------------- #
# Bounded input, output, time and concurrency
# --------------------------------------------------------------------------- #


def test_oversized_input_is_refused_before_any_process_exists(mode: str) -> None:
    small = PdfProcessRunner(max_concurrent=1, search_paths=[STUB], max_input_bytes=64)
    with pytest.raises(ContentLimitError):
        canon(mode, small, doc("ok", "x" * 200))
    assert small.spawned_pids == []


def _script(tmp_path: Path, name: str, body: str) -> list[str]:
    path = tmp_path / name
    path.write_text(body)
    return [sys.executable, "-I", str(path)]


def test_a_worker_that_floods_stdout_is_cut_off_and_killed(mode: str, tmp_path: Path) -> None:
    flood = _script(
        tmp_path,
        "flood.py",
        "import sys\nchunk = b'x' * 65536\nwhile True:\n    sys.stdout.buffer.write(chunk)\n"
        "    sys.stdout.buffer.flush()\n",
    )
    rogue = PdfProcessRunner(max_concurrent=1, worker_command=flood)
    with pytest.raises(UnsupportedContentError, match="PDF could not be parsed safely"):
        canon(mode, rogue, doc("ok", "x"), max_chars=100, timeout=5.0)
    assert rogue.live_count() == 0 and all(gone(pid) for pid in rogue.spawned_pids)


@pytest.mark.parametrize(
    "reply",
    [
        b"",
        b"not json\n",
        b"[1,2]\n",
        b'{"ok": true}\n',
        b'{"ok": true, "text": 5}\n',
        b'{"ok": false, "kind": "mystery"}\n',
    ],
)
def test_a_malformed_worker_reply_is_unsupported_not_trusted(
    mode: str, tmp_path: Path, reply: bytes
) -> None:
    command = _script(
        tmp_path,
        "reply.py",
        f"import sys\nsys.stdin.buffer.read()\nsys.stdout.buffer.write({reply!r})\n",
    )
    rogue = PdfProcessRunner(max_concurrent=1, worker_command=command)
    with pytest.raises(UnsupportedContentError, match="PDF could not be parsed safely"):
        canon(mode, rogue, doc("ok", "x"))
    assert rogue.live_count() == 0


def test_a_worker_that_never_reads_its_input_cannot_block_the_writer(
    mode: str, tmp_path: Path
) -> None:
    sleeper = _script(tmp_path, "sleeper.py", "import time\ntime.sleep(60)\n")
    rogue = PdfProcessRunner(max_concurrent=1, worker_command=sleeper, max_input_bytes=64_000_000)
    big = b"%PDF-DOUBLE\nok\n" + b"z" * 12_000_000  # far larger than any pipe buffer
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        canon(mode, rogue, big, timeout=0.8)
    assert time.monotonic() - started < 4.0
    assert rogue.live_count() == 0 and all(gone(pid) for pid in rogue.spawned_pids)


def _peak_children(runner: PdfProcessRunner, work: Callable[[], None]) -> int:
    peak = 0
    stop = threading.Event()

    def sample() -> None:
        nonlocal peak
        while not stop.is_set():
            peak = max(peak, runner.live_count())
            time.sleep(0.005)

    sampler = threading.Thread(target=sample)
    sampler.start()
    try:
        work()
    finally:
        stop.set()
        sampler.join()
    return peak


def test_concurrent_requests_never_exceed_the_child_bound(mode: str) -> None:
    bounded = PdfProcessRunner(max_concurrent=2, search_paths=[STUB])
    results: list[str] = []

    def one() -> None:
        results.append(canon(mode, bounded, doc("slow-ok 0.3", "done"), timeout=20.0))

    def burst() -> None:
        with ThreadPoolExecutor(max_workers=6) as pool:
            for future in [pool.submit(one) for _ in range(6)]:
                future.result()

    peak = _peak_children(bounded, burst)
    assert results == ["done"] * 6
    assert 1 <= peak <= 2
    assert len(bounded.spawned_pids) == 6 and bounded.live_count() == 0


def test_async_requests_on_one_loop_never_exceed_the_child_bound() -> None:
    bounded = PdfProcessRunner(max_concurrent=2, search_paths=[STUB])
    holder: dict[str, Any] = {}

    async def scenario() -> list[str]:
        async def one() -> str:
            return await bounded.acanonicalize(
                doc("slow-ok 0.3", "done"), max_chars=100, max_pages=1, timeout_seconds=20
            )

        return list(await asyncio.gather(*[one() for _ in range(6)]))

    peak = _peak_children(bounded, lambda: holder.update(out=asyncio.run(scenario())))
    assert holder["out"] == ["done"] * 6
    assert 1 <= peak <= 2


def test_waiting_for_a_slot_respects_the_deadline_and_spawns_nothing(tmp_path: Path) -> None:
    one_slot = PdfProcessRunner(max_concurrent=1, search_paths=[STUB])

    async def scenario() -> None:
        holder = asyncio.ensure_future(
            one_slot.acanonicalize(
                doc("hang-sleep", "x"), max_chars=100, max_pages=1, timeout_seconds=2.5
            )
        )
        for _ in range(200):
            if one_slot.live_count() == 1:
                break
            await asyncio.sleep(0.02)
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            await one_slot.acanonicalize(
                doc("ok", "x"), max_chars=100, max_pages=1, timeout_seconds=0.3
            )
        assert time.monotonic() - started < 1.5
        assert len(one_slot.spawned_pids) == 1  # the waiter never launched a process
        with pytest.raises(TimeoutError):
            await holder

    asyncio.run(scenario())
    assert one_slot.live_count() == 0


def test_a_failed_request_releases_its_slot(mode: str) -> None:
    one_slot = PdfProcessRunner(max_concurrent=1, search_paths=[STUB])
    for _ in range(3):
        with pytest.raises(TimeoutError):
            canon(mode, one_slot, doc("hang-sleep", "x"), timeout=0.3)
    assert canon(mode, one_slot, doc("ok", "fine")) == "fine"
    assert one_slot.live_count() == 0


# --------------------------------------------------------------------------- #
# Every ingestion entry path is covered
# --------------------------------------------------------------------------- #


def test_canonicalize_content_is_isolated(runner: PdfProcessRunner) -> None:
    with use_runner(runner):
        assert (
            canonicalize_content(
                doc("ok", "Hello  world"), media_type="application/pdf", max_chars=100
            )
            == "Hello  world"
        )
        with pytest.raises(TimeoutError):
            canonicalize_content(
                doc("hang-sleep", "x"),
                media_type="application/pdf",
                max_chars=100,
                pdf_timeout_seconds=0.5,
            )
        assert (
            asyncio.run(
                acanonicalize_content(
                    doc("ok", "Async"), media_type="application/pdf", max_chars=100
                )
            )
            == "Async"
        )
    assert runner.live_count() == 0 and all(gone(pid) for pid in runner.spawned_pids)


def _policy() -> SourcePolicyRecord:
    from datetime import date

    return SourcePolicyRecord(
        policy_id="issuer-hdfc",
        name="HDFC official",
        owner="HDFC Bank",
        domain="hdfcbank.com",
        source_url="https://www.hdfcbank.com/cards/infinia",
        terms_url="https://www.hdfcbank.com/terms",
        terms_read_on=date(2026, 10, 1),
        automated_access_permitted=True,
        manual_only=False,
        allowed_page_classes=("card_page", "tnc_pdf"),
        minimum_delay_seconds=10,
        reviewed_on=date(2026, 10, 1),
        reviewed_by="curator-1",
    )


def _request(*, kind: str = "official_page", timeout: int = 3, max_pages: int = 5) -> FetchRequest:
    page_class = PageKind.TNC_PDF if kind == "tnc_pdf" else PageKind.CARD_PAGE
    return FetchRequest(
        request_id="fetch-1",
        canonical_url="https://www.hdfcbank.com/cards/infinia",
        source_policy_id="issuer-hdfc",
        evidence_kind=kind,  # type: ignore[arg-type]
        page_class=page_class,
        max_bytes=50_000,
        max_pages=max_pages,
        timeout_seconds=timeout,
        run_id="run-1",
    )


def _blob_count(root: Path) -> int:
    return sum(1 for path in (root / "blobs").rglob("*") if path.is_file())


def _manual(tmp_path: Path, data: bytes) -> tuple[ManualUploadBackend, ContentAddressedStore]:
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    upload = tmp_path / "capture.pdf"
    upload.write_bytes(data)
    policy = _policy().model_copy(update={"manual_only": True, "automated_access_permitted": False})
    return ManualUploadBackend(upload, artifacts=artifacts, policy=policy), artifacts


def test_manual_upload_success_is_unchanged(runner: PdfProcessRunner, tmp_path: Path) -> None:
    backend, artifacts = _manual(tmp_path, doc("ok", "Annual fee is INR 12,500."))
    with use_runner(runner):
        result = asyncio.run(backend.fetch(_request()))
    assert result.failure is None
    assert result.normalized_text == "Annual fee is INR 12,500."
    assert result.content_type == "application/pdf"
    assert result.raw_artifact is not None and result.normalized_artifact is not None
    assert artifacts.read(result.raw_artifact).startswith(b"%PDF-DOUBLE")
    assert _blob_count(artifacts.root) == 2
    assert runner.live_count() == 0


def test_manual_upload_page_limit_stays_an_invalid_response(
    runner: PdfProcessRunner, tmp_path: Path
) -> None:
    backend, artifacts = _manual(tmp_path, doc("pages 4"))
    with use_runner(runner):
        result = asyncio.run(backend.fetch(_request(max_pages=2)))
    assert result.failure is not None and result.failure.kind.value == "invalid_response"
    assert "page limit" in result.failure.diagnostic
    assert _blob_count(artifacts.root) == 0


def test_manual_upload_timeout_kills_the_parser_and_persists_nothing(
    runner: PdfProcessRunner, tmp_path: Path
) -> None:
    backend, artifacts = _manual(tmp_path, doc("hang-busy", "x"))
    started = time.monotonic()
    with use_runner(runner):
        result = asyncio.run(backend.fetch(_request(timeout=1)))
    assert time.monotonic() - started < 4.0
    assert result.failure is not None and result.failure.kind.value == "timeout"
    assert _blob_count(artifacts.root) == 0
    assert runner.live_count() == 0 and all(gone(pid) for pid in runner.spawned_pids)


def test_cancelling_a_manual_fetch_kills_the_parser_and_persists_nothing(
    runner: PdfProcessRunner, tmp_path: Path
) -> None:
    backend, artifacts = _manual(tmp_path, doc("hang-sleep", "x"))

    async def scenario() -> None:
        task = asyncio.ensure_future(backend.fetch(_request(timeout=30)))
        for _ in range(300):
            if runner.live_count() == 1:
                break
            await asyncio.sleep(0.02)
        assert runner.live_count() == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    with use_runner(runner):
        asyncio.run(scenario())
    assert _blob_count(artifacts.root) == 0
    assert runner.live_count() == 0 and all(gone(pid) for pid in runner.spawned_pids)


class _TncResult:
    success = True
    url = "https://www.hdfcbank.com/cards/infinia"
    redirected_url = url
    content_type = "application/pdf"
    html = None
    links: dict[str, list[dict[str, str]]] = {"internal": []}

    def __init__(self, body: bytes) -> None:
        self.body = body


class _TncCrawler:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def __aenter__(self) -> _TncCrawler:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def arun(self, *, url: str, config: Any) -> _TncResult:
        return _TncResult(self._body)


def _crawl(tmp_path: Path, body: bytes) -> tuple[Crawl4AIBackend, ContentAddressedStore]:
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    backend = Crawl4AIBackend(
        artifacts=artifacts,
        policy=_policy(),
        robots=RobotsRules.parse("User-agent: *\nAllow: /\n"),
        crawler_factory=lambda config: _TncCrawler(body),
    )
    return backend, artifacts


def test_crawl4ai_tnc_pdf_success_is_unchanged(runner: PdfProcessRunner, tmp_path: Path) -> None:
    backend, artifacts = _crawl(tmp_path, doc("ok", "Forex markup is 2%."))
    with use_runner(runner):
        result = asyncio.run(backend.fetch(_request(kind="tnc_pdf")))
    assert result.failure is None
    assert result.normalized_text == "Forex markup is 2%."
    assert result.content_type == "application/pdf"
    assert _blob_count(artifacts.root) == 2


def test_crawl4ai_tnc_pdf_is_no_longer_parsed_inline_without_a_deadline(
    runner: PdfProcessRunner, tmp_path: Path
) -> None:
    backend, artifacts = _crawl(tmp_path, doc("hang-sleep", "x"))
    started = time.monotonic()
    with use_runner(runner):
        result = asyncio.run(backend.fetch(_request(kind="tnc_pdf", timeout=1)))
    assert time.monotonic() - started < 4.0
    assert result.failure is not None and result.failure.kind.value == "timeout"
    assert _blob_count(artifacts.root) == 0
    assert runner.live_count() == 0 and all(gone(pid) for pid in runner.spawned_pids)


def _pdf_snapshot(
    tmp_path: Path, raw: bytes, canonical: str
) -> tuple[SnapshotBundle, ContentAddressedStore]:
    artifacts = ContentAddressedStore(tmp_path / "evidence")
    raw_ref = artifacts.put(raw, media_type="application/pdf")
    normalized = artifacts.put(canonical.encode(), media_type="text/plain")
    snapshot = SnapshotBundle(
        snapshot_id="snapshot:pdf:1",
        target_id="watch:pdf",
        captured_at=NOW,
        raw_artifact=raw_ref,
        normalized_artifact=normalized,
        raw_sha256=raw_ref.sha256,
        normalized_sha256=normalized.sha256,
        canonical_markdown=canonical,
    )
    return snapshot, artifacts


def _span(snapshot: SnapshotBundle, quote: str, page_number: int) -> EvidenceSpan:
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
        page_number=page_number,
    )


def test_evidence_verification_uses_the_isolated_parser(
    runner: PdfProcessRunner, tmp_path: Path
) -> None:
    raw = doc("ok", "Cover page", "Annual fee is INR 12,500.")
    snapshot, artifacts = _pdf_snapshot(tmp_path, raw, "Cover page\nAnnual fee is INR 12,500.")
    with use_runner(runner):
        verify_evidence_span(
            _span(snapshot, "Annual fee is INR 12,500.", 2), snapshot=snapshot, artifacts=artifacts
        )
        with pytest.raises(EvidenceVerificationError, match="not present on the cited page"):
            verify_evidence_span(
                _span(snapshot, "Annual fee is INR 12,500.", 1),
                snapshot=snapshot,
                artifacts=artifacts,
            )
        with pytest.raises(EvidenceVerificationError, match="outside the artifact"):
            verify_evidence_span(
                _span(snapshot, "Cover page", 9), snapshot=snapshot, artifacts=artifacts
            )
    assert runner.live_count() == 0


def test_evidence_verification_of_a_hung_pdf_fails_closed_and_kills_the_parser(
    tmp_path: Path,
) -> None:
    impatient = PdfProcessRunner(max_concurrent=1, search_paths=[STUB], default_timeout_seconds=0.6)
    snapshot, artifacts = _pdf_snapshot(tmp_path, doc("hang-busy", "Quote"), "Quote")
    started = time.monotonic()
    with use_runner(impatient):
        with pytest.raises(EvidenceVerificationError, match="could not be verified"):
            verify_evidence_span(
                _span(snapshot, "Quote", 1), snapshot=snapshot, artifacts=artifacts
            )
    assert time.monotonic() - started < 4.0
    assert impatient.live_count() == 0 and all(gone(pid) for pid in impatient.spawned_pids)


# --------------------------------------------------------------------------- #
# No bypass in source
# --------------------------------------------------------------------------- #

INGESTION = BACKEND / "ingestion"
PROCESS_MODULES = {"pdf_isolation.py"}


def _modules(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _sources() -> list[Path]:
    return [p for p in sorted(INGESTION.rglob("*.py")) if "fixtures" not in p.parts]


def test_only_the_worker_names_the_parser_library() -> None:
    offenders = []
    for path in _sources():
        text = path.read_text()
        if path.name != "pdf_worker.py" and "pdfplumber" in text.replace(
            "ingestion-local", ""
        ).replace("optional ingestion", ""):
            offenders.append(path.name)
    assert offenders == [], f"PDF parser referenced outside the isolated worker: {offenders}"


def test_process_creation_is_confined_to_the_runner_and_never_uses_a_shell() -> None:
    for path in _sources():
        modules = _modules(path)
        tree_text = path.read_text()
        if path.name == "pdf_worker.py":
            # The worker may use ``os``/``signal`` to end its own group, but never spawns.
            assert not ({"subprocess", "multiprocessing"} & modules)
            assert "os.system" not in tree_text and "os.popen" not in tree_text
            continue
        if path.name in PROCESS_MODULES:
            assert "shell=True" not in tree_text and "create_subprocess_shell" not in tree_text
            assert "os.system" not in tree_text and "os.popen" not in tree_text
            continue
        assert not ({"subprocess", "multiprocessing", "os"} & modules) or path.name in {
            "artifacts.py",
            "storage.py",
        }, path.name
        assert "create_subprocess" not in tree_text, path.name


def test_no_ingestion_module_runs_the_canonicalizer_on_a_thread_directly() -> None:
    """``to_thread(canonicalize_content, ...)`` is the pattern that could not stop a parser."""
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name)):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
                if name == "to_thread" and node.args:
                    first = node.args[0]
                    target = first.id if isinstance(first, ast.Name) else ""
                    assert target != "canonicalize_pdf", path.name
                    if path.name != "canonical.py":
                        assert target != "canonicalize_content", path.name


def test_the_default_worker_launch_is_a_fixed_argv_list() -> None:
    command = PdfProcessRunner(search_paths=[STUB]).worker_command
    assert isinstance(command, list) and all(isinstance(part, str) for part in command)
    assert command[0] == sys.executable and "-I" in command
    assert command[:3] == [sys.executable, "-I", "-c"]  # constant bootstrap, no user text
    assert "shell" not in " ".join(command[3:4])
