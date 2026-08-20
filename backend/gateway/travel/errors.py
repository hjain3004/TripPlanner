"""Typed travel gateway errors — spec 16 §13.

Reuses the existing ``redact_secret`` utility from ``gateway.places.registry``
(a generic string-scrubbing helper, not a places-specific object) so secrets
are stripped from error messages consistently across both gateway packages.
"""

from __future__ import annotations

from typing import Literal

from gateway.places.registry import redact_secret

ErrorCode = Literal[
    "provider_unavailable",
    "authentication_failed",
    "permission_denied",
    "rate_limited",
    "budget_exhausted",
    "timeout",
    "invalid_response",
    "no_results",
    "unsupported_domain",
    "region_restricted",
    "terms_disabled",
]


class TravelGatewayError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        sanitized = redact_secret(message)
        super().__init__(sanitized)
        self.code = code
        self.message = sanitized

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"TravelGatewayError(code={self.code!r}, message={self.message!r})"
