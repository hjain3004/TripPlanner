"""Locations of mutable runtime state.

By default state stays exactly where it always was (next to the code), so
development and the test suite are unchanged. A deployment sets
``TRIPWISE_DATA_DIR`` to one explicit directory and every mutable store - the
seeded knowledge base, the accounts/planning database and the pipeline traces -
moves there, which lets the application code itself stay read-only.

Standard library only: ``core`` never imports anything else.
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR_ENV = "TRIPWISE_DATA_DIR"


def data_dir() -> Path | None:
    """The configured data directory, or None when state stays next to the code."""
    raw = os.environ.get(DATA_DIR_ENV, "").strip()
    return Path(raw) if raw else None


def state_path(name: str, default: Path) -> Path:
    root = data_dir()
    return root / name if root is not None else default
