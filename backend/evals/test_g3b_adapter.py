"""The adapter is off by default, spends a bounded budget, never retries, and falls back."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from core.db import SEEDS_DIR, load_kb, seed_database
from evals.g3b_support import NOW, request
from gateway.travel.adapters.openbnb.adapter import OpenBnBAdapter, OpenBnBCircuitBreaker
from gateway.travel.adapters.openbnb.budget import OpenBnBBudgetUnavailableError, OpenBnBCallBudget
from gateway.travel.adapters.openbnb.fixture_transport import (
    FixtureOpenBnBTransport,
    OpenBnBToolResult,
)
from gateway.travel.adapters.sample import SampleAdapter
from gateway.travel.contracts import (
    AwardSearchRequest,
    FlexibleFlightSearchRequest,
    FlightSearchRequest,
    TravelerMix,
)
from gateway.travel.errors import TravelGatewayError
from gateway.travel.registry import TravelProviderRegistry, get_default_travel_registry
from gateway.travel.service import TravelInventoryService


def _transport(fixture: str = "search_success") -> FixtureOpenBnBTransport:
    return FixtureOpenBnBTransport({"airbnb_search": fixture}, now=lambda: NOW)


def _adapter(
    transport: Any = None,
    *,
    enabled: bool = True,
    budget: OpenBnBCallBudget | None = None,
    plan: str = "plan-1",
    **kwargs: Any,
) -> OpenBnBAdapter:
    return OpenBnBAdapter(
        transport=transport if transport is not None else _transport(),
        budget=budget or OpenBnBCallBudget(),
        plan_id=plan,
        now=lambda: NOW,
        enabled=enabled,
        **kwargs,
    )


class _Counting:
    """A transport that records calls and can fail, hang or overlap-check."""

    def __init__(self, *, fail: TravelGatewayError | None = None, delay: float = 0.0) -> None:
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self._fail = fail
        self._delay = delay
        self._inner = _transport()

    async def call_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> OpenBnBToolResult:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            if self._fail:
                raise self._fail
            return await self._inner.call_tool(tool_name, arguments)
        finally:
            self.active -= 1


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Disabled by default
# --------------------------------------------------------------------------- #


def test_the_adapter_is_disabled_unless_explicitly_enabled() -> None:
    transport = _Counting()
    budget = OpenBnBCallBudget()
    adapter = OpenBnBAdapter(transport=transport, budget=budget, plan_id="p", now=lambda: NOW)
    with pytest.raises(TravelGatewayError) as raised:
        _run(adapter.search_hotels(request()))
    assert raised.value.code == "provider_unavailable"
    assert transport.calls == 0 and budget.calls_used("p") == 0


def test_an_enabled_adapter_without_a_transport_still_fails_closed() -> None:
    adapter = OpenBnBAdapter(
        transport=None, budget=OpenBnBCallBudget(), plan_id="p", now=lambda: NOW, enabled=True
    )
    with pytest.raises(TravelGatewayError) as raised:
        _run(adapter.search_hotels(request()))
    assert raised.value.code == "provider_unavailable"


def test_capabilities_state_the_experimental_scraper_nature() -> None:
    caps = OpenBnBAdapter.capabilities
    assert caps.provider_id == "openbnb"
    assert caps.domains == {"hotel"}
    assert caps.source_method == "scraper_wrapper"
    assert caps.stability == "experimental"
    assert caps.allowed_profiles == {"student_noncommercial"}
    assert caps.requires_user_initiated_search is True
    assert caps.supports_commercial_use is False and caps.supports_cache is False
    assert caps.live_data is False and caps.max_concurrency == 1


@pytest.mark.parametrize("method", ["flights", "trends", "awards"])
def test_every_other_domain_is_unsupported(method: str) -> None:
    adapter = _adapter()
    travelers = TravelerMix(adults=1)
    from datetime import date

    with pytest.raises(TravelGatewayError) as raised:
        if method == "flights":
            _run(
                adapter.search_flights(
                    FlightSearchRequest(
                        origin="DEL",
                        destination="SIN",
                        depart_date=date(2026, 11, 10),
                        travelers=travelers,
                        cabin="economy",
                        currency="INR",
                    )
                )
            )
        elif method == "trends":
            _run(
                adapter.search_flight_price_trends(
                    FlexibleFlightSearchRequest(
                        origin="DEL",
                        destination="SIN",
                        depart_window_start=date(2026, 11, 10),
                        depart_window_end=date(2026, 11, 12),
                        travelers=travelers,
                        cabin="economy",
                        currency="INR",
                        max_date_pairs=1,
                    )
                )
            )
        else:
            _run(
                adapter.search_awards(
                    AwardSearchRequest(
                        origin="DEL",
                        destination="SIN",
                        depart_date=date(2026, 11, 10),
                        travelers=travelers,
                        cabin="economy",
                    )
                )
            )
    assert raised.value.code == "unsupported_domain"


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #


def test_search_returns_priced_quotes_and_reports_discovery_only_rows_separately() -> None:
    adapter = _adapter()
    outcome = _run(adapter.search_rental_stays(request()))
    assert [q.evidence.provider_quote_id for q in outcome.quotes] == ["12345678", "34567890"]
    assert [row.reason for row in outcome.incomplete] == ["price_nightly_only"]
    assert outcome.incomplete[0].advertised_nightly_minor == 11_000
    complete, partial = outcome.quotes
    assert complete.evidence.completeness == "complete"
    assert partial.evidence.completeness == "partial"
    assert all(q.evidence.status == "verify_required" for q in outcome.quotes)
    assert all(q.evidence.needs_verification for q in outcome.quotes)
    assert all("origin=synthetic_fixture" in " ".join(q.evidence.notes) for q in outcome.quotes)


def test_search_hotels_returns_only_the_priced_quotes() -> None:
    quotes = _run(_adapter().search_hotels(request()))
    assert len(quotes) == 2 and all(q.total_minor > 0 for q in quotes)


def test_a_valid_empty_search_is_success_with_zero_quotes() -> None:
    assert _run(_adapter(_transport("search_empty")).search_hotels(request())) == []


def test_a_nightly_only_search_yields_no_priced_quote() -> None:
    outcome = _run(_adapter(_transport("search_nightly_only")).search_rental_stays(request()))
    assert outcome.quotes == [] and outcome.incomplete[0].reason == "price_nightly_only"


def test_a_hostile_listing_title_is_redacted_end_to_end() -> None:
    (quote,) = _run(_adapter(_transport("search_prompt_injection")).search_hotels(request()))
    assert "Ignore previous" not in quote.model_dump_json()
    assert quote.name.startswith("[redacted")


@pytest.mark.parametrize(
    ("fixture", "code"),
    [
        ("search_robots_blocked", "permission_denied"),
        ("search_upstream_timeout", "timeout"),
        ("search_structure_changed", "invalid_response"),
        ("search_dates_mismatch", "invalid_response"),
        ("search_malformed", "invalid_response"),
        ("error_rate_limited", "rate_limited"),
        ("error_timeout", "timeout"),
    ],
)
def test_every_failure_fixture_raises_its_typed_error(fixture: str, code: str) -> None:
    with pytest.raises(TravelGatewayError) as raised:
        _run(_adapter(_transport(fixture)).search_hotels(request()))
    assert raised.value.code == code


# --------------------------------------------------------------------------- #
# Bounds
# --------------------------------------------------------------------------- #


def test_unsupported_requests_spend_no_budget_and_never_dispatch() -> None:
    transport, budget = _Counting(), OpenBnBCallBudget()
    adapter = _adapter(transport, budget=budget)
    for bad in (request(rooms=2), request(property_kinds={"hotel"}), request(area_ids=["x"])):
        with pytest.raises(TravelGatewayError) as raised:
            _run(adapter.search_hotels(bad))
        assert raised.value.code == "unsupported_domain"
    assert transport.calls == 0 and budget.calls_used("plan-1") == 0
    assert adapter.consecutive_failures == 0


def test_the_per_plan_budget_is_two_calls_then_exhausted() -> None:
    transport, budget = _Counting(), OpenBnBCallBudget()
    adapter = _adapter(transport, budget=budget)
    _run(adapter.search_hotels(request()))
    _run(adapter.search_hotels(request()))
    with pytest.raises(TravelGatewayError) as raised:
        _run(adapter.search_hotels(request()))
    assert raised.value.code == "budget_exhausted"
    assert transport.calls == 2
    other_plan = _adapter(transport, budget=budget, plan="plan-2")
    _run(other_plan.search_hotels(request()))
    assert transport.calls == 3


def test_a_failed_call_still_spends_its_reservation() -> None:
    budget = OpenBnBCallBudget()
    adapter = _adapter(
        _Counting(fail=TravelGatewayError("provider_unavailable", "x")), budget=budget
    )
    with pytest.raises(TravelGatewayError):
        _run(adapter.search_hotels(request()))
    assert budget.calls_used("plan-1") == 1


def test_there_are_no_retries_even_for_a_transient_failure() -> None:
    transport = _Counting(fail=TravelGatewayError("provider_unavailable", "5xx"))
    with pytest.raises(TravelGatewayError):
        _run(_adapter(transport).search_hotels(request()))
    assert transport.calls == 1


def test_a_hung_call_times_out_and_counts_as_a_failure() -> None:
    adapter = _adapter(_Counting(delay=1.0), call_timeout_s=0.05)
    with pytest.raises(TravelGatewayError) as raised:
        _run(adapter.search_hotels(request()))
    assert raised.value.code == "timeout"
    assert adapter.consecutive_failures == 1


def test_the_circuit_opens_after_repeated_failures_and_stops_dispatching() -> None:
    transport = _Counting(fail=TravelGatewayError("provider_unavailable", "down"))
    budget = OpenBnBCallBudget(calls_per_plan=10)
    adapter = _adapter(transport, budget=budget, circuit_breaker=OpenBnBCircuitBreaker())
    for _ in range(2):
        with pytest.raises(TravelGatewayError):
            _run(adapter.search_hotels(request()))
    with pytest.raises(TravelGatewayError) as raised:
        _run(adapter.search_hotels(request()))
    assert "circuit breaker" in str(raised.value)
    assert transport.calls == 2 and budget.calls_used("plan-1") == 2


def test_a_success_resets_the_failure_streak() -> None:
    adapter = _adapter(
        _transport("search_dates_mismatch"), budget=OpenBnBCallBudget(calls_per_plan=9)
    )
    with pytest.raises(TravelGatewayError):
        _run(adapter.search_hotels(request()))
    assert adapter.consecutive_failures == 1
    good = _adapter(_transport(), budget=OpenBnBCallBudget(calls_per_plan=9))
    _run(good.search_hotels(request()))
    assert good.consecutive_failures == 0


def test_a_malformed_response_counts_toward_the_breaker() -> None:
    adapter = _adapter(_transport("search_malformed"))
    with pytest.raises(TravelGatewayError):
        _run(adapter.search_hotels(request()))
    assert adapter.consecutive_failures == 1


def test_concurrent_searches_never_overlap() -> None:
    transport = _Counting(delay=0.02)
    adapter = _adapter(transport, budget=OpenBnBCallBudget(calls_per_plan=9))

    async def both() -> None:
        await asyncio.gather(adapter.search_hotels(request()), adapter.search_hotels(request()))

    asyncio.run(both())
    assert transport.calls == 2 and transport.max_active == 1


def test_an_unavailable_ledger_fails_soft_and_dispatches_nothing() -> None:
    class Broken(OpenBnBCallBudget):
        def reserve_call(self, plan_id: str) -> bool:
            raise OpenBnBBudgetUnavailableError("locked")

    transport = _Counting()
    with pytest.raises(TravelGatewayError) as raised:
        _run(_adapter(transport, budget=Broken()).search_hotels(request()))
    assert raised.value.code == "provider_unavailable"
    assert transport.calls == 0


# --------------------------------------------------------------------------- #
# Details
# --------------------------------------------------------------------------- #


def test_details_enrich_coordinates_using_the_second_budgeted_call() -> None:
    transport = FixtureOpenBnBTransport(
        {"airbnb_search": "search_success", "airbnb_listing_details": "details_success"},
        now=lambda: NOW,
    )
    budget = OpenBnBCallBudget()
    adapter = _adapter(transport, budget=budget)
    (first, _) = _run(adapter.search_hotels(request()))
    enriched = _run(adapter.enrich_with_coordinates(first, request()))
    assert (enriched.lat, enriched.lon) == (1.3112, 103.8631)
    assert enriched.total_minor == first.total_minor
    assert budget.calls_used("plan-1") == 2
    with pytest.raises(TravelGatewayError) as raised:
        _run(adapter.enrich_with_coordinates(first, request()))
    assert raised.value.code == "budget_exhausted"


def test_enriching_a_non_openbnb_quote_is_refused_before_any_call() -> None:
    transport = _Counting()
    adapter = _adapter(transport)
    quote = _run(adapter.search_hotels(request()))[0]
    foreign = quote.model_copy(update={"property_id": "sample:1"})
    transport.calls = 0
    with pytest.raises(TravelGatewayError) as raised:
        _run(adapter.enrich_with_coordinates(foreign, request()))
    assert raised.value.code == "invalid_response" and transport.calls == 0


# --------------------------------------------------------------------------- #
# Sample fallback through the real inventory service
# --------------------------------------------------------------------------- #


def _service(tmp_path: Path, openbnb: OpenBnBAdapter) -> TravelInventoryService:
    from gateway.travel.adapters.openbnb.registry import build_openbnb_registry_entry

    db = tmp_path / "t.sqlite"
    seed_database(SEEDS_DIR, db)
    sample = SampleAdapter(load_kb(db), now=lambda: datetime(2026, 10, 26, tzinfo=UTC))
    base = get_default_travel_registry()
    entry = build_openbnb_registry_entry({"TRIPWISE_OPENBNB_ENABLED": "1"})
    registry = TravelProviderRegistry(
        entries=[e for e in base.entries if e.provider_id == "sample_travel_adapter"] + [entry]
    )
    return TravelInventoryService(
        registry=registry,
        adapters={"sample_travel_adapter": sample, "openbnb": openbnb},
        plan_id="plan-1",
        country="SG",
        now=lambda: datetime(2026, 10, 26, tzinfo=UTC),
    )


def _flight() -> FlightSearchRequest:
    from datetime import date

    return FlightSearchRequest(
        origin="DEL",
        destination="SIN",
        depart_date=date(2026, 11, 10),
        return_date=date(2026, 11, 13),
        travelers=TravelerMix(adults=2),
        cabin="economy",
        currency="INR",
    )


def test_when_openbnb_fails_the_sample_adapter_still_supplies_hotels(tmp_path: Path) -> None:
    failing = _adapter(_Counting(fail=TravelGatewayError("provider_unavailable", "down")))
    snapshot = _run(
        _service(tmp_path, failing).search(
            _flight(), request(currency="INR", style="balanced"), domains={"hotel"}
        )
    )
    assert snapshot.hotels, "the sample fallback must still provide hotel evidence"
    assert all(h.evidence.provider_id.startswith("sample_") for h in snapshot.hotels)
    assert any(
        d.code == "provider_unavailable" and d.provider_id == "openbnb"
        for d in snapshot.diagnostics
    )


def test_openbnb_quotes_in_a_different_currency_are_never_silently_accepted(tmp_path: Path) -> None:
    working = _adapter(_transport())
    snapshot = _run(
        _service(tmp_path, working).search(
            _flight(), request(currency="INR", style="balanced"), domains={"hotel"}
        )
    )
    assert all(not h.evidence.provider_id == "openbnb" for h in snapshot.hotels)
    assert any(d.code == "mismatched_response" for d in snapshot.diagnostics)
    assert snapshot.hotels  # and the fallback still supplies a result


def test_an_accepted_openbnb_quote_is_never_a_verified_price_scope(tmp_path: Path) -> None:
    working = _adapter(_transport())
    snapshot = _run(
        _service(tmp_path, working).search(
            _flight(), request(currency="USD", style="balanced"), domains={"hotel"}
        )
    )
    openbnb_quotes = [h for h in snapshot.hotels if h.evidence.provider_id == "openbnb"]
    assert openbnb_quotes
    for quote in openbnb_quotes:
        scope = snapshot.hotel_scopes[quote.id]
        assert scope.scope_verified is False
        assert quote.evidence.status == "verify_required"
    partial = next(q for q in openbnb_quotes if q.evidence.completeness == "partial")
    assert snapshot.hotel_scopes[partial.id].basis == "unknown"
