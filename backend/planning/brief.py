"""Deterministic Trip Brief assembly and confirmation (CP1 task 6).

Every function here is a pure, referentially transparent transformation over
an already-``reviewing`` ``PlanningSession`` -- no LLM call, no database
write, no wall-clock or random-id access (``now`` is always a caller-injected
parameter). Assumption prose is a small closed set of fixed, calm templates
(see ``_ASSUMPTION_TEMPLATE``), never LLM-generated text.

``assemble_trip_brief`` resolves a completed interview into a fully-typed
``TripBrief``: required facts, optional core answers (``None`` when
delegated), adaptive details keyed by question id, any durable profile
defaults actually applied for a delegated section, and a fixed assumption
string per delegated question.

``build_profile_update_proposals`` turns each eligible answered core section
(``memory_scope="propose_profile_update"``) into typed, data-only
``ProfileUpdateProposal`` candidates. It never calls
``accounts.store.AccountStore.put_travel_preferences`` -- it doesn't even
receive a store. A future milestone (CP2) is the only place a human-approved
write happens.

``confirm_trip_brief`` is the sole way a session's first
``ConfirmedBriefSnapshot`` is created. It re-derives the brief from the
session's own current state and requires the caller's brief to match it
byte-for-byte (canonical ``model_dump_json()`` equality) before accepting it
-- the anti-tamper, anti-staleness mechanism. CP1 exposes no amendment path:
an already-confirmed session (``confirmed_briefs`` non-empty) can never be
reconfirmed; a later milestone (CP2) owns revision 2+.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, TypeVar

from pydantic import BaseModel

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
from planning.answers import (
    AdaptiveDetailPayload,
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
from planning.contracts import (
    ConfirmedBriefSnapshot,
    PlanningSession,
    PlanningSessionStatus,
    ProfileUpdateProposal,
    TripBrief,
)
from planning.policy import StaleSessionVersionError
from planning.question_catalog import DEFAULT_QUESTION_CATALOG, QuestionDefinition

ProfileSection = Literal["flight", "stay", "rhythm", "experiences", "constraints", "optimization"]

_PREFERENCE_SOURCE: Literal["user_confirmed_from_trip"] = "user_confirmed_from_trip"


class BriefNotReadyError(ValueError):
    """The session is not ``reviewing``, so no brief can be assembled or confirmed."""


class BriefMismatchError(ValueError):
    """The supplied brief does not byte-match a freshly assembled brief for this session."""


class BriefAlreadyConfirmedError(ValueError):
    """The session already has a confirmed brief; CP1 has no amendment transition."""


_CATALOG_BY_ID: dict[QuestionId, QuestionDefinition] = {
    definition.id: definition for definition in DEFAULT_QUESTION_CATALOG
}
_CATALOG_ORDER: tuple[QuestionId, ...] = tuple(
    definition.id for definition in DEFAULT_QUESTION_CATALOG
)

# One fixed, calm template per delegable question. Deliberately does not
# branch on whether a durable profile default was actually applied for that
# section -- `applied_profile_sections`/`applied_profile_preferences` are the
# separate, structured signal for "a saved default was reused"; this prose
# only ever states what the system will practically assume for *this trip*.
_ASSUMPTION_TEMPLATE: dict[QuestionId, str] = {
    QuestionId.PURPOSE_AND_PARTY: (
        "No purpose or travel-party details supplied; assume solo leisure "
        "travel for planning purposes."
    ),
    QuestionId.BUDGET_AND_OBJECTIVE: (
        "No budget or objective supplied; assume a balanced budget "
        "optimizing for overall value."
    ),
    QuestionId.FLIGHT_PREFERENCES: (
        "No flight preference supplied; choose a practical option within "
        "the confirmed objective."
    ),
    QuestionId.STAY_PREFERENCES: (
        "No stay preference supplied; choose a well-located, balanced "
        "option within budget."
    ),
    QuestionId.DAILY_RHYTHM: (
        "No daily rhythm supplied; assume a moderate pace with balanced "
        "downtime."
    ),
    QuestionId.EXPERIENCES_AND_FOOD: (
        "No experience or food preference supplied; balance iconic and "
        "local options."
    ),
    QuestionId.CELEBRATION_DETAILS: (
        "No celebration details supplied; plan a pleasant, low-key touch "
        "appropriate to the occasion."
    ),
    QuestionId.CHILDREN_NEEDS: (
        "No children's needs supplied; assume standard family-friendly "
        "planning."
    ),
    QuestionId.MOBILITY_DETAILS: (
        "No mobility details supplied; assume standard accessibility needs."
    ),
    QuestionId.POINTS_STRATEGY: (
        "No points strategy supplied; use points where it clearly beats "
        "paying cash."
    ),
    QuestionId.FLIGHT_TRADEOFF: (
        "No flight trade-off supplied; favor a practical balance of price "
        "and convenience."
    ),
    QuestionId.HOTEL_TRADEOFF: (
        "No hotel trade-off supplied; favor a practical balance of "
        "location and price."
    ),
    QuestionId.FOOD_DEPTH: (
        "No food depth supplied; balance iconic and local dining options."
    ),
}

_PROFILE_SECTION_ATTR: dict[str, str] = {
    "flight": "flight",
    "stay": "stay",
    "rhythm": "rhythm",
    "experiences": "experiences",
    "constraints": "constraints",
    "optimization": "optimization",
}

P = TypeVar("P", bound=BaseModel)
T = TypeVar("T")


# --------------------------------------------------------------------------- #
# assemble_trip_brief                                                          #
# --------------------------------------------------------------------------- #


def _answer_payload(
    session: PlanningSession, question_id: QuestionId, payload_type: type[P]
) -> P | None:
    """The typed payload for ``question_id``, or ``None`` if unanswered,
    delegated, or (defensively) not an instance of the expected type.
    """
    answer = session.answers.get(question_id)
    if answer is None:
        return None
    payload = answer.payload
    if isinstance(payload, payload_type):
        return payload
    return None


def _required_payload(
    session: PlanningSession, question_id: QuestionId, payload_type: type[P]
) -> P:
    payload = _answer_payload(session, question_id, payload_type)
    if payload is None:
        raise BriefNotReadyError(
            f"{question_id.value} is required and must be answered (not "
            "delegated) before brief assembly"
        )
    return payload


def _delegated_in_catalog_order(session: PlanningSession) -> list[QuestionId]:
    return [
        question_id
        for question_id in _CATALOG_ORDER
        if (answer := session.answers.get(question_id)) is not None and answer.delegated
    ]


def _adaptive_details_in_catalog_order(
    session: PlanningSession,
) -> dict[QuestionId, AdaptiveDetailPayload]:
    details: dict[QuestionId, AdaptiveDetailPayload] = {}
    for question_id in _CATALOG_ORDER:
        payload = _answer_payload(session, question_id, AdaptiveDetailPayload)
        if payload is not None:
            details[question_id] = payload
    return details


def _section_has_any_value(section: BaseModel) -> bool:
    return any(value is not None for value in section.__dict__.values())


def _profile_defaults_and_assumptions(
    session: PlanningSession, delegated: list[QuestionId]
) -> tuple[list[str], TravelPreferenceProfile | None, list[str]]:
    assumptions = [_ASSUMPTION_TEMPLATE[question_id] for question_id in delegated]

    applied_sections: list[str] = []
    profile_defaults = session.profile_defaults
    if profile_defaults is not None:
        seen: set[str] = set()
        for question_id in delegated:
            for section in _CATALOG_BY_ID[question_id].profile_sections:
                if section in seen:
                    continue
                group = getattr(profile_defaults, _PROFILE_SECTION_ATTR[section])
                if _section_has_any_value(group):
                    seen.add(section)
                    applied_sections.append(section)

    applied_preferences: TravelPreferenceProfile | None = None
    if applied_sections and profile_defaults is not None:
        overrides = {
            section: getattr(profile_defaults, _PROFILE_SECTION_ATTR[section])
            for section in applied_sections
        }
        applied_preferences = TravelPreferenceProfile(
            user_id=profile_defaults.user_id,
            updated_at=profile_defaults.updated_at,
            **overrides,
        )

    return applied_sections, applied_preferences, assumptions


def assemble_trip_brief(session: PlanningSession) -> TripBrief:
    if session.status is not PlanningSessionStatus.REVIEWING:
        raise BriefNotReadyError("session must be reviewing before brief assembly")
    essentials = _required_payload(session, QuestionId.TRIP_ESSENTIALS, TripEssentialsPayload)
    constraints = _required_payload(session, QuestionId.HARD_CONSTRAINTS, HardConstraintsPayload)
    delegated = _delegated_in_catalog_order(session)
    applied_sections, applied_preferences, assumptions = _profile_defaults_and_assumptions(
        session, delegated
    )
    return TripBrief(
        home=session.home,
        trip_essentials=essentials,
        purpose_and_party=_answer_payload(
            session, QuestionId.PURPOSE_AND_PARTY, PurposePartyPayload
        ),
        budget_and_objective=_answer_payload(
            session, QuestionId.BUDGET_AND_OBJECTIVE, BudgetObjectivePayload
        ),
        flight_preferences=_answer_payload(
            session, QuestionId.FLIGHT_PREFERENCES, FlightPreferencesPayload
        ),
        stay_preferences=_answer_payload(
            session, QuestionId.STAY_PREFERENCES, StayPreferencesPayload
        ),
        daily_rhythm=_answer_payload(session, QuestionId.DAILY_RHYTHM, DailyRhythmPayload),
        experiences_and_food=_answer_payload(
            session, QuestionId.EXPERIENCES_AND_FOOD, ExperiencesFoodPayload
        ),
        hard_constraints=constraints,
        adaptive_details=_adaptive_details_in_catalog_order(session),
        delegated_questions=delegated,
        applied_profile_preferences=applied_preferences,
        applied_profile_sections=applied_sections,
        assumptions=assumptions,
        wallet=session.wallet,
    )


# --------------------------------------------------------------------------- #
# build_profile_update_proposals                                               #
# --------------------------------------------------------------------------- #


def _wrap(value: T, *, now: datetime) -> PreferenceValue[T]:
    return PreferenceValue[T](value=value, source=_PREFERENCE_SOURCE, updated_at=now)


def _wrap_optional(value: T | None, *, now: datetime) -> PreferenceValue[T] | None:
    if value is None:
        return None
    return _wrap(value, now=now)


def _wrap_list_or_none(values: list[str], *, now: datetime) -> PreferenceValue[list[str]] | None:
    # An answered-but-empty list means nothing was actually told to us --
    # treated identically to "not answered" rather than persisting a hollow
    # durable preference with fabricated provenance (see DEVIATIONS.md).
    if not values:
        return None
    return _wrap(list(values), now=now)


def _optimization_from_payload(
    payload: BudgetObjectivePayload, *, now: datetime
) -> OptimizationPreferences:
    return OptimizationPreferences(
        objective=_wrap(payload.objective, now=now),
        points_priority=_wrap(payload.points_priority, now=now),
    )


def _flight_from_payload(payload: FlightPreferencesPayload, *, now: datetime) -> FlightPreferences:
    cabin: PreferenceValue[Cabin] | None = None
    if payload.cabin != "no_preference":
        cabin = _wrap(payload.cabin, now=now)
    schedule: PreferenceValue[
        Literal["morning", "afternoon", "evening", "overnight", "no_preference"]
    ] | None = None
    if payload.schedule != "no_preference":
        schedule = _wrap(payload.schedule, now=now)
    seat: PreferenceValue[Literal["aisle", "window", "middle", "no_preference"]] | None = None
    if payload.seat != "no_preference":
        seat = _wrap(payload.seat, now=now)
    return FlightPreferences(
        cabin=cabin,
        max_stops=_wrap_optional(payload.max_stops, now=now),
        schedule=schedule,
        checked_baggage=_wrap_optional(payload.checked_baggage, now=now),
        airport_flexible=_wrap_optional(payload.airport_flexible, now=now),
        seat=seat,
    )


def _stay_from_payload(payload: StayPreferencesPayload, *, now: datetime) -> StayPreferences:
    tradeoff: PreferenceValue[Literal["location", "price", "balanced"]] | None = None
    if payload.location_price_tradeoff != "no_preference":
        tradeoff = _wrap(payload.location_price_tradeoff, now=now)
    return StayPreferences(
        lodging_styles=_wrap_list_or_none(payload.lodging_styles, now=now),
        location_priorities=_wrap_list_or_none(payload.neighborhood_priorities, now=now),
        room_needs=_wrap_list_or_none(payload.room_needs, now=now),
        location_price_tradeoff=tradeoff,
    )


def _rhythm_from_payload(payload: DailyRhythmPayload, *, now: datetime) -> RhythmPreferences:
    pace: PreferenceValue[Literal["relaxed", "moderate", "packed"]] | None = None
    if payload.pace != "no_preference":
        pace = _wrap(payload.pace, now=now)
    day_start: PreferenceValue[Literal["early", "normal", "late"]] | None = None
    if payload.day_start != "no_preference":
        day_start = _wrap(payload.day_start, now=now)
    evening_style: PreferenceValue[Literal["quiet", "flexible", "late"]] | None = None
    if payload.evening_style != "no_preference":
        evening_style = _wrap(payload.evening_style, now=now)
    day_trip_appetite: PreferenceValue[Literal["none", "one", "multiple"]] | None = None
    if payload.day_trip_appetite != "no_preference":
        day_trip_appetite = _wrap(payload.day_trip_appetite, now=now)
    return RhythmPreferences(
        pace=pace,
        day_start=day_start,
        evening_style=evening_style,
        downtime_minutes=_wrap_optional(payload.downtime_minutes, now=now),
        transit_tolerance_minutes=_wrap_optional(payload.transit_tolerance_minutes, now=now),
        day_trip_appetite=day_trip_appetite,
    )


def _experiences_from_payload(
    payload: ExperiencesFoodPayload, *, now: datetime
) -> ExperiencePreferences:
    iconic_local_balance: PreferenceValue[Literal["iconic", "balanced", "local"]] | None = None
    if payload.iconic_local_balance != "no_preference":
        iconic_local_balance = _wrap(payload.iconic_local_balance, now=now)
    return ExperiencePreferences(
        interests=_wrap_list_or_none(payload.interests, now=now),
        food_interests=_wrap_list_or_none(payload.food_interests, now=now),
        iconic_local_balance=iconic_local_balance,
        nightlife=_wrap_optional(payload.nightlife, now=now),
        shopping=_wrap_optional(payload.shopping, now=now),
    )


def _constraints_from_payload(
    payload: HardConstraintsPayload, *, now: datetime
) -> ConstraintPreferences:
    return ConstraintPreferences(
        dietary=_wrap_list_or_none(payload.dietary, now=now),
        accessibility=_wrap_list_or_none(payload.accessibility, now=now),
    )


def _candidate_profile(
    session: PlanningSession, *, section: ProfileSection, group: BaseModel, now: datetime
) -> TravelPreferenceProfile:
    """A candidate copy of the current profile (or a fresh empty one) with
    only ``section`` replaced -- every other group is carried through
    untouched, including its own existing provenance.
    """
    base = session.profile_defaults
    if base is None:
        base = TravelPreferenceProfile(user_id=session.user_id, updated_at=now)
    candidate = base.model_copy(update={section: group})
    return TravelPreferenceProfile.model_validate(candidate.model_dump())


def build_profile_update_proposals(
    session: PlanningSession, *, now: datetime
) -> list[ProfileUpdateProposal]:
    proposals: list[ProfileUpdateProposal] = []
    for question_id in _CATALOG_ORDER:
        answer = session.answers.get(question_id)
        if answer is None or answer.memory_scope != "propose_profile_update":
            continue
        payload = answer.payload
        section: ProfileSection
        group: BaseModel
        if isinstance(payload, BudgetObjectivePayload):
            section = "optimization"
            group = _optimization_from_payload(payload, now=now)
        elif isinstance(payload, FlightPreferencesPayload):
            section = "flight"
            group = _flight_from_payload(payload, now=now)
        elif isinstance(payload, StayPreferencesPayload):
            section = "stay"
            group = _stay_from_payload(payload, now=now)
        elif isinstance(payload, DailyRhythmPayload):
            section = "rhythm"
            group = _rhythm_from_payload(payload, now=now)
        elif isinstance(payload, ExperiencesFoodPayload):
            section = "experiences"
            group = _experiences_from_payload(payload, now=now)
        elif isinstance(payload, HardConstraintsPayload):
            section = "constraints"
            group = _constraints_from_payload(payload, now=now)
        else:
            # Defense-in-depth: InterviewAnswer's own model validator
            # (planning/answers.py) already guarantees memory_scope=
            # "propose_profile_update" only ever accompanies one of the six
            # payload types handled above.
            continue
        candidate = _candidate_profile(session, section=section, group=group, now=now)
        # ``no_preference`` and an entirely empty payload carry no durable
        # user preference. Never propose replacing a populated profile group
        # with an empty/no-preference group.
        if not _section_has_any_value(group):
            continue
        proposals.append(
            ProfileUpdateProposal(
                proposal_id=f"{session.id}:{session.version}:{section}",
                section=section,
                candidate_profile=candidate,
                source_question_id=question_id,
            )
        )
    return proposals


# --------------------------------------------------------------------------- #
# confirm_trip_brief                                                           #
# --------------------------------------------------------------------------- #


def confirm_trip_brief(
    session: PlanningSession,
    brief: TripBrief,
    *,
    expected_version: int,
    now: datetime,
) -> PlanningSession:
    # Checked first so the ordinary "confirm a second time" call -- which
    # naturally leaves the session in `confirmed`, not `reviewing` -- reports
    # the precise BriefAlreadyConfirmedError rather than the more generic
    # BriefNotReadyError (see DEVIATIONS.md for this ordering decision).
    if session.confirmed_briefs:
        raise BriefAlreadyConfirmedError(
            "this session already has a confirmed brief; CP1 has no "
            "amendment transition (see CP2)"
        )
    if session.status is not PlanningSessionStatus.REVIEWING:
        raise BriefNotReadyError("session must be reviewing before brief confirmation")
    if expected_version != session.version:
        raise StaleSessionVersionError(
            f"expected_version={expected_version} does not match "
            f"session.version={session.version}"
        )
    reassembled = assemble_trip_brief(session)
    if reassembled.model_dump_json() != brief.model_dump_json():
        raise BriefMismatchError(
            "the supplied brief does not byte-match a freshly assembled "
            "brief for this session; it may be stale or tampered with"
        )

    proposals = build_profile_update_proposals(session, now=now)
    snapshot = ConfirmedBriefSnapshot(
        revision=len(session.confirmed_briefs) + 1,
        brief=brief,
        confirmed_at=now,
    )
    candidate = session.model_copy(
        update={
            "status": PlanningSessionStatus.CONFIRMED,
            "version": session.version + 1,
            "updated_at": now,
            "confirmed_briefs": [*session.confirmed_briefs, snapshot],
            "pending_profile_updates": proposals,
        }
    )
    return PlanningSession.model_validate(candidate.model_dump())
