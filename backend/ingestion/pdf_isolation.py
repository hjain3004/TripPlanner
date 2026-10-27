"""Run PDF parsing in a child process that can really be killed.

Why: ``asyncio.to_thread`` + ``wait_for`` returns a timeout to the caller but cannot stop the
thread that is still inside the parser. Here every parse runs in its own short-lived child
process (``python -I``, fixed argv, no shell). On success, error, deadline or caller
cancellation the child's whole process group is sent SIGKILL and the child is reaped before
the call returns, so a timed-out parser cannot keep running, cannot be left a zombie, and
cannot deliver a result after the fact: results exist only as the bounded reply this module
validates and returns.

What this guarantees
* the parser stops (SIGKILL cannot be ignored or deferred by a busy C loop);
* only processes this operation created are touched (a private process group per child);
* at most ``max_concurrent`` children exist at once, across sync and async callers;
* input, reply size and total time (slot wait included) are bounded;
* a reply that is malformed, oversized or from a crashed child is ``UnsupportedContentError``.

What it does NOT guarantee
* It is not an OS sandbox. The child runs as the same user with the same filesystem,
  network and memory access; a parser exploit could still read files or open sockets
  before the deadline. Use a container/seccomp/jail for that.
* No memory or CPU rlimits are set; only wall-clock time and pipe sizes are bounded.
* Group cleanup signals the child's pgid unconditionally. While any group member lives the
  pgid cannot be reissued as a pid, so this is safe; only after the whole group is gone could
  a recycled pid collide, a window of microseconds that is accepted and documented.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import selectors
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import IO

from ingestion.canonical import ContentLimitError, UnsupportedContentError

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_CONCURRENT = 2
DEFAULT_MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_PAGE_TEXT_CHARS = 1_000_000
REAP_TIMEOUT_SECONDS = 5.0
_CHUNK = 65536
_JSON_EXPANSION = 12  # worst case: an astral character is a 12-byte escaped surrogate pair
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_BOOTSTRAP = (
    "import sys; sys.path.append(sys.argv[1]); "
    "from ingestion.pdf_worker import main; raise SystemExit(main(sys.argv[2:]))"
)
_CHILD_ENV = {
    "PYTHONUTF8": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
}
_UNSUPPORTED = "PDF could not be parsed safely"
_MISSING = "PDF canonicalization requires the optional ingestion-local extra"


class PdfPageOutOfRange(ValueError):
    """The cited page does not exist in the PDF."""


class _Overflow(Exception):
    """The child wrote more than its declared reply bound."""


def _unsupported() -> UnsupportedContentError:
    return UnsupportedContentError(_UNSUPPORTED)


def _kill_group(pgid: int) -> None:
    """SIGKILL the child's private process group (its pgid equals the pid it was started with).

    Always signalled, even if the leader has already been reaped (asyncio reaps behind our
    back): surviving members keep the pgid reserved, and an empty group just raises ESRCH."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGKILL)


