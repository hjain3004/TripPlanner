"""CP4 Task 2 — deterministic impact and invalidation (conversational design, section 9).

Impact is computed from the validated action and the workspace context. The model never
chooses a domain, and the briefs alone are not enough: identical global briefs mean
different work for a removal, a day-local override and an explanation.
"""

from __future__ import annotations

from datetime import date

import pytest

from core.models import UserWallet
from core.trip_models import AddItem, MoveItem, RemoveItem, ReorderDay, ReplaceItem
from evals.cp4_support import (
    HOTEL_AREA,
    START,
    impact_context,
    make_brief,
)
from planning.answers import (
    BudgetObjectivePayload,
    DailyRhythmPayload,
    ExperiencesFoodPayload,
    FlightPreferencesPayload,
    HardConstraintsPayload,
    PurposePartyPayload,
    QuestionId,
    StayPreferencesPayload,
    TripEssentialsPayload,
)
from planning.contracts import TripBrief
from planning.post_plan import (
    ActionImpact,
    BriefPatch,
    ClarificationRequired,
    DayOverride,
    DeterministicEdit,
    ExplanationRequest,
    InvalidatedDomain,
    PatchEntry,
    PostPlanAction,
    ProfileUpdateAction,
    ProviderInvalidatingChange,
    ScopedItineraryReplan,
    WalletOrObjectiveChange,
    apply_brief_patch,
    apply_wallet_or_objective,
    compute_impact,
    flight_fingerprint,
    hotel_fingerprint,
    objective_patch,
)

D = InvalidatedDomain
ALL_DOMAINS = [D.FLIGHT, D.HOTEL, D.AWARD, D.ITINERARY, D.COST, D.CARD_STRATEGY]
FLIGHT_SET = [D.FLIGHT, D.AWARD, D.COST, D.CARD_STRATEGY]
HOTEL_SET = [D.HOTEL, D.ITINERARY, D.COST, D.CARD_STRATEGY]
ITINERARY_SET = [D.ITINERARY, D.COST]
STRATEGY_SET = [D.AWARD, D.COST, D.CARD_STRATEGY]


def patch_of(question_id: QuestionId, payload: object) -> BriefPatch:
    return BriefPatch(entries=[PatchEntry(question_id=question_id, payload=payload)])  # type: ignore[arg-type]


def provider(question_id: QuestionId, payload: object) -> ProviderInvalidatingChange:
    return ProviderInvalidatingChange(patch=patch_of(question_id, payload))


def impact_of(
    action: PostPlanAction, before: TripBrief | None = None, **context: object
) -> ActionImpact:
    before = before or make_brief()
    ctx = impact_context(before, **context)  # type: ignore[arg-type]
    if isinstance(action, ProviderInvalidatingChange):
        after = apply_brief_patch(before, action.patch)
    elif isinstance(action, ScopedItineraryReplan) and action.scope == "trip":
        assert action.patch is not None
        after = apply_brief_patch(before, action.patch)
    else:
        after = before
    return compute_impact(before, after, action=action, context=ctx)


def essentials(brief: TripBrief, **changes: object) -> TripEssentialsPayload:
    return TripEssentialsPayload.model_validate(
        brief.trip_essentials.model_copy(update=changes).model_dump()
    )


# --------------------------------------------------------------------------- #
# The invalidation table, row by row                                             #
# --------------------------------------------------------------------------- #


def test_dates_invalidate_everything_and_need_confirmation() -> None:
    brief = make_brief()
    action = provider(
        QuestionId.TRIP_ESSENTIALS,
        essentials(brief, start_date=date(2026, 11, 10), end_date=date(2026, 11, 14)),
    )

    impact = impact_of(action, brief)

    assert impact.invalidated_domains == ALL_DOMAINS
    assert impact.refetch_domains == ["flight", "hotel"]
    assert impact.inventory_reuse == "none"
    assert impact.requires_confirmation and impact.changes_trip
    assert impact.affected_dates == [date(2026, 11, 10 + i) for i in range(4)]


def test_destination_invalidates_everything() -> None:
    brief = make_brief()

    impact = impact_of(provider(QuestionId.TRIP_ESSENTIALS, essentials(brief, destination="BOM")))

    assert impact.invalidated_domains == ALL_DOMAINS
    assert impact.refetch_domains == ["flight", "hotel"]


