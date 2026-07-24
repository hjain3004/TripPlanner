from datetime import date

import pytest
from pydantic import ValidationError

from core.models import (
    AwardTarget,
    LoyaltyProgram,
    Provenance,
    RecommendationKind,
    TransferEdge,
)

PROV = Provenance(
    source_type="manual_curation",
    last_verified=date(2026, 7, 24),
    verified_by="UNVERIFIED",
    needs_verification=True,
    confidence=1.0,
)


def test_transfer_edge_rejects_zero_ratio_and_increment() -> None:
    with pytest.raises(ValidationError):
        TransferEdge(
            id="bad",
            from_id="card",
            to_id="program",
            ratio_from=0,
            ratio_to=1,
            min_transfer=0,
            increment=0,
            transfer_time_hours_typical=0,
            transfer_time_hours_max=0,
            provenance=PROV,
        )


def test_award_target_defaults_to_home_currency() -> None:
    target = AwardTarget(
        origin="DEL",
        destination="SIN",
        cabin="business",
        trip_type="round_trip",
        travelers=2,
    )
    assert target.home_currency == "INR"
    assert RecommendationKind.NO_DATA.value == "NO_DATA"
