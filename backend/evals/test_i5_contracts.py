import pytest
from pydantic import ValidationError

from agents.discovery.contracts import DiscoveryCandidate, LoopBudget, SearchIntent


def test_search_intent_carries_no_provider_or_url_fields() -> None:
    """Spec 4: no provider-specific tool names and no arbitrary URLs in model context."""
    banned = {"provider", "provider_id", "adapter", "adapter_id", "url", "source_url", "endpoint"}
    assert not (banned & set(SearchIntent.model_fields))


def test_search_intent_rejects_a_url_smuggled_into_query_text() -> None:
    with pytest.raises(ValidationError):
        SearchIntent(query_text="hawker centre https://evil.invalid/x", round_index=0)


def test_a_remembered_name_starts_unverified() -> None:
    """Spec 4: 'that name is only an unverified DiscoveryCandidate'."""
    d = DiscoveryCandidate(mentioned_name="Some Cafe I Recall")
    assert d.resolved_place_id is None
    assert d.verification_state == "unverified"


def test_budget_defaults_match_the_student_profile() -> None:
    """Spec 4 initial student-profile loop budget."""
    b = LoopBudget()
    assert (b.max_rounds, b.max_calls, b.max_retained_candidates, b.max_per_day) == (3, 6, 40, 12)


def test_budget_cannot_be_constructed_above_the_ceiling() -> None:
    """Tuning down is Tier C. Tuning UP silently is how autonomy leaks."""
    with pytest.raises(ValidationError):
        LoopBudget(max_calls=99)