def test_travelers_and_party_invalidate_everything() -> None:
    brief = make_brief()
    patch = BriefPatch(
        entries=[
            PatchEntry(
                question_id=QuestionId.TRIP_ESSENTIALS, payload=essentials(brief, travelers=3)
            ),
            PatchEntry(
                question_id=QuestionId.PURPOSE_AND_PARTY,
                payload=PurposePartyPayload(purpose="leisure", adults=3),
            ),
        ]
    )

    impact = impact_of(ProviderInvalidatingChange(patch=patch), brief)

    assert impact.invalidated_domains == ALL_DOMAINS
    assert impact.refetch_domains == ["flight", "hotel"]


@pytest.mark.parametrize(
    "change",
    [
        {"cabin": "business"},
        {"max_stops": 1},
        {"schedule": "morning"},
        {"airport_flexible": True},
        {"checked_baggage": True},
        {"seat": "window"},
    ],
)
def test_flight_changes_query_flights_only(change: dict[str, object]) -> None:
    brief = make_brief()
    payload = FlightPreferencesPayload.model_validate(
        brief.flight_preferences.model_copy(update=change).model_dump()  # type: ignore[union-attr]
    )

    impact = impact_of(provider(QuestionId.FLIGHT_PREFERENCES, payload), brief)

    assert impact.invalidated_domains == FLIGHT_SET
    assert impact.refetch_domains == ["flight"]
    assert impact.inventory_reuse == "partial"
    assert D.HOTEL not in impact.invalidated_domains
    assert impact.affected_dates == []  # the itinerary itself is untouched


@pytest.mark.parametrize(
    "change",
    [
        {"room_count": 2},
        {"lodging_styles": ["boutique"]},
        {"neighborhood_priorities": ["riverside"]},
        {"room_needs": ["twin beds"]},
        {"location_price_tradeoff": "price"},
    ],
)
def test_hotel_changes_query_hotels_only_and_refit_the_itinerary(
    change: dict[str, object],
) -> None:
    brief = make_brief()
    payload = StayPreferencesPayload.model_validate(
        brief.stay_preferences.model_copy(update=change).model_dump()  # type: ignore[union-attr]
    )

    impact = impact_of(provider(QuestionId.STAY_PREFERENCES, payload), brief)

    assert impact.invalidated_domains == HOTEL_SET
    assert impact.refetch_domains == ["hotel"]
    assert impact.inventory_reuse == "partial"
    assert D.FLIGHT not in impact.invalidated_domains
    assert len(impact.affected_dates) == 4  # every day is re-fitted to the new area


def test_travel_style_changes_both_searches() -> None:
    brief = make_brief()
    payload = BudgetObjectivePayload.model_validate(
        brief.budget_and_objective.model_copy(update={"travel_style": "luxury"}).model_dump()  # type: ignore[union-attr]
    )

    impact = impact_of(provider(QuestionId.BUDGET_AND_OBJECTIVE, payload), brief)

    assert impact.refetch_domains == ["flight", "hotel"]
    assert impact.invalidated_domains == ALL_DOMAINS


@pytest.mark.parametrize(
    ("question_id", "payload"),
    [
        (
            QuestionId.DAILY_RHYTHM,
            DailyRhythmPayload(
                pace="relaxed", day_start="late", evening_style="quiet", day_trip_appetite="none"
            ),
        ),
        (
            QuestionId.EXPERIENCES_AND_FOOD,
            ExperiencesFoodPayload(interests=["art"], iconic_local_balance="local"),
        ),
        (
            QuestionId.HARD_CONSTRAINTS,
            HardConstraintsPayload(has_constraints=True, accessibility=["step-free routes"]),
        ),
    ],
)
def test_itinerary_preferences_never_authorize_a_provider_call(
    question_id: QuestionId, payload: object
) -> None:
    for action in (
        provider(question_id, payload),
        ScopedItineraryReplan(
            scope="trip",
            affected_dates=[START.replace(day=START.day + i) for i in range(4)],
            patch=patch_of(question_id, payload),
        ),
    ):
        impact = impact_of(action)

        assert impact.invalidated_domains == ITINERARY_SET
        assert impact.refetch_domains == []
        assert impact.inventory_reuse == "full"
        assert not impact.requires_confirmation


def test_wallet_adoption_reuses_inventory_and_asks_for_visible_approval() -> None:
    before = make_brief()
    action = WalletOrObjectiveChange(adopt_current_wallet=True)
    after = apply_wallet_or_objective(
        before, action, current_wallet=UserWallet(card_ids=["hdfc-infinia", "axis-atlas"])
    )

    impact = compute_impact(before, after, action=action, context=impact_context(before))

    assert impact.invalidated_domains == STRATEGY_SET
    assert impact.refetch_domains == [] and impact.inventory_reuse == "full"
    assert impact.requires_confirmation  # a wallet change is adopted only with visible approval


