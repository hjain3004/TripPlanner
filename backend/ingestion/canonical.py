"""Bounded, deterministic normalization of untrusted fetched material."""

from __future__ import annotations

import asyncio
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


def is_pdf_media_type(media_type: str) -> bool:
    return media_type.split(";", 1)[0].lower().strip() == "application/pdf"


def canonicalize_pdf(
    data: bytes, *, max_chars: int, max_pages: int, timeout_seconds: float | None = None
) -> str:
    """Parse a PDF in a killable child process (see ``ingestion.pdf_isolation``).

    Raises ``TimeoutError`` if the deadline passes; the parser is already dead and reaped
    when that happens. Imported lazily because the isolation module imports this one.
    """
    from ingestion.pdf_isolation import get_default_runner

    return get_default_runner().canonicalize(
        data, max_chars=max_chars, max_pages=max_pages, timeout_seconds=timeout_seconds
    )


async def acanonicalize_pdf(
    data: bytes, *, max_chars: int, max_pages: int, timeout_seconds: float | None = None
) -> str:
    """Async twin of ``canonicalize_pdf``; caller cancellation also kills the child."""
    from ingestion.pdf_isolation import get_default_runner

    return await get_default_runner().acanonicalize(
        data, max_chars=max_chars, max_pages=max_pages, timeout_seconds=timeout_seconds
    )


def canonicalize_content(
    data: bytes,
    *,
    media_type: str,
    max_chars: int,
    max_pages: int = 1,
    pdf_timeout_seconds: float | None = None,
) -> str:
    normalized_type = media_type.split(";", 1)[0].lower().strip()
    if normalized_type in {"text/html", "application/xhtml+xml"}:
        return canonicalize_html(data, max_chars=max_chars)
    if normalized_type in {"text/plain", "text/markdown", "text/csv"}:
        try:
            return canonicalize_markdown(data.decode("utf-8"), max_chars=max_chars)
        except UnicodeDecodeError as error:
            raise UnsupportedContentError("text content must be valid UTF-8") from error
    if normalized_type == "application/pdf":
        return canonicalize_pdf(
            data, max_chars=max_chars, max_pages=max_pages, timeout_seconds=pdf_timeout_seconds
        )
    raise UnsupportedContentError(f"unsupported content type: {normalized_type}")


async def acanonicalize_content(
    data: bytes,
    *,
    media_type: str,
    max_chars: int,
    max_pages: int = 1,
    timeout_seconds: float | None = None,
) -> str:
    """Normalize without blocking the event loop, bounded by ``timeout_seconds``.

    PDFs use the killable child process. Other types keep their existing behaviour: a worker
    thread under ``wait_for``, which is safe because those parsers are pure and bounded.
    """
    if is_pdf_media_type(media_type):
        return await acanonicalize_pdf(
            data, max_chars=max_chars, max_pages=max_pages, timeout_seconds=timeout_seconds
        )
    work = asyncio.to_thread(
        canonicalize_content, data, media_type=media_type, max_chars=max_chars, max_pages=max_pages
    )
    if timeout_seconds is None:
        return await work
    return await asyncio.wait_for(work, timeout=timeout_seconds)
