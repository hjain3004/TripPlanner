"""Trivago anonymous read-only MCP adapter (hotel & accommodation metasearch)."""

from __future__ import annotations

from gateway.travel.adapters.trivago.adapter import TrivagoAdapter
from gateway.travel.adapters.trivago.tool_policy import ALLOWED_TOOLS, DENIED_TOOLS

__all__ = ["ALLOWED_TOOLS", "DENIED_TOOLS", "TrivagoAdapter"]