def test_a_points_balance_change_is_strategy_only() -> None:
    before = make_brief(wallet=UserWallet(card_ids=["hdfc-infinia"]))
    action = WalletOrObjectiveChange(adopt_current_wallet=True)
    after = apply_wallet_or_objective(
        before,
        action,
        current_wallet=UserWallet(card_ids=["hdfc-infinia"], points_balances={"voyager-prime": 5}),
    )

    impact = compute_impact(before, after, action=action, context=impact_context(before))

    assert impact.invalidated_domains == STRATEGY_SET and impact.refetch_domains == []


def test_objective_only_changes_do_not_imply_a_new_hotel_or_flight_search() -> None:
    before = make_brief()
    action = WalletOrObjectiveChange(objective="lowest_cash")
    patch = objective_patch(before, action)
    assert patch is not None
    after = apply_brief_patch(before, patch)

    impact = compute_impact(before, after, action=action, context=impact_context(before))

    assert impact.invalidated_domains == STRATEGY_SET
    assert impact.refetch_domains == []
    assert not impact.requires_confirmation
    assert D.HOTEL not in impact.invalidated_domains and D.FLIGHT not in impact.invalidated_domains


def test_rooms_and_occupancy_do_imply_a_hotel_search() -> None:
    brief = make_brief()
    rooms = StayPreferencesPayload(room_count=2, location_price_tradeoff="balanced")

    assert impact_of(provider(QuestionId.STAY_PREFERENCES, rooms), brief).refetch_domains == [
        "hotel"
    ]


def test_mixed_changes_union_rather_than_cancel() -> None:
    brief = make_brief()
    cabin = FlightPreferencesPayload(cabin="business", max_stops=0, schedule="no_preference")
    pace = DailyRhythmPayload(
        pace="packed", day_start="normal", evening_style="flexible", day_trip_appetite="none"
    )
    patch = BriefPatch(
        entries=[
            PatchEntry(question_id=QuestionId.FLIGHT_PREFERENCES, payload=cabin),
            PatchEntry(question_id=QuestionId.DAILY_RHYTHM, payload=pace),
        ]
    )

    impact = impact_of(ProviderInvalidatingChange(patch=patch), brief)

    assert impact.invalidated_domains == [D.FLIGHT, D.AWARD, D.ITINERARY, D.COST, D.CARD_STRATEGY]
    assert impact.refetch_domains == ["flight"]
    assert impact.inventory_reuse == "partial"


def test_a_change_the_search_cannot_express_is_not_assumed_equivalent() -> None:
    brief = make_brief()
    payload = FlightPreferencesPayload.model_validate(
        brief.flight_preferences.model_copy(update={"seat": "aisle"}).model_dump()  # type: ignore[union-attr]
    )

    impact = impact_of(provider(QuestionId.FLIGHT_PREFERENCES, payload), brief)

    assert impact.refetch_domains == ["flight"]
    assert any("seat" in note.casefold() for note in impact.limitations)


def test_budget_and_flexibility_have_small_honest_impacts() -> None:
    brief = make_brief()
    budget = BudgetObjectivePayload.model_validate(
        brief.budget_and_objective.model_copy(update={"budget_minor": 500000}).model_dump()  # type: ignore[union-attr]
    )
    flexible = essentials(brief, date_flexibility_days=3)

    cap = impact_of(provider(QuestionId.BUDGET_AND_OBJECTIVE, budget), brief)
    flex = impact_of(provider(QuestionId.TRIP_ESSENTIALS, flexible), brief)

    assert cap.invalidated_domains == [D.COST] and cap.refetch_domains == []
    assert flex.invalidated_domains == [] and flex.refetch_domains == []
    assert any("not searched" in note for note in flex.limitations)


def test_retained_evidence_for_a_different_search_is_never_reused() -> None:
    before = make_brief()
    other = make_brief(
        trip_essentials=essentials(before, destination="BOM"),
    )
    # The retained fingerprints belong to another trip; even a no-op request cannot reuse them.
    context = impact_context(before, flight_fingerprint=flight_fingerprint(other),
                             hotel_fingerprint=hotel_fingerprint(other, hotel_area_id=HOTEL_AREA))
    no_op = provider(QuestionId.TRIP_ESSENTIALS, before.trip_essentials)

    impact = compute_impact(before, before, action=no_op, context=context)

    assert impact.refetch_domains == ["flight", "hotel"]
    assert impact.requires_confirmation


