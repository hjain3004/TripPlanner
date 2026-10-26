"""Link validation for OpenBnB output.

Upstream builds every URL as ``https://www.airbnb.com/rooms/<id>`` (listings) or
``https://www.airbnb.com/s/<slug>/homes?...`` (searches), where ``<id>`` is decoded from a
base64 global id with no validation of its own (upstream issue #54: truncated ids yield
``/rooms/undefined``). A link is therefore used only if it is exactly that shape for the
exact listing id the result itself carries; anything else is dropped, never repaired.
"""

from __future__ import annotations

import re
from urllib.parse import SplitResult, parse_qsl, urlsplit

from gateway.travel.adapters.openbnb.tool_policy import LISTING_ID_PATTERN

ALLOWED_HOSTS: frozenset[str] = frozenset({"www.airbnb.com", "airbnb.com"})
MAX_URL_CHARS = 2048
MAX_QUERY_FIELDS = 50
_LISTING_PATH = re.compile(r"/rooms/([0-9]{1,20})")
_SEARCH_PATH = re.compile(r"/s/[^/\s]{1,200}/homes")


def _safe_parts(url: object) -> SplitResult | None:
    if not isinstance(url, str) or not url or len(url) > MAX_URL_CHARS:
        return None
    # Printable ASCII only: rejects whitespace, controls and non-ASCII (IDN look-alikes).
    if any(ord(ch) <= 32 or ord(ch) >= 127 for ch in url) or "\\" in url:
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if (
        parts.scheme != "https"
        or parts.username is not None
        or parts.password is not None
        or port is not None
        or parts.hostname not in ALLOWED_HOSTS
        or parts.netloc != parts.hostname
    ):
        return None
    return parts


def validated_listing_url(url: object, expected_id: str) -> str | None:
    """The URL itself iff it is exactly the listing page for ``expected_id``."""
    if not LISTING_ID_PATTERN.fullmatch(expected_id):
        return None
    parts = _safe_parts(url)
    if parts is None or parts.query or parts.fragment:
        return None
    match = _LISTING_PATH.fullmatch(parts.path)
    if match is None or match.group(1) != expected_id:
        return None
    assert isinstance(url, str)
    return url


def parse_search_url(url: object) -> dict[str, str] | None:
    """Query parameters of an Airbnb search URL, or ``None`` if it is not one.

    A repeated key is ambiguous (which value did the provider apply?) and rejects the URL.
    """
    parts = _safe_parts(url)
    if parts is None or parts.fragment or _SEARCH_PATH.fullmatch(parts.path) is None:
        return None
    try:
        pairs = parse_qsl(parts.query, keep_blank_values=True, max_num_fields=MAX_QUERY_FIELDS)
    except ValueError:
        return None
    result: dict[str, str] = {}
    for key, value in pairs:
        if key in result:
            return None
        result[key] = value
    return result
