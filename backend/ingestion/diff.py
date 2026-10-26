"""Deterministic normalized snapshot comparison."""

from __future__ import annotations

import difflib
from dataclasses import dataclass


@dataclass(frozen=True)
class SnapshotDiff:
    changed: bool
    before_sha256: str | None
    after_sha256: str
    unified_diff: str


def diff_text(before: str | None, after: str) -> SnapshotDiff:
    old_lines = [] if before is None else before.splitlines(keepends=True)
    new_lines = after.splitlines(keepends=True)
    changed = before != after
    patch = "".join(
        difflib.unified_diff(old_lines, new_lines, fromfile="previous", tofile="current")
    )
    import hashlib

    return SnapshotDiff(
        changed=changed,
        before_sha256=None if before is None else hashlib.sha256(before.encode()).hexdigest(),
        after_sha256=hashlib.sha256(after.encode()).hexdigest(),
        unified_diff=patch,
    )
