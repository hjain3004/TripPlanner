"""Deterministic synthetic stand-in for ``pdfplumber`` (test double, never shipped).

Behaviour is selected by the document bytes, so tests drive a real child process through a
parser that succeeds, hangs, ignores SIGTERM, spawns a grandchild, writes late, or dies.

    %PDF-DOUBLE\\n<directive> [args]\\n<page text>\\f<page text>...
"""

from __future__ import annotations

import builtins
import os
import signal
import subprocess
import sys
import time
from typing import Any


class _Page:
    def __init__(self, text: str, behavior: list[str]) -> None:
        self._text = text
        self._behavior = behavior

    def extract_text(self) -> str:
        directive = self._behavior[0] if self._behavior else "ok"
        args = self._behavior[1:]
        if directive == "hang-sleep":
            while True:
                time.sleep(0.05)
        if directive == "hang-busy":
            while True:
                pass
        if directive == "hang-ignore-term":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            while True:
                time.sleep(0.05)
        if directive == "grandchild":
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
            with builtins.open(args[0], "w") as handle:
                handle.write(str(child.pid))
            while True:
                time.sleep(0.05)
        if directive == "grandchild-then-raise":
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
            with builtins.open(args[0], "w") as handle:
                handle.write(str(child.pid))
            raise ValueError("synthetic failure after spawning a helper")
        if directive == "late-write":
            time.sleep(float(args[0]))
            with builtins.open(args[1], "w") as handle:
                handle.write("written after the deadline")
        if directive == "slow-ok":
            time.sleep(float(args[0]))
        if directive == "crash":
            os._exit(3)
        if directive == "segv":
            os.kill(os.getpid(), signal.SIGSEGV)
        if directive == "raise":
            raise ValueError("synthetic parser failure")
        if directive == "bigpage":
            return "x" * int(args[0])
        return self._text


class _Document:
    def __init__(self, data: bytes) -> None:
        header, _, body = data.partition(b"\n")
        if header != b"%PDF-DOUBLE":
            raise ValueError("not a synthetic PDF")
        directive_line, _, text = body.partition(b"\n")
        behavior = directive_line.decode().split()
        texts = text.decode().split("\f") if text else []
        if behavior[:1] == ["pages"]:
            texts = [""] * int(behavior[1])
            behavior = []
        self.pages = [_Page(t, behavior) for t in texts]

    def __enter__(self) -> _Document:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


def open(stream: Any) -> _Document:  # noqa: A001 - mirrors pdfplumber.open
    return _Document(stream.read())