def test_the_retained_hotel_area_is_part_of_the_hotel_search() -> None:
    brief = make_brief()

    assert hotel_fingerprint(brief, hotel_area_id="marina_bay") != hotel_fingerprint(
        brief, hotel_area_id="chinatown"
    )
    assert flight_fingerprint(brief) == flight_fingerprint(make_brief())
    moved = impact_context(brief, retained_hotel_area_id="chinatown", hotel_fingerprint=None)
    stay = StayPreferencesPayload(room_count=2, location_price_tradeoff="balanced")
    action = provider(QuestionId.STAY_PREFERENCES, stay)
    after = apply_brief_patch(brief, action.patch)
    assert compute_impact(brief, after, action=action, context=moved).refetch_domains == ["hotel"]


# --------------------------------------------------------------------------- #
# Identical global briefs, different actions                                     #
# --------------------------------------------------------------------------- #


def test_equal_briefs_do_not_imply_equal_impact() -> None:
    brief = make_brief()
    ctx = impact_context(brief)
    remove = DeterministicEdit(edit=RemoveItem(poi_id="poi:maxwell", day_index=0))
    local = ScopedItineraryReplan(
        scope="dates",
        affected_dates=[date(2026, 11, 2), date(2026, 11, 3)],
        patch=patch_of(
            QuestionId.DAILY_RHYTHM,
            DailyRhythmPayload(
                pace="relaxed", day_start="normal", evening_style="quiet", day_trip_appetite="none"
            ),
        ),
    )
    explain = ExplanationRequest(
        target_kind="cost_line", target_id="flight:SQ", topic="why_chosen"
    )
    ask = ClarificationRequired(reason="needs_detail", question="Which day?")
    profile = ProfileUpdateAction(
        section="flight",
        candidate=FlightPreferencesPayload(
            cabin="economy", max_stops=0, schedule="no_preference", seat="window"
        ),
    )

    impacts = {
        name: compute_impact(brief, brief, action=action, context=ctx)
        for name, action in {
            "remove": remove,
            "local": local,
            "explain": explain,
            "ask": ask,
            "profile": profile,
        }.items()
    }

    assert impacts["remove"].affected_dates == [START] and impacts["remove"].changes_trip
    assert impacts["local"].affected_dates == [date(2026, 11, 2), date(2026, 11, 3)]
    assert impacts["local"].invalidated_domains == ITINERARY_SET
    assert impacts["explain"].explanation_only and impacts["explain"].invalidated_domains == []
    assert not impacts["ask"].changes_trip and impacts["ask"].invalidated_domains == []
    assert impacts["profile"].requires_confirmation and not impacts["profile"].changes_trip
    assert len({impact.model_dump_json() for impact in impacts.values()}) == 5


def test_a_global_replan_leaves_overridden_days_alone() -> None:
    brief = make_brief()
    overrides = [DayOverride(date=date(2026, 11, 2), question_ids=[QuestionId.DAILY_RHYTHM])]
    pace = DailyRhythmPayload(
        pace="relaxed", day_start="normal", evening_style="flexible", day_trip_appetite="none"
    )
    action = ScopedItineraryReplan(
        scope="trip",
        affected_dates=[date(2026, 11, 1 + i) for i in range(4)],
        patch=patch_of(QuestionId.DAILY_RHYTHM, pace),
    )

    impact = impact_of(action, brief, day_overrides=overrides)

    assert date(2026, 11, 2) not in impact.affected_dates
    assert impact.affected_dates == [date(2026, 11, 1), date(2026, 11, 3), date(2026, 11, 4)]


def test_a_global_replan_that_changes_nothing_is_an_explicit_no_op() -> None:
    brief = make_brief()
    action = ScopedItineraryReplan(
        scope="trip",
        affected_dates=[date(2026, 11, 1 + i) for i in range(4)],
        patch=patch_of(QuestionId.DAILY_RHYTHM, brief.daily_rhythm),
    )

    impact = impact_of(action, brief)

    assert impact.affected_dates == [] and not impact.changes_trip
    assert any("nothing to replan" in note for note in impact.limitations)


