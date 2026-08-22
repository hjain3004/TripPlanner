"""Consent-based travel preference storage (CP1).

Every leaf preference carries its own human-consent provenance (``source``)
and timestamp — there is no LLM-inference source in the closed set, because a
model's guess about what the user wants is never durable state on its own.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from accounts.models import (
    Cabin,
    ConstraintPreferences,
    ExperiencePreferences,
    FlightPreferences,
    OptimizationPreferences,
    PreferenceValue,
    RhythmPreferences,
    StayPreferences,
    TravelPreferenceProfile,
)
from accounts.store import AccountStore

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _user_store(tmp_path: Path) -> AccountStore:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    store.create_user(email="a@example.com", now=NOW, user_id="u1")
    return store


# --------------------------------------------------------------------------- #
# Provenance                                                                    #
# --------------------------------------------------------------------------- #


def test_preference_value_requires_an_explicit_human_source() -> None:
    value = PreferenceValue[str](
        value="business",
        source="user_confirmed_from_trip",
        updated_at=NOW,
    )
    assert value.source == "user_confirmed_from_trip"


def test_llm_inference_is_not_a_durable_preference_source() -> None:
    with pytest.raises(ValidationError):
        PreferenceValue[str](value="business", source="llm_inferred", updated_at=NOW)


def test_profile_groups_stable_travel_defaults() -> None:
    profile = TravelPreferenceProfile(
        user_id="u1",
        flight=FlightPreferences(
            cabin=PreferenceValue[Cabin](
                value="economy", source="user_profile_edit", updated_at=NOW
            )
        ),
        experiences=ExperiencePreferences(
            interests=PreferenceValue[list[str]](
                value=["food", "nature"],
                source="user_confirmed_from_trip",
                updated_at=NOW,
            )
        ),
        updated_at=NOW,
    )
    assert profile.flight.cabin is not None
    assert profile.experiences.interests is not None


def test_nested_preference_models_reject_unknown_sensitive_fields() -> None:
    with pytest.raises(ValidationError):
        FlightPreferences.model_validate({"pan": "4111111111111111"})


@pytest.mark.parametrize(
    "model, kwargs",
    [
        (FlightPreferences, {"pan": "4111111111111111"}),
        (StayPreferences, {"password": "hunter2"}),
        (RhythmPreferences, {"cvv": "123"}),
        (ExperiencePreferences, {"pin": "1234"}),
        (ConstraintPreferences, {"card_number": "4111111111111111"}),
        (OptimizationPreferences, {"bank_password": "hunter2"}),
    ],
)
def test_every_nested_preference_group_rejects_a_smuggled_secret(
    model: type, kwargs: dict[str, str]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(kwargs)


# --------------------------------------------------------------------------- #
# Deterministic list trimming / de-duplication                                 #
# --------------------------------------------------------------------------- #


def test_experience_interests_are_trimmed_deduped_and_casefolded() -> None:
    prefs = ExperiencePreferences(
        interests=PreferenceValue[list[str]](
            value=["  Food ", "Nature", "food", "", "   "],
            source="user_profile_edit",
            updated_at=NOW,
        )
    )
    assert prefs.interests is not None
    assert prefs.interests.value == ["food", "nature"]


def test_constraint_dietary_and_accessibility_casefold_and_dedupe() -> None:
    prefs = ConstraintPreferences(
        dietary=PreferenceValue[list[str]](
            value=["Vegetarian", "vegetarian", " Halal "],
            source="user_confirmed_from_trip",
            updated_at=NOW,
        ),
        accessibility=PreferenceValue[list[str]](
            value=["Wheelchair", "WHEELCHAIR", ""],
            source="user_confirmed_from_trip",
            updated_at=NOW,
        ),
    )
    assert prefs.dietary is not None
    assert prefs.dietary.value == ["vegetarian", "halal"]
    assert prefs.accessibility is not None
    assert prefs.accessibility.value == ["wheelchair"]


def test_stay_loyalty_programs_and_room_needs_preserve_display_case_but_dedupe() -> None:
    prefs = StayPreferences(
        loyalty_programs=PreferenceValue[list[str]](
            value=["Marriott Bonvoy", " Hilton Honors", "Marriott Bonvoy", ""],
            source="user_profile_edit",
            updated_at=NOW,
        ),
        room_needs=PreferenceValue[list[str]](
            value=["Crib", "crib", " Extra Pillows "],
            source="user_profile_edit",
            updated_at=NOW,
        ),
    )
    assert prefs.loyalty_programs is not None
    assert prefs.loyalty_programs.value == ["Marriott Bonvoy", "Hilton Honors"]
    assert prefs.room_needs is not None
    assert prefs.room_needs.value == ["Crib", "crib", "Extra Pillows"]


# --------------------------------------------------------------------------- #
# Enum ranges and numeric bounds                                               #
# --------------------------------------------------------------------------- #


def test_flight_cabin_rejects_a_value_outside_the_enum() -> None:
    with pytest.raises(ValidationError):
        FlightPreferences(
            cabin=PreferenceValue[str](
                value="super-first", source="user_profile_edit", updated_at=NOW
            )
        )


def test_flight_max_stops_rejects_an_out_of_range_value() -> None:
    with pytest.raises(ValidationError):
        FlightPreferences(
            max_stops=PreferenceValue[int](
                value=4, source="user_profile_edit", updated_at=NOW
            )
        )
    with pytest.raises(ValidationError):
        FlightPreferences(
            max_stops=PreferenceValue[int](
                value=-1, source="user_profile_edit", updated_at=NOW
            )
        )


def test_rhythm_downtime_and_transit_minutes_reject_negative_and_over_bound() -> None:
    with pytest.raises(ValidationError):
        RhythmPreferences(
            downtime_minutes=PreferenceValue[int](
                value=-1, source="user_profile_edit", updated_at=NOW
            )
        )
    with pytest.raises(ValidationError):
        RhythmPreferences(
            downtime_minutes=PreferenceValue[int](
                value=361, source="user_profile_edit", updated_at=NOW
            )
        )
    with pytest.raises(ValidationError):
        RhythmPreferences(
            transit_tolerance_minutes=PreferenceValue[int](
                value=241, source="user_profile_edit", updated_at=NOW
            )
        )


def test_optimization_objective_rejects_a_value_outside_the_enum() -> None:
    with pytest.raises(ValidationError):
        OptimizationPreferences(
            objective=PreferenceValue[str](
                value="cheapest", source="user_profile_edit", updated_at=NOW
            )
        )


# --------------------------------------------------------------------------- #
# Persistence, export, and deletion through AccountStore                       #
# --------------------------------------------------------------------------- #


def test_travel_preferences_upsert_and_round_trip(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    first = TravelPreferenceProfile(user_id="u1", updated_at=NOW)
    store.put_travel_preferences(first)
    updated = first.model_copy(
        update={
            "flight": FlightPreferences(
                cabin=PreferenceValue[str](
                    value="economy", source="user_profile_edit", updated_at=NOW
                )
            )
        }
    )
    store.put_travel_preferences(updated)
    assert store.get_travel_preferences("u1") == updated


def test_get_travel_preferences_returns_none_when_absent(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    assert store.get_travel_preferences("u1") is None


def test_put_travel_preferences_rejects_an_unknown_user(tmp_path: Path) -> None:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    with pytest.raises(ValueError):
        store.put_travel_preferences(
            TravelPreferenceProfile(user_id="ghost", updated_at=NOW)
        )


def test_privacy_export_and_delete_include_travel_preferences(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    store.put_travel_preferences(TravelPreferenceProfile(user_id="u1", updated_at=NOW))
    assert store.export_user("u1", now=NOW).travel_preferences is not None
    store.delete_user("u1")
    assert store.get_travel_preferences("u1") is None
