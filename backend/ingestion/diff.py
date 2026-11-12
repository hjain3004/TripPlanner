"""Deterministic normalized snapshot comparison and contextual changed block extraction."""

from __future__ import annotations

import difflib
import hashlib
from typing import Literal

from feed.contracts import BlockLimits, BlockOutcome, ChangedBlock


class SnapshotDiff:
    __slots__ = ("changed", "before_sha256", "after_sha256", "unified_diff")

    def __init__(
        self,
        *,
        changed: bool,
        before_sha256: str | None,
        after_sha256: str,
        unified_diff: str,
    ) -> None:
        self.changed = changed
        self.before_sha256 = before_sha256
        self.after_sha256 = after_sha256
        self.unified_diff = unified_diff

    def __repr__(self) -> str:
        return (
            f"SnapshotDiff(changed={self.changed!r}, "
            f"before_sha256={self.before_sha256!r}, "
            f"after_sha256={self.after_sha256!r}, "
            f"unified_diff={self.unified_diff!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SnapshotDiff):
            return NotImplemented
        return (
            self.changed == other.changed
            and self.before_sha256 == other.before_sha256
            and self.after_sha256 == other.after_sha256
            and self.unified_diff == other.unified_diff
        )


def diff_text(before: str | None, after: str) -> SnapshotDiff:
    """Compute unified diff between two snapshot strings (preserves existing callers)."""
    old_lines = [] if before is None else before.splitlines(keepends=True)
    new_lines = after.splitlines(keepends=True)
    changed = before != after
    patch = "".join(
        difflib.unified_diff(old_lines, new_lines, fromfile="previous", tofile="current")
    )

    return SnapshotDiff(
        changed=changed,
        before_sha256=None if before is None else hashlib.sha256(before.encode()).hexdigest(),
        after_sha256=hashlib.sha256(after.encode()).hexdigest(),
        unified_diff=patch,
    )


def changed_blocks(
    before: str | None,
    after: str,
    *,
    limits: BlockLimits | None = None,
) -> BlockOutcome:
    """Extract contextual changed blocks between two canonical snapshot versions.

    Enforces finite boundaries (200k chars, 4000 lines, 8k chars/side, 32 blocks max).
    Preserves absolute char offsets against original text and supports deletion-only blocks.
    A first capture (before=None) returns status="baseline".
    """
    effective_limits = limits or BlockLimits()

    if len(after) > effective_limits.max_text_chars:
        return BlockOutcome(
            status="oversize",
            diagnostic=(
                f"after text ({len(after)} chars) exceeds max_text_chars "
                f"({effective_limits.max_text_chars})"
            ),
        )

    after_lines = after.splitlines(keepends=True)
    if len(after_lines) > effective_limits.max_lines:
        return BlockOutcome(
            status="oversize",
            diagnostic=(
                f"after text ({len(after_lines)} lines) exceeds max_lines "
                f"({effective_limits.max_lines})"
            ),
        )

    if before is None:
        return BlockOutcome(
            status="baseline",
            blocks=(),
            total_blocks=0,
            diagnostic="first capture is a baseline; no previous snapshot to diff",
        )

    if len(before) > effective_limits.max_text_chars:
        return BlockOutcome(
            status="oversize",
            diagnostic=(
                f"before text ({len(before)} chars) exceeds max_text_chars "
                f"({effective_limits.max_text_chars})"
            ),
        )

    before_lines = before.splitlines(keepends=True)
    if len(before_lines) > effective_limits.max_lines:
        return BlockOutcome(
            status="oversize",
            diagnostic=(
                f"before text ({len(before_lines)} lines) exceeds max_lines "
                f"({effective_limits.max_lines})"
            ),
        )

    if before == after:
        return BlockOutcome(
            status="unchanged",
            blocks=(),
            total_blocks=0,
        )

    # Line start offsets for absolute character indexing
    before_line_starts: list[int] = []
    curr = 0
    for line in before_lines:
        before_line_starts.append(curr)
        curr += len(line)

    after_line_starts: list[int] = []
    curr = 0
    for line in after_lines:
        after_line_starts.append(curr)
        curr += len(line)

    matcher = difflib.SequenceMatcher(None, before_lines, after_lines, autojunk=False)
    opcodes = [op for op in matcher.get_opcodes() if op[0] != "equal"]

    if not opcodes:
        return BlockOutcome(status="unchanged", blocks=(), total_blocks=0)

    ctx = effective_limits.context_lines

    # Group opcodes into clusters with context lines, merging overlapping contexts
    clusters: list[list[tuple[str, int, int, int, int]]] = []
    current_cluster: list[tuple[str, int, int, int, int]] = []

    def cluster_bounds(
        items: list[tuple[str, int, int, int, int]],
    ) -> tuple[int, int, int, int]:
        b_min = min(op[1] for op in items)
        b_max = max(op[2] for op in items)
        a_min = min(op[3] for op in items)
        a_max = max(op[4] for op in items)
        b_ctx_start = max(0, b_min - ctx)
        b_ctx_end = min(len(before_lines), b_max + ctx)
        a_ctx_start = max(0, a_min - ctx)
        a_ctx_end = min(len(after_lines), a_max + ctx)
        return b_ctx_start, b_ctx_end, a_ctx_start, a_ctx_end

    for op in opcodes:
        if not current_cluster:
            current_cluster.append(op)
            continue

        b_ctx_start, b_ctx_end, a_ctx_start, a_ctx_end = cluster_bounds(current_cluster)
        op_b_ctx_start = max(0, op[1] - ctx)
        op_a_ctx_start = max(0, op[3] - ctx)

        # Check if the new opcode's context overlaps or touches the current cluster's context
        if op_b_ctx_start <= b_ctx_end or op_a_ctx_start <= a_ctx_end:
            current_cluster.append(op)
        else:
            clusters.append(current_cluster)
            current_cluster = [op]

    if current_cluster:
        clusters.append(current_cluster)

    if len(clusters) > effective_limits.max_blocks:
        return BlockOutcome(
            status="needs_review",
            total_blocks=len(clusters),
            diagnostic=(
                f"changed blocks count ({len(clusters)}) exceeds max_blocks "
                f"({effective_limits.max_blocks})"
            ),
        )

    result_blocks: list[ChangedBlock] = []

    for cluster in clusters:
        b_ctx_start, b_ctx_end, a_ctx_start, a_ctx_end = cluster_bounds(cluster)

        tags = {op[0] for op in cluster}
        if tags == {"delete"}:
            change_kind: Literal["addition", "deletion", "modification"] = "deletion"
        elif tags == {"insert"}:
            change_kind = "addition"
        else:
            change_kind = "modification"

        before_slice = "".join(before_lines[b_ctx_start:b_ctx_end])
        after_slice = "".join(after_lines[a_ctx_start:a_ctx_end])

        if len(before_slice) > effective_limits.max_block_chars_per_side:
            return BlockOutcome(
                status="needs_review",
                total_blocks=len(clusters),
                diagnostic=(
                    f"before content in block ({len(before_slice)} chars) exceeds "
                    f"max_block_chars_per_side ({effective_limits.max_block_chars_per_side})"
                ),
            )

        if len(after_slice) > effective_limits.max_block_chars_per_side:
            return BlockOutcome(
                status="needs_review",
                total_blocks=len(clusters),
                diagnostic=(
                    f"after content in block ({len(after_slice)} chars) exceeds "
                    f"max_block_chars_per_side ({effective_limits.max_block_chars_per_side})"
                ),
            )

        # Compute character offsets
        before_char_range = (
            (
                before_line_starts[b_ctx_start],
                before_line_starts[b_ctx_end - 1] + len(before_lines[b_ctx_end - 1]),
            )
            if b_ctx_end > b_ctx_start
            else None
        )

        after_char_range = (
            (
                after_line_starts[a_ctx_start],
                after_line_starts[a_ctx_end - 1] + len(after_lines[a_ctx_end - 1]),
            )
            if a_ctx_end > a_ctx_start
            else None
        )

        # Context lines
        b_diff_start = min(op[1] for op in cluster)
        b_diff_end = max(op[2] for op in cluster)
        leading_b_ctx = [line.rstrip("\r\n") for line in before_lines[b_ctx_start:b_diff_start]]
        trailing_b_ctx = [line.rstrip("\r\n") for line in before_lines[b_diff_end:b_ctx_end]]
        before_context = tuple(leading_b_ctx + trailing_b_ctx)

        a_diff_start = min(op[3] for op in cluster)
        a_diff_end = max(op[4] for op in cluster)
        leading_a_ctx = [line.rstrip("\r\n") for line in after_lines[a_ctx_start:a_diff_start]]
        trailing_a_ctx = [line.rstrip("\r\n") for line in after_lines[a_diff_end:a_ctx_end]]
        after_context = tuple(leading_a_ctx + trailing_a_ctx)

        block_key = (
            f"{change_kind}:{b_ctx_start}-{b_ctx_end}:"
            f"{a_ctx_start}-{a_ctx_end}:{before_slice}:{after_slice}"
        )
        block_id = f"block:{hashlib.sha256(block_key.encode('utf-8')).hexdigest()[:16]}"

        result_blocks.append(
            ChangedBlock(
                block_id=block_id,
                change_kind=change_kind,
                before_line_range=(b_ctx_start + 1, b_ctx_end) if b_ctx_end > b_ctx_start else None,
                after_line_range=(a_ctx_start + 1, a_ctx_end) if a_ctx_end > a_ctx_start else None,
                before_char_range=before_char_range,
                after_char_range=after_char_range,
                before_context=before_context,
                after_context=after_context,
                before_content=before_slice,
                after_content=after_slice,
            )
        )

    return BlockOutcome(
        status="ok",
        blocks=tuple(result_blocks),
        total_blocks=len(result_blocks),
    )