# --------------------------------------------------------------------------- #
# Edits: every operation names real days and real items                           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("edit", "dates"),
    [
        (MoveItem(poi_id="poi:maxwell", from_day_index=0, to_day_index=2, position=0),
         [date(2026, 11, 1), date(2026, 11, 3)]),
        (ReorderDay(day_index=0, poi_ids=["poi:maxwell", "poi:gardens"]), [date(2026, 11, 1)]),
        (ReplaceItem(old_poi_id="poi:flyer", new_poi_id="poi:jewel", day_index=2),
         [date(2026, 11, 3)]),
        (AddItem(poi_id="poi:jewel", day_index=3, position=0), [date(2026, 11, 4)]),
    ],
)
def test_edits_affect_only_the_days_they_touch(edit: object, dates: list[date]) -> None:
    impact = impact_of(DeterministicEdit(edit=edit))  # type: ignore[arg-type]

    assert impact.affected_dates == dates
    assert impact.invalidated_domains == ITINERARY_SET
    assert impact.refetch_domains == [] and impact.inventory_reuse == "full"


@pytest.mark.parametrize(
    "edit",
    [
        RemoveItem(poi_id="poi:nowhere", day_index=0),
        RemoveItem(poi_id="poi:maxwell", day_index=2),
        MoveItem(poi_id="poi:maxwell", from_day_index=1, to_day_index=2, position=0),
        MoveItem(poi_id="poi:maxwell", from_day_index=0, to_day_index=9, position=0),
        ReorderDay(day_index=0, poi_ids=["poi:maxwell"]),
        ReplaceItem(old_poi_id="poi:maxwell", new_poi_id="poi:jewel", day_index=2),
        AddItem(poi_id="poi:jewel", day_index=9, position=0),
    ],
)
def test_an_edit_that_does_not_match_the_workspace_is_rejected(edit: object) -> None:
    with pytest.raises(ValueError):
        impact_of(DeterministicEdit(edit=edit))  # type: ignore[arg-type]


def test_impact_refuses_inconsistent_inputs() -> None:
    brief = make_brief()
    ctx = impact_context(brief)
    rooms = provider(
        QuestionId.STAY_PREFERENCES,
        StayPreferencesPayload(room_count=3, location_price_tradeoff="balanced"),
    )
    with pytest.raises(ValueError, match="patch applied"):  # an after-brief nobody derived
        compute_impact(brief, brief, action=rooms, context=ctx)
    outside = ScopedItineraryReplan(
        scope="dates", affected_dates=[date(2027, 1, 1)], day_theme="food"
    )
    with pytest.raises(ValueError, match="outside"):
        compute_impact(brief, brief, action=outside, context=ctx)
    partial = ScopedItineraryReplan(
        scope="trip",
        affected_dates=[START],
        patch=patch_of(QuestionId.DAILY_RHYTHM, brief.daily_rhythm),
    )
    with pytest.raises(ValueError, match="every itinerary date"):
        compute_impact(brief, brief, action=partial, context=ctx)
    with pytest.raises(ValueError, match="cannot change the brief"):
        compute_impact(
            brief,
            apply_brief_patch(brief, rooms.patch),
            action=ExplanationRequest(target_kind="cost_line", target_id="x", topic="why_chosen"),
            context=ctx,
        )
    with pytest.raises(ValueError, match="home context"):
        compute_impact(
            brief,
            brief.model_copy(update={"home": brief.home.model_copy(update={"home_country": "US"})}),
            action=ClarificationRequired(reason="needs_detail", question="?"),
            context=ctx,
        )


def test_wallet_actions_cannot_smuggle_a_provider_search_change() -> None:
    before = make_brief()
    sneaky = apply_brief_patch(
        before,
        patch_of(
            QuestionId.STAY_PREFERENCES,
            StayPreferencesPayload(room_count=2, location_price_tradeoff="balanced"),
        ),
    )
    action = WalletOrObjectiveChange(objective="lowest_cash")

    with pytest.raises(ValueError):
        compute_impact(before, sneaky, action=action, context=impact_context(before))


def test_an_objective_change_without_a_budget_answer_cannot_be_built() -> None:
    brief = make_brief(budget_and_objective=None)

    with pytest.raises(ValueError, match="budget and objective"):
        objective_patch(brief, WalletOrObjectiveChange(objective="lowest_cash"))
    assert objective_patch(brief, WalletOrObjectiveChange(adopt_current_wallet=True)) is None


def test_wallet_adoption_needs_the_current_wallet() -> None:
    with pytest.raises(ValueError, match="no current wallet"):
        apply_wallet_or_objective(
            make_brief(), WalletOrObjectiveChange(adopt_current_wallet=True), current_wallet=None
        )
