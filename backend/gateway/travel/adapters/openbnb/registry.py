"""Registry entry and enable gate for OpenBnB -- deliberately NOT in the default registry.

``gateway.travel.registry.get_default_travel_registry`` is unchanged: it has no OpenBnB
entry, so no code path selects this adapter. A future, separately approved milestone may
add the entry returned here. Until then the entry exists so its shape (domain, profile,
source method, priority, zero cost) is reviewed and tested.

Activation order mirrors Gondola's: the kill switch is read once, at construction, and it
wins over the enable flag.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import datetime

from gateway.travel.adapters.openbnb.adapter import OpenBnBAdapter, OpenBnBCircuitBreaker
from gateway.travel.adapters.openbnb.budget import OpenBnBCallBudget
from gateway.travel.adapters.openbnb.fixture_transport import OpenBnBTransport
from gateway.travel.registry import TravelProviderRegistryEntry

ENABLE_ENV = "TRIPWISE_OPENBNB_ENABLED"
KILL_SWITCH_ENV = "TRIPWISE_OPENBNB_KILL_SWITCH"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _flag(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in _TRUTHY


def openbnb_enabled(env: Mapping[str, str] | None = None) -> bool:
    """True only if the enable flag is set and the kill switch is not."""
    source = os.environ if env is None else env
    if _flag(source, KILL_SWITCH_ENV):
        return False
    return _flag(source, ENABLE_ENV)


def build_openbnb_registry_entry(
    env: Mapping[str, str] | None = None,
) -> TravelProviderRegistryEntry:
    return TravelProviderRegistryEntry(
        provider_id="openbnb",
        enabled=openbnb_enabled(env),
        allowed_profiles={"student_noncommercial"},
        domains={"hotel"},
        countries="configured",
        source_method="scraper_wrapper",
        live_data=False,
        monthly_cost_minor=0,
        priority=800,  # after Gondola (500), before the sample fallback (999)
    )


def build_openbnb_adapter(
    *,
    transport: OpenBnBTransport | None,
    budget: OpenBnBCallBudget,
    plan_id: str,
    now: Callable[[], datetime],
    env: Mapping[str, str] | None = None,
    bare_dollar_currency: str | None = None,
    circuit_breaker: OpenBnBCircuitBreaker | None = None,
) -> OpenBnBAdapter:
    """An adapter whose ``enabled`` comes only from the flag/kill-switch pair."""
    return OpenBnBAdapter(
        transport=transport,
        budget=budget,
        plan_id=plan_id,
        now=now,
        enabled=openbnb_enabled(env),
        circuit_breaker=circuit_breaker,
        bare_dollar_currency=bare_dollar_currency,
    )
