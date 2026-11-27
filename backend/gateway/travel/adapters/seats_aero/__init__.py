"""Seats.aero anonymous read-only MCP adapter (cached award availability)."""

from __future__ import annotations

from gateway.travel.adapters.seats_aero.adapter import SeatsAeroAdapter
from gateway.travel.adapters.seats_aero.tool_policy import ALLOWED_TOOLS, DENIED_TOOLS

__all__ = ["ALLOWED_TOOLS", "DENIED_TOOLS", "SeatsAeroAdapter"]
