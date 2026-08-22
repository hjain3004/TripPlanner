"""Shared prompt-injection sanitizer for Gondola provider free text.

Best-effort, not a formal guarantee — no substring sanitizer catches every
adversarial rephrasing. Applied uniformly to every provider free-text field
across both hotel and flight normalization (name, cancellation text,
review-adjacent notes, raw notes) so a future LLM call site never sees
unsanitized provider text from any Gondola result type.

Unicode NFKC normalization and whitespace collapsing run before matching,
closing the cheapest bypasses (fullwidth Unicode variants, extra internal
whitespace, embedded newlines) without materially increasing complexity.
"""

from __future__ import annotations

import re
import unicodedata

_INJECTION_MARKERS = (
    "ignore previous",
    "ignore all previous",
    "disregard all prior",
    "disregard previous",
    "system:",
    "new instructions",
    "you are now",
    "reveal your system prompt",
)
REDACTED = "[redacted: provider text contained a suspected prompt-injection marker]"

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_for_matching(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    collapsed = _WHITESPACE_RE.sub(" ", normalized)
    return collapsed.casefold()


def sanitize_provider_text(text: str | None) -> str | None:
    if text is None:
        return None
    normalized = _normalize_for_matching(text)
    if any(marker in normalized for marker in _INJECTION_MARKERS):
        return REDACTED
    return text
