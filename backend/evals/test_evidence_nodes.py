import pytest
from pydantic import ValidationError

from gateway.evidence.edges import EvidenceGraph
from gateway.evidence.freshness import supersede
from gateway.evidence.nodes import (
    Artifact, Claim, ClaimKind, Evaluation, FreshnessState, LifecycleState, Run, Source
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
            lifecycle=LifecycleState.ACTIVE,
            confidence=0.9, needs_verification=False,
        )


def test_claim_accepts_inference_without_source() -> None:
    claim = Claim(
        claim_id="c2", run_id="r1", adapter_id="derived",
        kind=ClaimKind.REFERENCE_FACT,
        payload={"note": "per-diem assumption"},
        source_id=None, is_inference=True,
        status=FreshnessState.ESTIMATED,
        lifecycle=LifecycleState.ACTIVE,
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
                   verdict="accept", reasons=[], run_id="r1")

def test_superseding_a_verify_required_claim_preserves_the_safety_signal(
    claim_a, source_a
):
    """verify_required must survive supersession — it is a Tier-F safety signal."""
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a.model_copy(update={
        "status": FreshnessState.VERIFY_REQUIRED
    }))
    replacement = claim_a.model_copy(update={"claim_id": "c-a2"})
    supersede(g, old_id="c-a", new_claim=replacement)

    assert g.claims["c-a"].lifecycle is LifecycleState.SUPERSEDED
    assert g.claims["c-a"].status is FreshnessState.VERIFY_REQUIRED   # preserved


def test_freshness_states_match_spec_16_exactly():
    assert {s.value for s in FreshnessState} == {
        "live", "cached", "estimated", "stale", "verify_required"
    }


# --- I0 Task 1: typed temporal/run ownership ------------------------------ #


def test_source_requires_timezone_aware_retrieved_at() -> None:
    with pytest.raises(ValidationError):
        Source(
            source_id="s-x", run_id="r1", provider="p", adapter_id="p",
            retrieved_at="2026-10-12T10:00:00",  # naive — no offset
            source_url="https://example.test/x", terms_ref=None,
        )


def test_run_rejects_ended_at_before_started_at() -> None:
    with pytest.raises(ValidationError):
        Run(
            run_id="r1",
            started_at="2026-10-12T10:00:00Z",
            ended_at="2026-10-12T09:00:00Z",
        )


def test_run_accepts_ended_at_after_started_at() -> None:
    run = Run(
        run_id="r1",
        started_at="2026-10-12T10:00:00Z",
        ended_at="2026-10-12T10:05:00Z",
    )
    assert run.ended_at is not None


def test_claim_expires_at_must_be_timezone_aware() -> None:
    # model_copy() never re-validates in Pydantic v2, so this must construct
    # a fresh Claim to actually exercise the AwareDatetime field type.
    with pytest.raises(ValidationError):
        Claim(
            claim_id="c-naive", run_id="r1", adapter_id="adapter-a",
            kind=ClaimKind.CASH_QUOTE,
            payload={"total_minor": 1000, "currency": "INR"},
            source_id=None, is_inference=True,
            status=FreshnessState.LIVE, confidence=0.5, needs_verification=True,
            expires_at="2026-10-12T10:20:00",  # naive — no offset
        )
