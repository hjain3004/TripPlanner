"""Child-process entry point that actually parses a PDF.

Launched only by ``ingestion.pdf_isolation`` with a fixed argv. It reads one JSON header
line and ``data_len`` raw bytes from stdin, parses with the optional ``pdfplumber``, and
writes exactly one JSON line to stdout. It has no path, URL or command input and opens no
files, so there is nothing for a PDF to "persist" through this process: its only output is
the reply the parent validates and bounds.

This module is the only place in the ingestion package that imports the parser library.
"""

from __future__ import annotations

import io
import json
import os
import signal
import sys
from typing import Any

from ingestion.canonical import ContentLimitError, _normalize_lines

MAX_HEADER_BYTES = 4096
MAX_INPUT_BYTES = 256 * 1024 * 1024  # absolute ceiling; the parent enforces a tighter bound
MAX_PAGE_TEXT_CHARS = 1_000_000


def _reply(payload: dict[str, Any]) -> None:
    # ensure_ascii keeps the reply pure ASCII (and lossless for odd code points); the parent
    # bounds the byte length knowing escapes can expand each character up to six-fold.
    line = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    sys.stdout.buffer.write(line.encode("ascii") + b"\n")
    sys.stdout.buffer.flush()


def _read_request() -> tuple[dict[str, Any], bytes] | None:
    stdin = sys.stdin.buffer
    line = stdin.readline(MAX_HEADER_BYTES + 1)
    if not line.endswith(b"\n") or len(line) > MAX_HEADER_BYTES:
        return None
    try:
        header = json.loads(line)
    except ValueError:
        return None
    if not isinstance(header, dict):
        return None
    length = header.get("data_len")
    if (
        isinstance(length, bool)
        or not isinstance(length, int)
        or not 0 <= length <= MAX_INPUT_BYTES
    ):
        return None
    data = stdin.read(length)
    if len(data) != length:
        return None
    return header, data


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _parse(header: dict[str, Any], data: bytes) -> dict[str, Any]:
    try:
        # The optional ingestion-local extra; imported dynamically (as before) because it is
        # not installed by default and ships no type stubs.
        pdfplumber = __import__("pdfplumber")
    except ImportError:
        return {"ok": False, "kind": "missing_dependency"}
    operation = header.get("op")
    try:
        with pdfplumber.open(io.BytesIO(data)) as document:
            pages = document.pages
            count = len(pages)
            if operation == "canonicalize":
                max_pages = _positive_int(header.get("max_pages"))
                max_chars = _positive_int(header.get("max_chars"))
                if max_pages is None or max_chars is None:
                    return {"ok": False, "kind": "unsupported"}
                if count > max_pages:
                    return {
                        "ok": False,
                        "kind": "content_limit",
                        "message": f"PDF exceeds {max_pages} page limit",
                    }
                text = "\n".join(page.extract_text() or "" for page in pages)
                try:
                    normalized = _normalize_lines(text, max_chars=max_chars)
                except ContentLimitError as error:
                    return {"ok": False, "kind": "content_limit", "message": str(error)}
                return {"ok": True, "text": normalized, "pages": count}
            if operation == "page_text":
                number = _positive_int(header.get("page_number"))
                if number is None:
                    return {"ok": False, "kind": "unsupported"}
                if number > count:
                    return {"ok": False, "kind": "page_out_of_range"}
                page_text = pages[number - 1].extract_text() or ""
                if len(page_text) > MAX_PAGE_TEXT_CHARS:
                    return {
                        "ok": False,
                        "kind": "content_limit",
                        "message": "PDF page text exceeds the verification bound",
                    }
                return {"ok": True, "text": page_text, "pages": count}
            return {"ok": False, "kind": "unsupported"}
    except Exception:
        return {"ok": False, "kind": "unsupported"}


def _end_own_process_group() -> None:
    """After replying, kill this worker's private group so no helper the parser spawned can
    outlive the request. Only when the worker really leads its own group (the parent starts
    it with a new session); a hand-run worker sharing a terminal's group is left alone."""
    if os.getpgrp() == os.getpid():
        os.killpg(os.getpgrp(), signal.SIGKILL)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # Test seam: directories searched before the environment for the parser library. The
    # production launch passes none, and only the parent process can construct argv.
    while args:
        flag = args.pop(0)
        if flag == "--search-path" and args:
            sys.path.insert(0, args.pop(0))
        else:
            return 2
    request = _read_request()
    if request is None:
        _reply({"ok": False, "kind": "unsupported"})
        _end_own_process_group()
        return 0
    header, data = request
    _reply(_parse(header, data))
    _end_own_process_group()
    return 0
