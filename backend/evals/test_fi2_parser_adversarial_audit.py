"""Adversarial audit reproductions for FI2 numeric/date parsing.

REVIEW ARTIFACT — NOT MERGE-READY, NOT GATE-PASSING.

This file is an auditor's executable evidence, written on branch
``codex/fi2-parser-adversarial-audit`` from base commit
``c925d98077dd94a1f24d7c312243bfcee78f2d3c``. It changes **no** production
code. Luna owns the production parser fixes in ``backend/ingestion/parsing.py``.

How to read this file
---------------------
Tests are split into two classes:

* ``TestActualBehaviour`` — assertions that **pass today** and pin the exact,
  observed, confidently-wrong / crashing behaviour of the current parser.
  These are the reproductions; they document reality without weakening it.

* ``TestSupportedBehaviour`` — assertions that express the behaviour the FI2
  contract *promises* ("Unsupported or ambiguous notation fails closed";
  "dates must use ISO YYYY-MM-DD notation"; the parser raises
  ``UnresolvedValueError`` for anything it will not parse). Several of these
  **fail on the base commit** — that failure is the finding. They are NOT
  xfail-marked: hiding the defect is explicitly out of scope. Run with
  ``-k SupportedBehaviour`` to see the red that a fix must turn green.

Grounding for "supported/correct" expectations (no invented financial rules):
* ``reports/fi2_extraction_validation.md`` → "Unsupported or ambiguous notation
  fails closed"; "remain unresolved rather than guessed".
* ``backend/evals/test_fi2_extraction.py::
  test_deterministic_parsers_reject_ambiguous_values`` → ambiguous notation
  must raise ``UnresolvedValueError``.
* ``backend/ingestion/parsing.py`` docstring/class ``UnresolvedValueError`` →
  "The source notation is unsupported or ambiguous."
* ``backend/ingestion/validation.py`` only catches ``UnresolvedValueError``
  around ``parse_field_value`` → any other exception is an uncaught contract
  break.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from core.models import Card
from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import SnapshotBundle
from ingestion.parsing import (
    UnresolvedValueError,
    parse_date_value,
    parse_field_value,
    parse_money_minor,
    parse_rate_micro,
)
from ingestion.validation import ProposalValidationError, validate_extraction

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# End-to-end helper: run one changed field through full proposal validation
# with synthetic, internally-consistent evidence (exact quote + matching hash).
# ---------------------------------------------------------------------------
def _card_row() -> dict[str, Any]:
    return Card.model_validate(
        {
            "id": "hdfc-infinia",
            "issuer": "HDFC Bank",
            "network": "visa",
            "country": "IN",
            "name": "Infinia",
            "annual_fee_minor": 1_000_000,
            "fee_currency": "INR",
            "forex_markup_bp": 200,
            "forex_markup_tax_bp": 1800,
            "base_earn": {"points": 3, "per_amount_minor": 15000, "currency": "INR"},
            "provenance": {
                "source_type": "crawl_draft",
                "last_verified": "2026-10-01",
                "verified_by": "UNVERIFIED",
                "needs_verification": True,
                "confidence": 0.5,
            },
        }
    ).model_dump(mode="json")


def _validate_annual_fee(raw_value: Any, proposed_minor: int, quote: str) -> Any:
    """Push one ``annual_fee_minor`` change through ``validate_extraction``."""
    root = Path(tempfile.mkdtemp())
    artifacts = ContentAddressedStore(root / "artifacts")
    raw = artifacts.put(f"<p>{quote}</p>".encode(), media_type="text/html")
    normalized = artifacts.put(quote.encode(), media_type="text/plain")
    snapshot = SnapshotBundle(
        snapshot_id="snapshot:watch:hdfc:1",
        target_id="watch:hdfc",
        captured_at=NOW,
        raw_artifact=raw,
        normalized_artifact=normalized,
        raw_sha256=raw.sha256,
        normalized_sha256=normalized.sha256,
        canonical_markdown=quote,
    )
    current = _card_row()
    proposed = _card_row()
    proposed["annual_fee_minor"] = proposed_minor
    response = {
        "target_table": "cards",
        "target_id": "hdfc-infinia",
        "proposed_row": proposed,
        "fields": [
            {
                "field_path": "annual_fee_minor",
                "proposed_raw_value": raw_value,
                "evidence_spans": [
                    {
                        "snapshot_id": snapshot.snapshot_id,
                        "snapshot_hash": snapshot.normalized_sha256,
                        "quote": quote,
                        "normalized_start": 0,
                        "normalized_end": len(quote),
                        "field_path": "annual_fee_minor",
                        "verification": "exact",
                    }
                ],
            }
        ],
        "change_summary": "Issuer page changed the annual fee.",
        "extractor_confidence": 0.8,
    }
    return validate_extraction(
        response=response,
        target_table="cards",
        target_id="hdfc-infinia",
        current_row=current,
        current_row_hash=None,
        snapshot=snapshot,
        artifacts=artifacts,
        now=NOW,
        extractor_version="fi2-extractor-v1",
    )


# ===========================================================================
# TestActualBehaviour — passes today; pins the observed defects.
# ===========================================================================
class TestActualBehaviour:
    # --- Finding 1: malformed comma/space grouping silently accepted --------
    @pytest.mark.parametrize(
        ("raw", "wrong_minor"),
        [
            ("INR 1,2", 1200),  # known repro from the task brief
            ("INR 1 2", 1200),  # known repro from the task brief
            ("12,34", 123400),  # 2-digit group, not a thousands group
            ("1,,234", 123400),  # double comma
            ("1,2,3,4", 123400),  # nonsense grouping
            ("100,00", 1000000),  # trailing 2-digit group
            ("1 00 000", 10000000),  # space-grouped nonsense
        ],
    )
    def test_malformed_grouping_is_silently_accepted(self, raw: str, wrong_minor: int) -> None:
        # Helper-only reproduction: separators are stripped with zero grouping
        # validation, so the parser returns a confidently-wrong number.
        assert parse_money_minor(raw) == wrong_minor

    def test_malformed_grouping_reaches_a_pending_proposal_end_to_end(self) -> None:
        # Proposal-path reproduction: the deterministic validator — the layer
        # meant to ignore the extractor's claimed value and re-parse — instead
        # ENDORSES the wrong 1200 and emits a clean pending proposal with no
        # findings. (It remains a VERIFY_REQUIRED draft; this is not a KB write.)
        proposal = _validate_annual_fee("INR 1,2", 1200, "Annual fee is INR 1,2.")
        assert proposal.proposed_row["annual_fee_minor"] == 1200
        assert proposal.status.value == "pending"
        assert proposal.validation_findings == ()

    # --- Finding 2: oversized numeric string raises an UNCAUGHT exception ---
    def test_long_money_digit_string_raises_uncaught_invalid_operation(self) -> None:
        # ~27+ significant digits overflow Decimal's prec=28 context during the
        # `value * 100` scale step. The contract only ever promises
        # UnresolvedValueError; this is a raw decimal.InvalidOperation.
        from decimal import InvalidOperation

        with pytest.raises(InvalidOperation):
            parse_money_minor("1" * 27)

    def test_long_rate_digit_string_raises_uncaught_invalid_operation(self) -> None:
        from decimal import InvalidOperation

        with pytest.raises(InvalidOperation):
            parse_rate_micro("1" * 23)  # x1_000_000 overflows sooner

    def test_long_digits_crash_escapes_validate_extraction(self) -> None:
        # Proposal-path reproduction: validate_extraction catches only
        # UnresolvedValueError around parse_field_value, so the raw
        # InvalidOperation escapes the validator (and FinancialExtractor.extract,
        # which likewise catches only ProposalValidationError).
        from decimal import InvalidOperation

        with pytest.raises(InvalidOperation):
            _validate_annual_fee("1" * 27, 100, "Fee is " + "1" * 27 + " minor.")

    # --- Finding 3: non-ISO date notation silently accepted -----------------
    @pytest.mark.parametrize(
        ("raw", "wrong_date"),
        [
            ("20261026", date(2026, 10, 26)),  # basic format, no separators
            ("2026-W01-1", date(2025, 12, 29)),  # ISO week-date
            ("2026W011", date(2025, 12, 29)),  # compact ISO week-date
        ],
    )
    def test_non_iso_date_notation_is_silently_accepted(
        self, raw: str, wrong_date: date
    ) -> None:
        # date.fromisoformat (Py 3.11+) accepts far more than YYYY-MM-DD, so a
        # value the contract/error message say is unsupported parses anyway.
        assert parse_date_value(raw) == wrong_date
        assert parse_field_value("valid_to", raw, expected=None) == wrong_date


# ===========================================================================
# TestSupportedBehaviour — expresses the FI2-contracted behaviour.
# Several of these FAIL on base commit c925d98; the failure IS the finding.
# NOT xfail-marked by design (see module docstring).
# ===========================================================================
class TestSupportedBehaviour:
    @pytest.mark.parametrize("raw", ["INR 1,2", "INR 1 2", "12,34", "1,,234", "100,00"])
    def test_malformed_grouping_should_fail_closed(self, raw: str) -> None:
        with pytest.raises(UnresolvedValueError):
            parse_money_minor(raw)

    def test_oversized_number_should_fail_closed_not_crash(self) -> None:
        with pytest.raises(UnresolvedValueError):
            parse_money_minor("1" * 27)

    @pytest.mark.parametrize("raw", ["20261026", "2026-W01-1", "2026W011"])
    def test_non_iso_dates_should_fail_closed(self, raw: str) -> None:
        with pytest.raises(UnresolvedValueError):
            parse_date_value(raw)

    def test_malformed_grouping_should_be_rejected_end_to_end(self) -> None:
        # A malformed, un-parseable source amount must never become a pending
        # proposal carrying a confidently-wrong number.
        with pytest.raises(ProposalValidationError):
            _validate_annual_fee("INR 1,2", 1200, "Annual fee is INR 1,2.")
