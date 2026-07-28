import pytest
from pydantic import ValidationError

from gateway.evidence.nodes import (
    Artifact, Claim, ClaimKind, Evaluation, FreshnessState,
)


def test_claim_requires_source_or_inference_flag() -> None:
    """A claim with neither a source nor is_inference is a malformed node."""
    with pytest.raises(ValidationError):
        Claim(
            claim_id="c1", run_id="r1", adapter_id="sample",
            kind=ClaimKind.CASH_QUOTE,
            payload={"total_minor": 2450000, "currency": "INR"},
            source_id=None, is_inference=False,
            status=FreshnessState.LIVE,
            confidence=0.9, needs_verification=False,
        )


def test_claim_accepts_inference_without_source() -> None:
    claim = Claim(
        claim_id="c2", run_id="r1", adapter_id="derived",
        kind=ClaimKind.REFERENCE_FACT,
        payload={"note": "per-diem assumption"},
        source_id=None, is_inference=True,
        status=FreshnessState.ESTIMATED,
        confidence=0.5, needs_verification=True,
    )
    assert claim.is_inference is True
    assert claim.source_id is None


def test_artifact_requires_run_and_version() -> None:
    with pytest.raises(ValidationError):
        Artifact(artifact_id="a1", kind="CostedTrip", run_id="", version=1,
                 derived_from=["c1"])


def test_evaluation_requires_rubric() -> None:
    with pytest.raises(ValidationError):
        Evaluation(evaluation_id="e1", subject_id="c1", rubric_id="",
                   verdict="accept", reasons=[])
