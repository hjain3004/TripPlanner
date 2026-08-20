from __future__ import annotations

from typing import Literal

ErrorCode = Literal["invalid_response"]


class FxImportError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
