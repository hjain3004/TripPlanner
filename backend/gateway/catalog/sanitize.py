from __future__ import annotations

import re
import unicodedata

MAX_TEXT_LEN = 2000

_TAG_RE = re.compile(r"<[^>]*>")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]")
_PROMPT_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?", re.I),
    re.compile(r"^\s*(system|assistant|user)\s*:", re.I | re.M),
    re.compile(r"\[\[?/?INST\]\]?", re.I),
    re.compile(r"<\|.*?\|>", re.S),
    re.compile(r"developer\s+mode", re.I),
]
_ALLOWED_SCHEMES = ("http://", "https://")


def sanitize_text(raw: str) -> str:
    """Strip active markup, control characters and prompt-like control text.

    Idempotent by construction: every rule removes, none rewrites into a form
    another rule would match. Build determinism (Task 10) depends on this.
    """
    text = unicodedata.normalize("NFC", raw)
    text = _TAG_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    for pattern in _PROMPT_PATTERNS:
        text = pattern.sub("", text)
    # Collapse the whitespace the removals leave behind, deterministically.
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text[:MAX_TEXT_LEN]


def sanitize_url(raw: str) -> str | None:
    candidate = raw.strip()
    if not candidate.lower().startswith(_ALLOWED_SCHEMES):
        return None
    if _CONTROL_RE.search(candidate):
        return None
    return candidate
