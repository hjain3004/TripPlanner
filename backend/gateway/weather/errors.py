"""Typed weather-context gateway errors.

Deliberately separate from ``gateway.travel.errors``: weather is contextual
evidence, not travel inventory, and must not widen the travel error taxonomy.
Messages pass through the shared ``redact_secret`` scrubber, and no provider
free text is ever placed in an error message — only field names and fixed
phrases — so an error can never smuggle provider prose into logs or outcomes.
"""

from __future__ import annotations

from typing import Literal

from gateway.places.registry import redact_secret

ErrorCode = Literal[
    "provider_disabled",
    "provider_unavailable",
    "permission_denied",
    "rate_limited",
    "budget_exhausted",
    "timeout",
    "invalid_response",
    "invalid_request",
]


class WeatherGatewayError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        sanitized = redact_secret(message)
        super().__init__(sanitized)
        self.code = code
        self.message = sanitized

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"WeatherGatewayError(code={self.code!r}, message={self.message!r})"
