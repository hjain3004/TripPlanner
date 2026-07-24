"""Deterministic rewards optimizer (spec 02).

Public entrypoint ``optimize`` — pure, no I/O beyond reads through the
``KnowledgeBase`` facade. Same input ⇒ byte-identical output.
"""

from __future__ import annotations

from core.db import KnowledgeBase
from core.models import CostedTrip, OptimizationPrefs, OptimizerResult, UserWallet
from core.optimizer.allocate import allocate
from core.optimizer.report import build_result

__all__ = ["optimize"]


def optimize(
    trip: CostedTrip,
    user: UserWallet,
    kb: KnowledgeBase,
    prefs: OptimizationPrefs | None = None,
) -> OptimizerResult:
    resolved = prefs or OptimizationPrefs()
    alloc = allocate(kb, trip, user, resolved)
    return build_result(kb, trip, user, alloc, resolved)
