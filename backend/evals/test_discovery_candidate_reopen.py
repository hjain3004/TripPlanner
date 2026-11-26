from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from ingestion.contracts import DiscoveryCandidate
from ingestion.storage import FinancialIngestionStore


@pytest.mark.parametrize("explicit_null", [False, True])
def test_discovery_without_issuer_url_reopens(tmp_path: Path, explicit_null: bool) -> None:
    values = {
        "id": "issuer-url-unknown",
        "found_at": date(2026, 11, 25),
        "hint_url": "https://example.com/public-disclosure",
        "hint_source": "issuer public disclosure",
        "corridor": "US",
        "kind": "card",
        "issuer_guess": "Example Bank",
        "product_guess": "Travel card",
        "claim_summary": "Product-specific issuer URL has not been established.",
        "status": "pending",
    }
    if explicit_null:
        values["issuer_url_to_verify"] = None
    candidate = DiscoveryCandidate.model_validate(values)
    path = tmp_path / "ingestion.sqlite"
    FinancialIngestionStore(path).put_discovery_candidate(candidate)

    reopened = FinancialIngestionStore(path)
    assert reopened.get_discovery_candidate(candidate.id) == candidate
    assert reopened.list_discovery_candidates() == [candidate]
    assert candidate.issuer_url_to_verify is None


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "https://user:password@example.com/card", "https://example.com/#secret"],
)
def test_optional_issuer_url_still_validates_supplied_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        DiscoveryCandidate(
            id="unsafe-url",
            found_at=date(2026, 11, 25),
            hint_url="https://example.com/disclosure",
            hint_source="issuer",
            corridor="US",
            kind="card",
            issuer_guess="Example Bank",
            product_guess="Travel card",
            claim_summary="Unverified discovery",
            issuer_url_to_verify=url,
            status="pending",
        )
