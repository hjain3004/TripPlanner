from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from agents.models import DraftItinerary, ItineraryDay, ItineraryItem, RetrievalContext, TripSpec
from core.models import Area, POI, Channel, Provenance, UserWallet
from evals.judge import (
    HostedJudgeClient,
    JudgeCallError,
    JudgeScores,
    JudgeVerdict,
    ScriptedJudgeClient,
    build_judge_prompt,
    complete_judge_with_repair,
)


PROV = Provenance(
    source_type="manual_curation",
    last_verified=date(2026, 7, 25),
    verified_by="UNVERIFIED",
    needs_verification=True,
    confidence=1.0,
)


def _valid_scores() -> dict[str, int]:
    return {
        "groundedness": 5,
        "interest_match": 4,
        "geographic_coherence": 5,
        "pacing": 4,
        "budget_respect": 4,
    }


def _spec() -> TripSpec:
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
        wallet=UserWallet(card_ids=["hdfc-infinia"], points_balances={}),
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
            )
        ],
    )


def _retrieval() -> RetrievalContext:
    poi = POI(
        id="sg-gardens-by-the-bay",
        city="Singapore",
        name="Gardens by the Bay",
        tags=["nature", "landmark"],
        typical_duration_min=180,
        price_minor=5300,
        currency="SGD",
        lat=1.2816,
        lon=103.8636,
        area="marina_bay",
        open_hours="09:00-21:00",
        booking_channel=Channel.OTA_GENERIC,
        merchant_hint="Klook",
        description="Curated garden attraction.",
        provenance=PROV,
    )
    area = Area(
        id="marina_bay",
        city="Singapore",
        name="Marina Bay",
        good_for_tags=["nature", "landmark"],
        centrality_score=0.95,
        provenance=PROV,
    )
    return RetrievalContext(
        pois=[poi],
        areas=[area],
        poi_rows=["sg-gardens-by-the-bay | Gardens by the Bay | marina_bay"],
        area_rows=["marina_bay | Marina Bay | nature,landmark"],
    )


def test_judge_scores_accepts_exact_five_dimensions() -> None:
    verdict = JudgeVerdict(scores=_valid_scores(), rationale="All rubric dimensions present.")

    assert verdict.scores.groundedness == 5
    assert verdict.scores.interest_match == 4


def test_judge_scores_rejects_missing_dimension() -> None:
    payload = _valid_scores()
    payload.pop("pacing")

    with pytest.raises(ValidationError):
        JudgeScores.model_validate(payload)


def test_judge_scores_rejects_out_of_range_score() -> None:
    payload = {**_valid_scores(), "budget_respect": 6}

    with pytest.raises(ValidationError):
        JudgeScores.model_validate(payload)


def test_judge_scores_rejects_invented_dimension() -> None:
    payload = {**_valid_scores(), "photo_quality": 5}

    with pytest.raises(ValidationError):
        JudgeScores.model_validate(payload)


def test_scripted_judge_counts_invocations_and_repairs_once() -> None:
    client = ScriptedJudgeClient(
        {
            "quality": [
                {"scores": {"groundedness": 0}, "rationale": "bad"},
                {"scores": _valid_scores(), "rationale": "corrected"},
            ]
        }
    )

    verdict = complete_judge_with_repair(
        client,
        node="quality",
        system="system",
        user="user",
    )

    assert verdict.rationale == "corrected"
    assert client.invocations["quality"] == 2


def test_scripted_judge_rejects_malformed_json_after_repair() -> None:
    client = ScriptedJudgeClient({"quality": ["not json", "{still not json"]})

    with pytest.raises(JudgeCallError):
        complete_judge_with_repair(
            client,
            node="quality",
            system="system",
            user="user",
        )


def test_hosted_judge_is_disabled_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRIPWISE_JUDGE_API_KEY", raising=False)
    client = HostedJudgeClient()

    with pytest.raises(JudgeCallError, match="disabled"):
        client.complete_json(node="quality", system="system", user="user")


def test_judge_prompt_contains_rubric_constraints() -> None:
    system, user = build_judge_prompt(_spec(), _itinerary(), _retrieval())
    joined = f"{system}\n{user}".casefold()

    assert "use only supplied evidence" in joined
    assert "do not reward prose style" in joined
    assert "do not infer unstated attraction facts" in joined
    assert "groundedness is 5 only if all pois and areas are supplied" in joined
    assert "geographic coherence concerns area clustering" in joined
    assert "pacing concerns item count, durations and trip pace" in joined
    assert "budget respect concerns style/budget consistency" in joined
