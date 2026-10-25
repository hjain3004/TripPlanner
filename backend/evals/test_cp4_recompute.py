"""CP4 Task 1 — a confirmed recompute derives every number from the admitted cost lines.

The defect this guards: ``recompute_confirmed_session`` ran the legacy recompute (which
costs the *seed* flight and hotel and runs the kernel on them) and only afterwards
replaced the flight/hotel lines with the admitted ones. Totals, payment allocations and
transfer advice were therefore computed from prices the user never saw. The tests use
admitted amounts that differ materially from the seeds, so a fallback to seed prices
cannot pass by accident.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

import api.main as api_main
from agents.estimator import estimate_costed_trip
from agents.explainer import _payment_rows, _template_explainer, _totals, build_final_report
from agents.kernel import run_kernel
from agents.models import (
    DraftItinerary,
    EstimatorResult,
    FinalReport,
    ItineraryDay,
    ItineraryItem,
    SectionState,
)
from agents.retrieval import retrieve_candidates
from api.job_manager import job_manager
from api.main import app
from core.db import SEEDS_DIR, KnowledgeBase, load_kb, seed_database
from core.models import Channel, SpendCategory, SpendLineItem, UserWallet
from core.trip_models import AddItem, RemoveItem, TripSpec
from evals.a4_support import PlanningKit, csrf, finished_plan, signed_in_client

BOOKING = date(2026, 7, 25)
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
RICH_WALLET = UserWallet(
    card_ids=["hdfc-infinia", "axis-atlas"], points_balances={"voyager-prime": 140000}
)


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _kb(tmp_path: Path) -> KnowledgeBase:
    db_path = tmp_path / "tripwise.sqlite"
    seed_database(SEEDS_DIR, db_path)
    return load_kb(db_path)


def _spec(wallet: UserWallet = RICH_WALLET) -> TripSpec:
    return TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        travelers=2,
        budget_minor=25000000,
        budget_currency="INR",
        style="balanced",
        interests=["nature", "food"],
        wallet=wallet,
    )


def _itinerary() -> DraftItinerary:
    return DraftItinerary(
        hotel_area_id="marina_bay",
        days=[
            ItineraryDay(
                date=date(2026, 8, 1),
                items=[
                    ItineraryItem(poi_id="sg-gardens-by-the-bay"),
                    ItineraryItem(poi_id="sg-hawker-maxwell"),
                ],
            ),
            ItineraryDay(date=date(2026, 8, 2), items=[]),
            ItineraryDay(date=date(2026, 8, 3), items=[]),
            ItineraryDay(date=date(2026, 8, 4), items=[]),
        ],
    )


def seed_report(kb: KnowledgeBase, spec: TripSpec | None = None) -> FinalReport:
    """A kernel-consistent report priced from the seeds (what the legacy path produces)."""
    spec = spec or _spec()
    itinerary = _itinerary()
    estimate = estimate_costed_trip(spec, itinerary, kb, booking_date=BOOKING)
    kernel = run_kernel(spec, estimate, kb, booking_date=BOOKING)
    return build_final_report(
        spec,
        itinerary,
        estimate,
        kernel,
        retrieve_candidates(spec, kb),
        critic_caveats=[],
        explainer=_template_explainer(kernel),
        trace_id="trace-seed",
    )


def with_admitted_prices(
    report: FinalReport,
    kb: KnowledgeBase,
    *,
    flight_factor: int = 3,
    hotel_factor: int = 2,
    flight_channels: list[Channel] | None = None,
    drop_hotel: bool = False,
) -> FinalReport:
    """The same report, re-priced as if provider evidence had been admitted.

    The kernel is re-run on the new lines, so the result is internally consistent: it is
    the report a real confirmed plan holds *before* any edit.
    """
    lines: list[SpendLineItem] = []
    for line in report.costed_trip.lines:
        if line.category is SpendCategory.FLIGHTS:
            lines.append(
                line.model_copy(
                    update={
                        "amount_minor": line.amount_minor * flight_factor,
                        "available_channels": flight_channels or line.available_channels,
                    }
                )
            )
        elif line.category is SpendCategory.HOTELS:
            if not drop_hotel:
                lines.append(
                    line.model_copy(update={"amount_minor": line.amount_minor * hotel_factor})
                )
        else:
            lines.append(line)
    estimate = EstimatorResult(
        costed_trip=report.costed_trip.model_copy(update={"lines": lines}),
        flight=report.flights_pick,
        hotel=None if drop_hotel else report.hotel_pick,
        assumptions=["Admitted evidence assumption retained across edits."],
    )
    kernel = run_kernel(
        report.trip_spec, estimate, kb, booking_date=report.costed_trip.booking_date
    )
    rebuilt = build_final_report(
        report.trip_spec,
        report.itinerary,
        estimate,
        kernel,
        retrieve_candidates(report.trip_spec, kb),
        critic_caveats=list(report.caveats),
        explainer=_template_explainer(kernel),
        trace_id=report.trace_id,
        region_capability=report.region_capability,
        freshness=report.freshness,
    )
    return rebuilt.model_copy(update={"travel_inventory": report.travel_inventory})


def assert_kernel_consistent(report: FinalReport, kb: KnowledgeBase) -> None:
    """Every derived number equals a fresh kernel run over the report's own cost lines."""
    estimate = EstimatorResult(
        costed_trip=report.costed_trip, flight=report.flights_pick, hotel=report.hotel_pick
    )
    kernel = run_kernel(
        report.trip_spec, estimate, kb, booking_date=report.costed_trip.booking_date
    )
    assert report.optimizer_result == kernel.optimizer_result
    assert report.transfer_advice == kernel.transfer_advice
    assert report.budget_totals == _totals(kernel.optimizer_result)
    assert report.payment_strategy == _payment_rows(kernel.optimizer_result.assignments)


