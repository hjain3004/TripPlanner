"""Bounded, deterministic normalization of untrusted fetched material."""

from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser


class ContentLimitError(ValueError):
    pass


class UnsupportedContentError(ValueError):
    pass


class _VisibleTextParser(HTMLParser):
    _IGNORED = {"script", "style", "noscript", "template", "svg", "canvas"}
    _BLOCKS = {
        "article",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "main",
        "p",
        "section",
        "table",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._IGNORED:
            self._ignored += 1
        elif self._ignored == 0 and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._IGNORED and self._ignored:
            self._ignored -= 1
        elif self._ignored == 0 and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored == 0:
            self.parts.append(data)


def _normalize_lines(text: str, *, max_chars: int) -> str:
    normalized = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = "\n".join(line for line in normalized.split("\n") if line.strip())
    normalized = normalized.strip()
    if len(normalized) > max_chars:
        raise ContentLimitError(f"normalized content exceeds {max_chars} characters")
    return normalized


def canonicalize_markdown(text: str, *, max_chars: int) -> str:
    return _normalize_lines(html.unescape(text), max_chars=max_chars)


def canonicalize_html(data: bytes, *, max_chars: int) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise UnsupportedContentError("HTML must be valid UTF-8") from error
    parser = _VisibleTextParser()
    parser.feed(text)
    parser.close()
    return _normalize_lines("".join(parser.parts), max_chars=max_chars)


def canonicalize_content(data: bytes, *, media_type: str, max_chars: int) -> str:
    normalized_type = media_type.split(";", 1)[0].lower().strip()
    if normalized_type in {"text/html", "application/xhtml+xml"}:
        return canonicalize_html(data, max_chars=max_chars)
    if normalized_type in {"text/plain", "text/markdown", "text/csv"}:
        try:
            return canonicalize_markdown(data.decode("utf-8"), max_chars=max_chars)
        except UnicodeDecodeError as error:
            raise UnsupportedContentError("text content must be valid UTF-8") from error
    raise UnsupportedContentError(f"unsupported content type: {normalized_type}")
