"""CP4 Task 2 — typed post-plan intents and deterministic routing.

Deterministic matching must never pretend to understand: a phrase it can resolve
exactly becomes a typed action, a phrase it recognises but cannot resolve safely becomes
a focused clarification, and anything else is ``None`` (the caller may then spend one
bounded interpretation). Nothing here uses a model.
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from core.models import UserWallet
from core.trip_models import AddItem, MoveItem, RemoveItem, ReorderDay, ReplaceItem
from evals.cp4_support import (
    FLYER,
    GALLERY,
    GARDENS,
    JEWEL,
    MAXWELL,
    START,
    make_brief,
    routing_context,
)
from planning.answers import (
    AdaptiveDetailPayload,
    DailyRhythmPayload,
    ExperiencesFoodPayload,
    FlightPreferencesPayload,
    PurposePartyPayload,
    QuestionId,
    StayPreferencesPayload,
    TripEssentialsPayload,
)
from planning.post_plan import (
    ACTION_KINDS,
    BriefPatch,
    ClarificationRequired,
    DeterministicEdit,
    ExplanationRequest,
    PatchEntry,
    PostPlanAction,
    PostPlanInputError,
    ProfileUpdateAction,
    ProviderInvalidatingChange,
    RoutingDay,
    RoutingItem,
    ScopedItineraryReplan,
    WalletOrObjectiveChange,
    apply_brief_patch,
    classify_command,
)

ADAPTER: TypeAdapter[PostPlanAction] = TypeAdapter(PostPlanAction)


def route(text: str, **overrides: object) -> PostPlanAction | None:
    return classify_command(text, routing_context(**overrides))  # type: ignore[arg-type]


def clarification(text: str, **overrides: object) -> ClarificationRequired:
    result = route(text, **overrides)
    assert isinstance(result, ClarificationRequired), result
    return result


# --------------------------------------------------------------------------- #
# All seven intent classes, deterministically                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("remove Maxwell Food Centre", "deterministic_edit"),
        ("make it more relaxed", "scoped_itinerary_replan"),
        ("change the dates to 2026-11-10 to 2026-11-14", "provider_invalidating_change"),
        ("update my wallet", "wallet_or_objective_change"),
        ("why did you pick the Singapore Airlines flight", "explanation_request"),
        ("always use a window seat", "profile_update_proposal"),
        ("remove the Eiffel Tower", "clarification_required"),
    ],
)
def test_every_intent_class_has_a_deterministic_route(text: str, kind: str) -> None:
    result = route(text)

    assert result is not None and result.kind == kind
    assert kind in ACTION_KINDS
    assert ADAPTER.validate_python(result.model_dump(mode="json")) == result


def test_the_action_union_has_exactly_the_seven_documented_kinds() -> None:
    assert sorted(ACTION_KINDS) == sorted(
        [
            "deterministic_edit",
            "scoped_itinerary_replan",
            "provider_invalidating_change",
            "wallet_or_objective_change",
            "explanation_request",
            "profile_update_proposal",
            "clarification_required",
        ]
    )
    with pytest.raises(ValidationError):
        ADAPTER.validate_python({"kind": "book_the_flight"})


# --------------------------------------------------------------------------- #
# Exact edit matches                                                            #
# --------------------------------------------------------------------------- #


def test_remove_resolves_the_item_and_its_day() -> None:
    result = route("please remove Maxwell Food Centre")

    assert result == DeterministicEdit(edit=RemoveItem(poi_id="poi:maxwell", day_index=0))


def test_matching_ignores_case_and_punctuation_but_not_meaning() -> None:
    assert route("Remove  gardens BY the bay!!") == DeterministicEdit(
        edit=RemoveItem(poi_id="poi:gardens", day_index=0)
    )


def test_move_to_a_named_day_appends_by_default() -> None:
    result = route("move National Gallery Singapore to day 4")

    assert result == DeterministicEdit(
        edit=MoveItem(poi_id="poi:gallery", from_day_index=1, to_day_index=3, position=0)
    )


def test_move_to_a_busy_day_goes_last_and_can_go_first() -> None:
    last = route("move Singapore Flyer to day 1")
    first = route("move Singapore Flyer to day 1 as the first stop")

    assert isinstance(last, DeterministicEdit) and isinstance(last.edit, MoveItem)
    assert last.edit.position == 2
    assert isinstance(first, DeterministicEdit) and isinstance(first.edit, MoveItem)
    assert first.edit.position == 0


def test_move_by_date_and_by_weekday() -> None:
    by_date = route("move Singapore Flyer to 2026-11-02")
    by_weekday = route("move Singapore Flyer to monday")

    assert by_date == by_weekday
    assert isinstance(by_date, DeterministicEdit) and isinstance(by_date.edit, MoveItem)
    assert by_date.edit.to_day_index == 1


def test_reorder_needs_every_stop_on_the_day() -> None:
    result = route("reorder day 1: Maxwell Food Centre, Gardens by the Bay")

    assert result == DeterministicEdit(
        edit=ReorderDay(day_index=0, poi_ids=["poi:maxwell", "poi:gardens"])
    )
    partial = clarification("reorder day 1: Maxwell Food Centre")
    assert partial.reason == "needs_detail"


def test_replace_swaps_in_only_an_approved_candidate() -> None:
    result = route("replace Singapore Flyer with Jewel Changi Airport")

    assert result == DeterministicEdit(
        edit=ReplaceItem(old_poi_id="poi:flyer", new_poi_id="poi:jewel", day_index=2)
    )
    unknown = clarification("replace Singapore Flyer with the Eiffel Tower")
    assert unknown.reason == "not_found"


def test_add_requires_an_approved_candidate_and_a_day() -> None:
    result = route("add Jewel Changi Airport to day 4")

    assert result == DeterministicEdit(edit=AddItem(poi_id="poi:jewel", day_index=3, position=0))
    undated = clarification("add Jewel Changi Airport")
    assert undated.reason == "needs_detail"
    assert {c.id for c in undated.choices} == {f"add:poi:jewel:{i}" for i in range(4)}


# --------------------------------------------------------------------------- #
# Ambiguity, absence, contradiction: clarify, never guess                        #
# --------------------------------------------------------------------------- #


def test_the_same_venue_on_two_days_is_ambiguous_until_a_day_is_named() -> None:
    twice = [
        RoutingDay(date=START, items=[GARDENS]),
        RoutingDay(date=date(2026, 11, 2), items=[GALLERY, GARDENS]),
        RoutingDay(date=date(2026, 11, 3), items=[]),
        RoutingDay(date=date(2026, 11, 4), items=[]),
    ]

    ambiguous = clarification("remove Gardens by the Bay", days=twice)
    resolved = route("remove Gardens by the Bay on day 2", days=twice)

    assert ambiguous.reason == "ambiguous_item"
    assert {c.id for c in ambiguous.choices} == {"remove:poi:gardens:0", "remove:poi:gardens:1"}
    assert resolved == DeterministicEdit(edit=RemoveItem(poi_id="poi:gardens", day_index=1))


def test_two_different_venues_with_one_name_are_ambiguous() -> None:
    twin = RoutingItem(poi_id="poi:gardens-annex", name="Gardens by the Bay")
    days = [
        RoutingDay(date=START, items=[GARDENS]),
        RoutingDay(date=date(2026, 11, 2), items=[twin]),
        RoutingDay(date=date(2026, 11, 3), items=[]),
        RoutingDay(date=date(2026, 11, 4), items=[]),
    ]

    result = clarification("remove Gardens by the Bay", days=days)

    assert result.reason == "scope_conflict"
    assert len(result.choices) == 2


def test_a_stop_that_is_not_in_the_plan_asks_which_one() -> None:
    result = clarification("remove the Eiffel Tower")

    assert result.reason == "not_found"
    assert len(result.choices) == 4  # the plan's four stops, offered as choices


@pytest.mark.parametrize(
    "text",
    ["remove Maxwell Food Centre on day 9", "move Singapore Flyer to day 7"],
)
def test_a_nonexistent_day_is_not_found(text: str) -> None:
    assert clarification(text).reason == "not_found"


@pytest.mark.parametrize(
    "text",
    [
        "remove Maxwell Food Centre tomorrow",
        "remove Singapore Flyer next week",
        "make it relaxed this weekend",
    ],
)
def test_relative_dates_are_never_resolved(text: str) -> None:
    result = clarification(text)

    assert result.reason == "ambiguous_date"


def test_a_weekday_that_names_two_days_is_ambiguous() -> None:
    eight = [
        RoutingDay(date=date(2026, 11, 1 + i), items=[GARDENS] if i == 0 else [])
        for i in range(8)
    ]

    result = clarification("remove Gardens by the Bay on sunday", days=eight)

    assert result.reason == "ambiguous_date"
    assert len(result.choices) == 2


def test_contradictory_requests_are_not_merged() -> None:
    assert clarification("make it relaxed but also packed").reason == "scope_conflict"
    assert (
        clarification("remove Maxwell Food Centre and Singapore Flyer").reason == "scope_conflict"
    )
    assert (
        clarification("remove Maxwell Food Centre on day 1 and day 2").reason == "scope_conflict"
    )


# --------------------------------------------------------------------------- #
# Pace, interests, themes, day-local scope                                       #
# --------------------------------------------------------------------------- #


def test_a_trip_wide_pace_change_is_a_brief_patch_on_every_date() -> None:
    result = route("slow down, make it more relaxed")

    assert isinstance(result, ScopedItineraryReplan)
    assert result.scope == "trip"
    assert len(result.affected_dates) == 4
    assert result.patch is not None
    (entry,) = result.patch.entries
    assert entry.question_id is QuestionId.DAILY_RHYTHM
    assert isinstance(entry.payload, DailyRhythmPayload) and entry.payload.pace == "relaxed"
    assert entry.payload.day_start == "normal"  # untouched fields come from the current brief


def test_a_pace_change_on_one_day_is_a_day_local_override_not_a_global_change() -> None:
    result = route("keep day 2 relaxed")

    assert isinstance(result, ScopedItineraryReplan)
    assert result.scope == "dates" and result.affected_dates == [date(2026, 11, 2)]


def test_interests_and_themes() -> None:
    interests = route("I want more museums")
    theme = route("make day 3 about nature")

    assert isinstance(interests, ScopedItineraryReplan) and interests.patch is not None
    payload = interests.patch.entries[0].payload
    assert isinstance(payload, ExperiencesFoodPayload)
    assert payload.interests == ["food", "museums"]
    assert isinstance(theme, ScopedItineraryReplan)
    assert theme.scope == "dates" and theme.day_theme == "nature"
    assert theme.affected_dates == [date(2026, 11, 3)]


# --------------------------------------------------------------------------- #
# Numbers and dates need exact support                                           #
# --------------------------------------------------------------------------- #


def test_exact_iso_dates_become_a_validated_patch() -> None:
    result = route("change the dates to 2026-11-10 to 2026-11-14")

    assert isinstance(result, ProviderInvalidatingChange)
    (entry,) = result.patch.entries
    assert isinstance(entry.payload, TripEssentialsPayload)
    assert (entry.payload.start_date, entry.payload.end_date) == (
        date(2026, 11, 10),
        date(2026, 11, 14),
    )
    assert entry.payload.origin == "DEL"  # everything else is preserved


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("change the dates to Nov 10 to Nov 14", "ambiguous_date"),
        ("change the dates to 2026-11-10", "ambiguous_date"),
        ("change the dates to 2026-11-10 to 2026-11-20", "ambiguous_date"),
        ("change the dates to 2026-13-45 to 2026-11-20", "ambiguous_date"),
    ],
)
def test_ambiguous_or_invalid_dates_are_clarified(text: str, reason: str) -> None:
    assert clarification(text).reason == reason


def test_a_traveler_count_keeps_the_party_consistent() -> None:
    result = route("change it to 3 travelers")

    assert isinstance(result, ProviderInvalidatingChange)
    by_id = {e.question_id: e.payload for e in result.patch.entries}
    essentials = by_id[QuestionId.TRIP_ESSENTIALS]
    party = by_id[QuestionId.PURPOSE_AND_PARTY]
    assert isinstance(essentials, TripEssentialsPayload) and essentials.travelers == 3
    assert isinstance(party, PurposePartyPayload) and party.adults == 3


def test_a_traveler_count_that_leaves_no_adult_is_clarified() -> None:
    brief = make_brief(
        purpose_and_party=PurposePartyPayload(purpose="family", adults=2, children_ages=[6, 9]),
        trip_essentials=TripEssentialsPayload(
            origin="DEL",
            destination="SIN",
            start_date=START,
            end_date=date(2026, 11, 5),
            travelers=4,
        ),
    )

    result = classify_command("change it to 2 travelers", routing_context(brief))

    assert isinstance(result, ClarificationRequired) and result.reason == "ambiguous_amount"


def test_rooms_cabin_and_destination_are_exact_fields() -> None:
    rooms = route("we need 2 rooms")
    cabin = route("fly business class")
    nonstop = route("only nonstop flights")
    destination = classify_command(
        "change the destination to BOM", routing_context()
    )

    assert isinstance(rooms, ProviderInvalidatingChange)
    stay = rooms.patch.entries[0].payload
    assert isinstance(stay, StayPreferencesPayload) and stay.room_count == 2
    assert isinstance(cabin, ProviderInvalidatingChange)
    flight = cabin.patch.entries[0].payload
    assert isinstance(flight, FlightPreferencesPayload) and flight.cabin == "business"
    assert isinstance(nonstop, ProviderInvalidatingChange)
    assert isinstance(destination, ProviderInvalidatingChange)
    essentials = destination.patch.entries[0].payload
    assert isinstance(essentials, TripEssentialsPayload) and essentials.destination == "BOM"
    assert (
        clarification("change the destination to somewhere warm").reason == "needs_detail"
    )
    assert clarification("we need 30 rooms").reason == "ambiguous_amount"


# --------------------------------------------------------------------------- #
# Wallet, objective, explanation, profile, unsupported claims                     #
# --------------------------------------------------------------------------- #


def test_wallet_and_objective_requests_carry_no_balances() -> None:
    adopt = route("use my current wallet")
    objective = route("optimize for lowest cash")
    both = route("update my cards and prioritize value")

    assert adopt == WalletOrObjectiveChange(adopt_current_wallet=True)
    assert objective == WalletOrObjectiveChange(objective="lowest_cash")
    assert isinstance(both, WalletOrObjectiveChange)
    assert both.adopt_current_wallet and both.objective == "highest_value"
    assert set(WalletOrObjectiveChange.model_fields) == {
        "kind",
        "adopt_current_wallet",
        "objective",
        "points_priority",
    }


def test_an_objective_change_needs_an_existing_budget_answer() -> None:
    brief = make_brief(budget_and_objective=None)

    result = classify_command("optimize for lowest cash", routing_context(brief))

    assert isinstance(result, ClarificationRequired) and result.reason == "needs_detail"


def test_explanations_reference_an_existing_artifact_and_topic() -> None:
    why = route("why did you pick the Singapore Airlines flight")
    card = route("which card should I use for the Singapore Airlines flight")
    priced = route("how was the Marina Bay hotel priced")

    assert why == ExplanationRequest(
        target_kind="cost_line", target_id="flight:SQ", topic="why_chosen"
    )
    assert isinstance(card, ExplanationRequest) and card.topic == "payment_card"
    assert isinstance(priced, ExplanationRequest) and priced.topic == "how_priced"
    assert route("why is the sky blue") is None  # not about any artifact: not ours to answer


def test_profile_proposals_are_typed_per_section() -> None:
    seat = route("remember that I always want a window seat")
    pace = route("from now on keep my trips relaxed")

    assert isinstance(seat, ProfileUpdateAction) and seat.section == "flight"
    assert isinstance(seat.candidate, FlightPreferencesPayload) and seat.candidate.seat == "window"
    assert isinstance(pace, ProfileUpdateAction) and pace.section == "rhythm"
    assert isinstance(pace.candidate, DailyRhythmPayload) and pace.candidate.pace == "relaxed"


def test_accessibility_guarantees_are_never_promised() -> None:
    result = clarification("make sure everything is wheelchair accessible")

    assert result.reason == "unsupported"
    assert "can't verify" in result.question


@pytest.mark.parametrize(
    "text",
    ["what a lovely plan", "thanks!", "what is the weather like in Singapore", "hello"],
)
def test_unrecognised_text_is_left_for_the_one_allowed_interpretation(text: str) -> None:
    assert route(text) is None


@pytest.mark.parametrize("text", ["", "   \n"])
def test_empty_commands_are_rejected(text: str) -> None:
    with pytest.raises(PostPlanInputError):
        route(text)


def test_oversize_commands_are_rejected_not_truncated() -> None:
    with pytest.raises(PostPlanInputError):
        route("remove " + "x" * 2000)
    assert route("remove Maxwell Food Centre" + " " * 1900) is not None


def test_routing_is_deterministic() -> None:
    first = route("replace Singapore Flyer with Jewel Changi Airport")
    second = route("replace Singapore Flyer with Jewel Changi Airport")

    assert first == second


# --------------------------------------------------------------------------- #
# Patches and action models reject anything outside the approved shapes           #
# --------------------------------------------------------------------------- #


def test_a_patch_replaces_whole_payloads_and_keeps_untouched_sections() -> None:
    brief = make_brief()
    patch = BriefPatch(
        entries=[
            PatchEntry(
                question_id=QuestionId.DAILY_RHYTHM,
                payload=DailyRhythmPayload(
                    pace="packed", day_start="early", evening_style="late", day_trip_appetite="one"
                ),
            )
        ]
    )

    patched = apply_brief_patch(brief, patch)

    assert patched.daily_rhythm is not None and patched.daily_rhythm.pace == "packed"
    assert patched.trip_essentials == brief.trip_essentials
    assert patched.experiences_and_food == brief.experiences_and_food
    assert brief.daily_rhythm is not None and brief.daily_rhythm.pace == "moderate"


def test_a_patch_can_add_an_adaptive_detail_and_clear_its_delegation() -> None:
    brief = make_brief(delegated_questions=[QuestionId.FOOD_DEPTH])
    patch = BriefPatch(
        entries=[
            PatchEntry(
                question_id=QuestionId.FOOD_DEPTH,
                payload=AdaptiveDetailPayload(detail="street food over restaurants"),
            )
        ]
    )

    patched = apply_brief_patch(brief, patch)

    assert patched.adaptive_details[QuestionId.FOOD_DEPTH].detail == "street food over restaurants"
    assert QuestionId.FOOD_DEPTH not in patched.delegated_questions


def test_a_patch_that_breaks_party_consistency_is_rejected() -> None:
    patch = BriefPatch(
        entries=[
            PatchEntry(
                question_id=QuestionId.TRIP_ESSENTIALS,
                payload=TripEssentialsPayload(
                    origin="DEL",
                    destination="SIN",
                    start_date=START,
                    end_date=date(2026, 11, 5),
                    travelers=5,
                ),
            )
        ]
    )

    with pytest.raises(ValueError, match="traveler count"):
        apply_brief_patch(make_brief(), patch)


def test_patch_validation_is_strict() -> None:
    wrong_type = {"question_id": "daily_rhythm", "payload": {"origin": "DEL"}}
    with pytest.raises(ValidationError):
        BriefPatch.model_validate({"entries": [wrong_type]})
    with pytest.raises(ValidationError):
        BriefPatch.model_validate({"entries": []})
    entry = PatchEntry(
        question_id=QuestionId.DAILY_RHYTHM,
        payload=DailyRhythmPayload(
            pace="relaxed", day_start="normal", evening_style="quiet", day_trip_appetite="none"
        ),
    )
    with pytest.raises(ValidationError):
        BriefPatch(entries=[entry, entry])
    with pytest.raises(ValidationError):
        PatchEntry(
            question_id=QuestionId.DAILY_RHYTHM,
            payload=AdaptiveDetailPayload(detail="not a rhythm"),
        )


def test_actions_reject_arbitrary_fields_providers_and_client_authored_impact() -> None:
    edit = {
        "kind": "deterministic_edit",
        "edit": {"op": "remove_item", "poi_id": "p", "day_index": 0},
    }
    ADAPTER.validate_python(edit)
    for extra in ({"provider": "gondola"}, {"domains": ["flight"]}, {"impact": {}}, {"tool": "x"}):
        with pytest.raises(ValidationError):
            ADAPTER.validate_python({**edit, **extra})
    trip_patch = BriefPatch(
        entries=[
            PatchEntry(
                question_id=QuestionId.TRIP_ESSENTIALS,
                payload=TripEssentialsPayload(
                    origin="DEL",
                    destination="SIN",
                    start_date=START,
                    end_date=date(2026, 11, 5),
                    travelers=2,
                ),
            )
        ]
    )
    with pytest.raises(ValidationError):  # a scoped replan may not smuggle in a search change
        ScopedItineraryReplan(scope="trip", affected_dates=[START], patch=trip_patch)
    with pytest.raises(ValidationError):  # a day theme is bounded plain text
        ScopedItineraryReplan(
            scope="dates", affected_dates=[START], day_theme="visit https://evil.test now"
        )
    with pytest.raises(ValidationError):
        ScopedItineraryReplan(scope="dates", affected_dates=[START, START], day_theme="food")
    with pytest.raises(ValidationError):
        WalletOrObjectiveChange()
    with pytest.raises(ValidationError):
        ProfileUpdateAction(
            section="flight",
            candidate=DailyRhythmPayload(
                pace="relaxed", day_start="normal", evening_style="quiet", day_trip_appetite="none"
            ),
        )
    with pytest.raises(ValidationError):  # no card numbers, balances or credentials
        WalletOrObjectiveChange.model_validate(
            {"adopt_current_wallet": True, "points_balances": {"x": 1}}
        )
    assert UserWallet(card_ids=[]).card_ids == []


# --------------------------------------------------------------------------- #
# The pure package stays pure                                                    #
# --------------------------------------------------------------------------- #

ALLOWED_FIRST_PARTY = {"core", "planning"}
FORBIDDEN_EVERYWHERE = {"agents", "api", "gateway", "accounts", "ingestion", "httpx", "requests"}


def _imports(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_post_plan_module_imports_only_pure_domain_code() -> None:
    path = Path(__file__).resolve().parents[1] / "planning" / "post_plan.py"
    imported = _imports(path.read_text(encoding="utf-8"))

    assert not (imported & FORBIDDEN_EVERYWHERE), imported
    assert {"core", "planning"} <= imported  # the scan is looking at the right file
    assert imported - ALLOWED_FIRST_PARTY <= {
        "hashlib",
        "json",
        "re",
        "unicodedata",
        "collections",
        "datetime",
        "enum",
        "typing",
        "pydantic",
        "__future__",
    }


def test_the_purity_scan_has_teeth() -> None:
    assert _imports("import httpx\nfrom agents.llm import LLMClient") & FORBIDDEN_EVERYWHERE


def test_post_plan_module_calls_no_clock_or_randomness() -> None:
    path = Path(__file__).resolve().parents[1] / "planning" / "post_plan.py"
    forbidden = {"now", "today", "uuid4", "random", "randint", "token_urlsafe", "time"}
    called: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            func = node.func
            called.add(func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", ""))
    assert not (called & forbidden), called
    assert GALLERY.name and FLYER.name and JEWEL.name and MAXWELL.name  # shared fixtures in use
