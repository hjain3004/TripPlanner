"""Sanitizer for every provider free-text field before it can reach another
component (G4).

Best-effort, not a formal guarantee — no substring sanitizer catches every
adversarial rephrasing. The design therefore leans on *not accepting* free
text at all: weather payloads are numeric, strings that must be identifiers
(timezone, units) are validated against strict patterns, and the only
free-text field that survives normalization (the provider's advisory
``notice``) passes through here and is length-bounded.

Order matters: ANSI escapes and control/format characters are removed *before*
marker matching so ``ig\\x00nore previous`` cannot evade it; NFKC folding and
whitespace collapsing close the fullwidth/spacing bypasses.
"""

from __future__ import annotations

import re
import unicodedata

MAX_TEXT_CHARS = 200

_INJECTION_MARKERS = (
    "ignore previous",
    "ignore all previous",
    "ignore the above",
    "disregard all prior",
    "disregard previous",
    "disregard the above",
    "forget your instructions",
    "system:",
    "assistant:",
    "new instructions",
    "you are now",
    "reveal your system prompt",
    "<|im_start|>",
)
REDACTED = "[redacted: provider text contained a suspected prompt-injection marker]"

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_URL_RE = re.compile(r"(?i)\b(?:https?|ftp)://\S+")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_control(text: str) -> str:
    return "".join(
        ch for ch in text if ch in "\t\n\r " or not unicodedata.category(ch).startswith("C")
    )


def sanitize_provider_text(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = _ANSI_RE.sub("", text)
    cleaned = unicodedata.normalize("NFKC", cleaned)
    cleaned = _strip_control(cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    folded = cleaned.casefold()
    if any(marker in folded for marker in _INJECTION_MARKERS):
        return REDACTED
    cleaned = _URL_RE.sub("[link removed]", cleaned)
    cleaned = cleaned.replace("<", "").replace(">", "")
    return cleaned[:MAX_TEXT_CHARS]