class PdfProcessRunner:
    def __init__(
        self,
        *,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        search_paths: Sequence[Path] = (),
        worker_command: Sequence[str] | None = None,
        max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
        default_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if max_concurrent < 1 or max_input_bytes < 1 or default_timeout_seconds <= 0:
            raise ValueError("runner bounds must be positive")
        if worker_command is not None:
            self.worker_command: list[str] = list(worker_command)
        else:
            self.worker_command = [sys.executable, "-I", "-c", _BOOTSTRAP, str(_BACKEND_ROOT)]
            for directory in search_paths:
                self.worker_command += ["--search-path", str(directory)]
        self._max_concurrent = max_concurrent
        self._max_input_bytes = max_input_bytes
        self.default_timeout_seconds = default_timeout_seconds
        self._slots = threading.Condition()
        self._held = 0
        self._live: set[int] = set()
        self.spawned_pids: list[int] = []  # diagnostic: every child this runner ever started

    # ------------------------------------------------------------------ bookkeeping

    def live_count(self) -> int:
        with self._slots:
            return len(self._live)

    def _try_acquire(self) -> bool:
        with self._slots:
            if self._held < self._max_concurrent:
                self._held += 1
                return True
            return False

    def _release(self) -> None:
        with self._slots:
            self._held -= 1
            self._slots.notify()

    def _acquire_sync(self, deadline: float) -> None:
        with self._slots:
            while self._held >= self._max_concurrent:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("PDF parser slot unavailable before the deadline")
                self._slots.wait(remaining)
            self._held += 1

    async def _acquire_async(self, deadline: float) -> None:
        while not self._try_acquire():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("PDF parser slot unavailable before the deadline")
            await asyncio.sleep(min(0.01, remaining))

    def _started(self, pid: int) -> None:
        with self._slots:
            self._live.add(pid)
            self.spawned_pids.append(pid)
            if len(self.spawned_pids) > 4096:  # diagnostic only; keep it bounded
                del self.spawned_pids[:2048]

    def _finished(self, pid: int) -> None:
        with self._slots:
            self._live.discard(pid)

    # ------------------------------------------------------------------ request/reply

    def _payload(self, header: dict[str, object], data: bytes) -> bytes:
        if len(data) > self._max_input_bytes:
            raise ContentLimitError(f"PDF exceeds the {self._max_input_bytes} byte input bound")
        full = {**header, "data_len": len(data)}
        return json.dumps(full, separators=(",", ":")).encode("utf-8") + b"\n" + data

    @staticmethod
    def _decode(raw: bytes, *, max_chars: int) -> str:
        if not raw.endswith(b"\n"):
            raise _unsupported()  # truncated reply: the child died mid-write
        try:
            reply = json.loads(raw)
        except (ValueError, RecursionError):
            raise _unsupported() from None
        if not isinstance(reply, dict) or not isinstance(reply.get("ok"), bool):
            raise _unsupported()
        if reply["ok"]:
            text = reply.get("text")
            if not isinstance(text, str):
                raise _unsupported()
            if len(text) > max_chars:
                raise ContentLimitError(f"normalized content exceeds {max_chars} characters")
            return text
        kind = reply.get("kind")
        message = reply.get("message")
        if kind == "content_limit" and isinstance(message, str):
            raise ContentLimitError(message[:300])
        if kind == "missing_dependency":
            raise UnsupportedContentError(_MISSING)
        if kind == "page_out_of_range":
            raise PdfPageOutOfRange("PDF page is outside the document")
        raise _unsupported()

    # ------------------------------------------------------------------ sync execution

    def _run_sync(self, payload: bytes, *, reply_limit: int, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        self._acquire_sync(deadline)
        process: subprocess.Popen[bytes] | None = None
        try:
            try:
                process = subprocess.Popen(  # noqa: S603 - fixed argv list, no shell
                    self.worker_command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    start_new_session=True,
                    env=_CHILD_ENV,
                )
            except OSError:
                raise UnsupportedContentError("PDF parser could not be started") from None
            self._started(process.pid)
            return self._pump_sync(process, payload, reply_limit, deadline)
        finally:
            try:
                if process is not None:
                    self._reap_sync(process)
            finally:
                self._release()

    @staticmethod
    def _pump_sync(
        process: subprocess.Popen[bytes], payload: bytes, reply_limit: int, deadline: float
    ) -> bytes:
        assert process.stdin is not None and process.stdout is not None
        stdin: IO[bytes] = process.stdin
        stdout: IO[bytes] = process.stdout
        os.set_blocking(stdin.fileno(), False)
        os.set_blocking(stdout.fileno(), False)
        selector = selectors.DefaultSelector()
        selector.register(stdout, selectors.EVENT_READ)
        selector.register(stdin, selectors.EVENT_WRITE)
        view = memoryview(payload)
        sent = 0
        reply = bytearray()
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("PDF parser exceeded its deadline")
                for key, _ in selector.select(remaining):
                    if key.fileobj is stdin:
                        try:
                            sent += os.write(stdin.fileno(), view[sent : sent + _CHUNK])
                        except BlockingIOError:
                            continue
                        except BrokenPipeError:
                            sent = len(payload)  # the child stopped reading; judge its reply
                        if sent >= len(payload):
                            selector.unregister(stdin)
                            stdin.close()
                    else:
                        try:
                            chunk = os.read(stdout.fileno(), _CHUNK)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            return bytes(reply)
                        reply += chunk
                        if len(reply) > reply_limit:
                            raise _Overflow
                        if reply.endswith(b"\n"):
                            return bytes(reply)  # the one-line reply is complete
        except _Overflow:
            raise _unsupported() from None
        finally:
            selector.close()

    def _reap_sync(self, process: subprocess.Popen[bytes]) -> None:
        try:
            _kill_group(process.pid)
            with contextlib.suppress(OSError):
                process.kill()
            try:
                process.wait(timeout=REAP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                return  # unkillable (uninterruptible sleep): keep the pid listed as live
            self._finished(process.pid)
        finally:
            for pipe in (process.stdin, process.stdout):
                if pipe is not None:
                    with contextlib.suppress(OSError):
                        pipe.close()

    # ------------------------------------------------------------------ async execution

    async def _run_async(self, payload: bytes, *, reply_limit: int, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        await self._acquire_async(deadline)
        process: asyncio.subprocess.Process | None = None
        try:
            try:
                process = await asyncio.create_subprocess_exec(
                    *self.worker_command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=True,
                    env=_CHILD_ENV,
                )
            except OSError:
                raise UnsupportedContentError("PDF parser could not be started") from None
            self._started(process.pid)
            remaining = max(deadline - time.monotonic(), 0.0)
            async with asyncio.timeout(remaining):
                return await self._pump_async(process, payload, reply_limit)
        finally:
            try:
                if process is not None:
                    await self._reap_async(process)
            finally:
                self._release()

    @staticmethod
    async def _pump_async(
        process: asyncio.subprocess.Process, payload: bytes, reply_limit: int
    ) -> bytes:
        assert process.stdin is not None and process.stdout is not None
        try:
            process.stdin.write(payload)
            await process.stdin.drain()
            process.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the child stopped reading; whatever it replied is judged below
        reply = bytearray()
        while True:
            chunk = await process.stdout.read(_CHUNK)
            if not chunk:
                return bytes(reply)
            reply += chunk
            if len(reply) > reply_limit:
                raise _unsupported()
            if reply.endswith(b"\n"):
                return bytes(reply)  # the one-line reply is complete; do not wait for EOF

    async def _reap_async(self, process: asyncio.subprocess.Process) -> None:
        pid = process.pid
        _kill_group(pid)
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        try:
            await asyncio.wait_for(asyncio.shield(process.wait()), REAP_TIMEOUT_SECONDS)
        except (TimeoutError, Exception):
            return  # unkillable: leave the pid listed as live
        finally:
            # Also reached on a second cancellation: the kill was already issued, so once the
            # (shielded) wait completes the bookkeeping must clear even while unwinding.
            if process.returncode is not None:
                self._finished(pid)
            else:
                waiter = asyncio.ensure_future(process.wait())
                waiter.add_done_callback(lambda _: self._finished(pid))

    # ------------------------------------------------------------------ public API

    def _timeout(self, timeout_seconds: float | None) -> float:
        return self.default_timeout_seconds if timeout_seconds is None else timeout_seconds

    def _canonical_request(self, data: bytes, max_chars: int, max_pages: int) -> tuple[bytes, int]:
        if max_chars < 1 or max_pages < 1:
            raise ValueError("PDF limits must be positive")
        payload = self._payload(
            {"op": "canonicalize", "max_chars": max_chars, "max_pages": max_pages}, data
        )
        return payload, max_chars * _JSON_EXPANSION + 4096

    def _page_request(self, data: bytes, page_number: int) -> tuple[bytes, int]:
        if page_number < 1:
            raise ValueError("page_number starts at 1")
        payload = self._payload({"op": "page_text", "page_number": page_number}, data)
        return payload, MAX_PAGE_TEXT_CHARS * _JSON_EXPANSION + 4096

    def canonicalize(
        self,
        data: bytes,
        *,
        max_chars: int,
        max_pages: int,
        timeout_seconds: float | None = None,
    ) -> str:
        payload, limit = self._canonical_request(data, max_chars, max_pages)
        raw = self._run_sync(payload, reply_limit=limit, timeout=self._timeout(timeout_seconds))
        return self._decode(raw, max_chars=max_chars)

    async def acanonicalize(
        self,
        data: bytes,
        *,
        max_chars: int,
        max_pages: int,
        timeout_seconds: float | None = None,
    ) -> str:
        payload, limit = self._canonical_request(data, max_chars, max_pages)
        raw = await self._run_async(
            payload, reply_limit=limit, timeout=self._timeout(timeout_seconds)
        )
        return self._decode(raw, max_chars=max_chars)

    def page_text(
        self, data: bytes, *, page_number: int, timeout_seconds: float | None = None
    ) -> str:
        payload, limit = self._page_request(data, page_number)
        raw = self._run_sync(payload, reply_limit=limit, timeout=self._timeout(timeout_seconds))
        return self._decode(raw, max_chars=MAX_PAGE_TEXT_CHARS)

    async def apage_text(
        self, data: bytes, *, page_number: int, timeout_seconds: float | None = None
    ) -> str:
        payload, limit = self._page_request(data, page_number)
        raw = await self._run_async(
            payload, reply_limit=limit, timeout=self._timeout(timeout_seconds)
        )
        return self._decode(raw, max_chars=MAX_PAGE_TEXT_CHARS)


_default_lock = threading.Lock()
_default_runner: PdfProcessRunner | None = None
_override: PdfProcessRunner | None = None


def get_default_runner() -> PdfProcessRunner:
    """The process-wide runner every ingestion PDF path shares (one concurrency bound)."""
    global _default_runner
    with _default_lock:
        if _override is not None:
            return _override
        if _default_runner is None:
            _default_runner = PdfProcessRunner()
        return _default_runner


@contextlib.contextmanager
def use_runner(runner: PdfProcessRunner) -> Iterator[PdfProcessRunner]:
    """Temporarily route every ingestion PDF path through ``runner`` (tests, tuning)."""
    global _override
    with _default_lock:
        previous, _override = _override, runner
    try:
        yield runner
    finally:
        with _default_lock:
            _override = previous
