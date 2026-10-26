"""Sanitizer for host-authored OpenBnB free text.

Listing titles, descriptions and badges are written by third-party hosts and relayed by a
community scraper: the most direct prompt-injection channel in the whole gateway. Every
such string passes through here before it can reach a model, a UI field or a note.

Best effort, not a guarantee -- a substring/regex sanitizer cannot catch every rephrasing
(letter-spaced or translated attacks, for example). It is one layer: provider text also
never drives a decision (no ranking, routing, tool choice or money value reads it), it is
length-bounded, and it is shown with a verification warning.

Order matters: normalize and strip invisible characters first so a marker cannot hide
behind width variants, zero-width characters or odd spacing, then match, then remove
markup and links, then bound.
"""

from __future__ import annotations

import re
import unicodedata

REDACTED = "[redacted: suspected prompt injection]"

_DROP_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Cn"})
_WHITESPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[\W_]+")
_ROLE_MARKER = re.compile(
    r"\b(?:system|assistant|developer)\s*:|\[/?inst\]|<\|[a-z_]+\|>|```", re.IGNORECASE
)
_PHRASES = re.compile(
    r"\bignore (?:all |any )?(?:the )?(?:previous|prior|above|earlier|preceding)\b"
    r"|\bdisregard\b.{0,40}\b(?:above|previous|prior|instructions?|rules)\b"
    r"|\bsystem prompt\b"
    r"|\bnew instructions?\b"
    r"|\byou are now\b"
    r"|\bdo not tell the user\b"
    r"|\breveal your\b"
    r"|\b(?:call|invoke|use|run|execute) (?:the )?\w+ tool\b"
    r"|\b(?:card|account|passport) number\b"
    r"|\bforward (?:everything|all)\b"
)
_MARKUP = re.compile(r"<[^>]*>")
_LINK = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def _strip_invisible(text: str, replacement: str = "") -> str:
    folded = _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text))
    return "".join(
        replacement if unicodedata.category(ch) in _DROP_CATEGORIES else ch for ch in folded
    )


def _is_injection(text: str) -> bool:
    if _ROLE_MARKER.search(text):
        return True
    words = _NON_WORD.sub(" ", text.casefold()).strip()
    return _PHRASES.search(words) is not None


def sanitize_text(text: str | None, *, max_chars: int) -> str | None:
    """Return bounded, markup-free text, ``REDACTED`` for injection, or ``None`` if empty."""
    if text is None:
        return None
    cleaned = _strip_invisible(text).strip()
    if not cleaned:
        return None
    # An invisible character can hide a marker either by splitting a word or by joining
    # two; test both readings.
    if _is_injection(cleaned) or _is_injection(_strip_invisible(text, " ")):
        return REDACTED[:max_chars]
    cleaned = _LINK.sub(" ", _MARKUP.sub("", cleaned))
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    if not cleaned:
        return None
    return cleaned[:max_chars].rstrip()