def _lines(report: FinalReport, category: SpendCategory) -> list[SpendLineItem]:
    return [line for line in report.costed_trip.lines if line.category is category]


# --------------------------------------------------------------------------- #
# The defect, reproduced through the real route                                  #
# --------------------------------------------------------------------------- #


def test_confirmed_recompute_route_is_kernel_consistent_with_admitted_prices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails numerically on the splice-after-assembly behaviour (see Task 1 step 2)."""
    client, _store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    headers = csrf(client)
    for card in ("hdfc-infinia", "axis-atlas"):
        added = client.post(
            "/account/wallet",
            headers=headers,
            json={
                "card_id": card,
                "nickname": card,
                "points_balances": {"voyager-prime": 140000},
            },
        )
        assert added.status_code == 201, added.text
    wallet = UserWallet(**client.get("/account/wallet/projection").json())
    session, _job = finished_plan(client, kit, wallet=wallet)
    state = job_manager.get_job(session["job_id"])
    assert state is not None and state.report is not None
    kb = api_main.get_kb()
    admitted = with_admitted_prices(state.report, kb)
    assert_kernel_consistent(admitted, kb)  # the precondition: a consistent admitted report
    assert _lines(admitted, SpendCategory.FLIGHTS)[0].amount_minor != _lines(
        state.report, SpendCategory.FLIGHTS
    )[0].amount_minor
    with state._lock:
        state.report = admitted
    assert admitted.travel_inventory is not None

    response = client.post(
        f"/planning/sessions/{session['id']}/recompute",
        headers=headers,
        json={
            "expected_inventory_revision": admitted.travel_inventory.inventory_revision,
            "edit": {"op": "remove_item", "poi_id": "sg-hawker-maxwell", "day_index": 0},
        },
    )

    assert response.status_code == 200, response.text
    updated = FinalReport.model_validate(response.json())
    assert [(x.id, x.amount_minor) for x in _lines(updated, SpendCategory.FLIGHTS)] == [
        (x.id, x.amount_minor) for x in _lines(admitted, SpendCategory.FLIGHTS)
    ]
    assert_kernel_consistent(updated, kb)


# --------------------------------------------------------------------------- #
# The new assembly function                                                      #
# --------------------------------------------------------------------------- #


def test_confirmed_edit_kernel_uses_admitted_prices(tmp_path: Path) -> None:
    from agents.post_plan_execution import recompute_confirmed_edit

    kb = _kb(tmp_path)
    seed = seed_report(kb)
    admitted = with_admitted_prices(seed, kb, flight_channels=[Channel.DIRECT_AIRLINE])
    seed_flight = _lines(seed, SpendCategory.FLIGHTS)[0]
    assert _lines(admitted, SpendCategory.FLIGHTS)[0].amount_minor == seed_flight.amount_minor * 3

    result = recompute_confirmed_edit(
        admitted, RemoveItem(poi_id="sg-hawker-maxwell", day_index=0), kb=kb, now=NOW
    )

    assert_kernel_consistent(result, kb)
    # Admitted lines survive byte for byte; they are never re-derived from seeds.
    assert _lines(result, SpendCategory.FLIGHTS) == _lines(admitted, SpendCategory.FLIGHTS)
    assert _lines(result, SpendCategory.HOTELS) == _lines(admitted, SpendCategory.HOTELS)
    assert _lines(result, SpendCategory.FLIGHTS)[0].available_channels == [Channel.DIRECT_AIRLINE]
    assert "poi:sg-hawker-maxwell" not in {line.id for line in result.costed_trip.lines}
    assert result.costed_trip.booking_date == admitted.costed_trip.booking_date
    assert result.flights_pick == admitted.flights_pick and result.hotel_pick == admitted.hotel_pick
    # The numbers the user reads moved with the edit and with the admitted prices.
    assert result.budget_totals != admitted.budget_totals
    assert result.optimizer_result != seed.optimizer_result


def test_transfer_advice_is_priced_from_the_admitted_flight(tmp_path: Path) -> None:
    from agents.post_plan_execution import recompute_confirmed_edit

    kb = _kb(tmp_path)
    admitted = with_admitted_prices(seed_report(kb), kb, flight_factor=5)
    assert admitted.transfer_advice is not None

    result = recompute_confirmed_edit(
        admitted, RemoveItem(poi_id="sg-hawker-maxwell", day_index=0), kb=kb, now=NOW
    )

    assert result.transfer_advice is not None
    assert result.transfer_advice == admitted.transfer_advice  # the flight price is unchanged
    assert_kernel_consistent(result, kb)


def test_report_metadata_survives_an_edit(tmp_path: Path) -> None:
    from agents.post_plan_execution import recompute_confirmed_edit

    kb = _kb(tmp_path)
    admitted = with_admitted_prices(seed_report(kb), kb).model_copy(
        update={"caveats": ["Prior caveat."], "trace_id": "trace-admitted"}
    )

    result = recompute_confirmed_edit(
        admitted, RemoveItem(poi_id="sg-hawker-maxwell", day_index=0), kb=kb, now=NOW
    )

    assert "Prior caveat." in result.caveats
    assert "Admitted evidence assumption retained across edits." in result.assumptions
    assert result.trace_id == "trace-admitted"
    assert result.freshness.budget is SectionState.RECOMPUTED
    assert result.freshness.payment_strategy is SectionState.RECOMPUTED
    assert result.freshness.prose is SectionState.STALE
    assert result.freshness.critic_verdict is SectionState.STALE
    assert result.freshness.edit_count == admitted.freshness.edit_count + 1


def test_an_empty_wallet_edit_is_cash_only_and_consistent(tmp_path: Path) -> None:
    from agents.post_plan_execution import recompute_confirmed_edit

    kb = _kb(tmp_path)
    spec = _spec(UserWallet(card_ids=[]))
    admitted = with_admitted_prices(seed_report(kb, spec), kb)

    result = recompute_confirmed_edit(
        admitted, RemoveItem(poi_id="sg-hawker-maxwell", day_index=0), kb=kb, now=NOW
    )

    assert_kernel_consistent(result, kb)
    assert result.transfer_advice is None
    assert all(a.card_id == "cash_only" for a in result.optimizer_result.assignments)
    assert sum(a.points_value_minor for a in result.optimizer_result.assignments) == 0


def test_a_missing_hotel_stays_missing_and_is_not_refilled_from_seeds(tmp_path: Path) -> None:
    from agents.post_plan_execution import recompute_confirmed_edit

    kb = _kb(tmp_path)
    admitted = with_admitted_prices(seed_report(kb), kb, drop_hotel=True)
    assert not _lines(admitted, SpendCategory.HOTELS)

    result = recompute_confirmed_edit(
        admitted, RemoveItem(poi_id="sg-hawker-maxwell", day_index=0), kb=kb, now=NOW
    )

    assert not _lines(result, SpendCategory.HOTELS)
    assert result.hotel_pick is None
    assert_kernel_consistent(result, kb)


def test_admitted_amounts_are_used_verbatim_whatever_their_price_scope(tmp_path: Path) -> None:
    """A party-total quote must not be multiplied by travelers a second time."""
    from agents.post_plan_execution import recompute_confirmed_edit

    kb = _kb(tmp_path)
    seed = seed_report(kb)
    admitted = with_admitted_prices(seed, kb, flight_factor=1, hotel_factor=1)
    party_total = _lines(admitted, SpendCategory.FLIGHTS)[0].amount_minor + 1_234_567
    lines = [
        line.model_copy(update={"amount_minor": party_total})
        if line.category is SpendCategory.FLIGHTS
        else line
        for line in admitted.costed_trip.lines
    ]
    admitted = admitted.model_copy(
        update={"costed_trip": admitted.costed_trip.model_copy(update={"lines": lines})}
    )

    result = recompute_confirmed_edit(
        admitted, RemoveItem(poi_id="sg-hawker-maxwell", day_index=0), kb=kb, now=NOW
    )

    assert _lines(result, SpendCategory.FLIGHTS)[0].amount_minor == party_total


def test_a_changed_paid_activity_changes_the_costed_lines(tmp_path: Path) -> None:
    from agents.post_plan_execution import recompute_confirmed_edit

    kb = _kb(tmp_path)
    admitted = with_admitted_prices(seed_report(kb), kb)
    used = {item.poi_id for day in admitted.itinerary.days for item in day.items}
    candidates = [
        poi
        for poi in retrieve_candidates(admitted.trip_spec, kb).pois
        if poi.price_minor > 0 and poi.id not in used
    ]
    assert candidates, "the seed must offer an unused paid POI for this scenario"
    added = candidates[0]

    result = recompute_confirmed_edit(
        admitted, AddItem(poi_id=added.id, day_index=1, position=0), kb=kb, now=NOW
    )

    assert f"poi:{added.id}" in {line.id for line in result.costed_trip.lines}
    assert _lines(result, SpendCategory.FLIGHTS) == _lines(admitted, SpendCategory.FLIGHTS)
    assert_kernel_consistent(result, kb)


def test_recompute_makes_no_network_or_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.post_plan_execution import recompute_confirmed_edit

    kb = _kb(tmp_path)
    admitted = with_admitted_prices(seed_report(kb), kb)

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("recompute must not open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)

    result = recompute_confirmed_edit(
        admitted, RemoveItem(poi_id="sg-hawker-maxwell", day_index=0), kb=kb, now=NOW
    )

    assert_kernel_consistent(result, kb)


def test_the_legacy_standalone_recompute_is_unchanged(tmp_path: Path) -> None:
    """/plan/recompute keeps its seed-priced behaviour; only confirmed sessions change."""
    from agents.recompute import recompute_itinerary

    kb = _kb(tmp_path)
    seed = seed_report(kb)

    result = recompute_itinerary(
        seed.trip_spec,
        seed.itinerary,
        RemoveItem(poi_id="sg-hawker-maxwell", day_index=0),
        kb,
        booking_date=BOOKING,
    )

    assert_kernel_consistent(result, kb)
    assert _lines(result, SpendCategory.FLIGHTS)[0].id.startswith("flight:")
