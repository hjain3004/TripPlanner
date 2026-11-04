"""stage-capture: curator-authored extraction through the real ingestion pipeline.

Real SQLite, the real ManualUploadBackend, SnapshotService, FinancialExtractor and FI2's own
validator. Only the capture documents are synthetic (host ``example.invalid``); nothing here
says anything about what an issuer's page contains.
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from core.db import SEEDS_DIR
from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import CuratorRecord, PageKind, SourcePolicyRecord, WatchTarget
from ingestion.staging import (
    CuratorExtraction,
    ExtractionRecord,
    StageLimits,
    StageOutcome,
    StageRefusalCode,
    stage_capture,
)
from ingestion.storage import FinancialIngestionStore

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
PAGE = (
    "<html><body><main>"
    "<p>SYNTHETIC FIXTURE (not issuer content).</p>"
    "<p>The annual fee is INR 15,000 per year.</p>"
    "<p>Foreign currency markup is 3.5% on every international transaction.</p>"
    "<p>Earn 5 reward points for every INR 150 spent.</p>"
    "<p>Late payment: 3.5% of the amount due.</p>"
    "<p>Previously the markup was 2% for premium accounts.</p>"
    "</main></body></html>"
)
FEE_QUOTE = "The annual fee is INR 15,000 per year."
FX_QUOTE = "Foreign currency markup is 3.5% on every international transaction."


class Env:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = FinancialIngestionStore(root / "ingestion.sqlite", now=lambda: NOW)
        self.artifacts = ContentAddressedStore(root / "artifacts")
        self.store.put_curator(
            CuratorRecord(curator_id="alice", display_name="Alice", created_at=NOW)
        )
        self.capture = root / "capture.html"
        self.capture.write_text(PAGE, encoding="utf-8")
        self.seeds = SEEDS_DIR

    def policy(self, **over: Any) -> SourcePolicyRecord:
        base: dict[str, Any] = {
            "policy_id": "synth-issuer",
            "name": "SYNTHETIC",
            "owner": "fixture",
            "domain": "example.invalid",
            "source_url": "https://www.example.invalid/card",
            "terms_url": "https://www.example.invalid/terms",
            "terms_read_on": "2026-11-01",
            "automated_access_permitted": False,
            "manual_only": True,
            "allowed_page_classes": ("card_page", "tnc_pdf"),
            "reviewed_on": "2026-11-01",
            "reviewed_by": "alice",
        }
        return SourcePolicyRecord.model_validate({**base, **over})

    def target(self, **over: Any) -> WatchTarget:
        base: dict[str, Any] = {
            "target_id": "synth-card",
            "canonical_url": "https://www.example.invalid/card",
            "source_policy_id": "synth-issuer",
            "target_fact_ids": ("hdfc-infinia",),
            "page_kind": PageKind.MANUAL_CAPTURE,
            "check_frequency_days": 365,
            "preferred_backend": "manual",
            "manual_only": True,
        }
        return WatchTarget.model_validate({**base, **over})

    def stage(
        self,
        records: list[dict[str, Any]],
        *,
        curator: str = "alice",
        document_class: PageKind = PageKind.CARD_PAGE,
        capture: Path | None = None,
        policy: SourcePolicyRecord | None = None,
        target: WatchTarget | None = None,
        seeds: Path | None = None,
        summary: str | None = None,
        now: Callable[[], datetime] = lambda: NOW,
        limits: StageLimits | None = None,
    ) -> StageOutcome:
        extraction = CuratorExtraction.model_validate(
            {
                "schema": "tripwise.curator-extraction/v1",
                "curator_id": curator,
                "change_summary": summary,
                "records": records,
            }
        )
        return stage_capture(
            store=self.store,
            artifacts=self.artifacts,
            seeds_dir=seeds or self.seeds,
            capture_path=capture or self.capture,
            policy=policy or self.policy(),
            target=target or self.target(),
            extraction=extraction,
            document_class=document_class,
            now=now,
            limits=limits,
        )


def fee(**over: Any) -> dict[str, Any]:
    return {
        "table": "cards",
        "id": "hdfc-infinia",
        "field_path": "annual_fee_minor",
        "raw_value": "INR 15,000",
        "quote": FEE_QUOTE,
        **over,
    }


def fx(**over: Any) -> dict[str, Any]:
    return {
        "table": "cards",
        "id": "hdfc-infinia",
        "field_path": "forex_markup_bp",
        "raw_value": "3.5%",
        "quote": FX_QUOTE,
        **over,
    }


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("staging attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    yield


def rows(env: Env) -> dict[str, int]:
    with env.store._connect() as connection:
        return {
            name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for name in (
                "source_policies",
                "watch_targets",
                "fetch_attempts",
                "snapshot_manifests",
                "change_proposals",
                "audit_events",
            )
        }


def refusal_codes(outcome: StageOutcome) -> list[StageRefusalCode]:
    return [r.code for r in outcome.refusals]


# ------------------------------------------------------------------ the working path


def test_a_capture_and_curator_quotes_become_one_validated_proposal(
    env: Env, no_network: None
) -> None:
    outcome = env.stage([fee(), fx()], summary="SYNTHETIC check")
    assert outcome.status == "staged", outcome.refusals
    assert outcome.extraction == "curator-authored"
    assert outcome.llm_calls == 0 and outcome.network_calls == 0
    assert (outcome.policy_state, outcome.target_state, outcome.snapshot_state) == (
        "stored",
        "stored",
        "stored",
    )
    (staged,) = outcome.proposals
    assert staged.target_id == "hdfc-infinia" and staged.review_status == "pending"
    assert staged.field_paths == ("annual_fee_minor", "forex_markup_bp")
    proposal = env.store.get_proposal(staged.proposal_id)
    assert proposal is not None
    # the proposed row carries exactly the deterministic parse, and nothing else changed
    assert proposal.proposed_row["annual_fee_minor"] == 1_500_000
    assert proposal.proposed_row["forex_markup_bp"] == 350
    assert proposal.proposed_row["provenance"]["needs_verification"] is True
    assert proposal.extractor_version == "curator-authored-v1"
    assert "Curator-authored by alice" in proposal.change_summary
    # every span is an exact slice of the stored canonical text, hash-bound to the snapshot
    snapshot = env.store.get_snapshot(outcome.snapshot_id or "")
    assert snapshot is not None
    for field in proposal.field_proposals:
        for span in field.evidence_spans:
            assert snapshot.canonical_markdown[span.normalized_start : span.normalized_end] == (
                span.quote
            )
            assert span.snapshot_hash == snapshot.normalized_sha256
            assert span.verification == "exact" and span.artifact_kind == "html"


def test_the_stored_proposal_is_what_review_sees_with_the_manual_capture_flag(
    env: Env,
) -> None:
    from ingestion.review import ReviewService
    from ingestion.review_rows import SeedRowSource

    outcome = env.stage([fee()])
    service = ReviewService(
        store=env.store, artifacts=env.artifacts, rows=SeedRowSource(env.seeds), now=lambda: NOW
    )
    context = service.context(outcome.proposals[0].proposal_id)
    assert [f.code.value for f in context.computed_findings] == ["manual_capture"]
    assert all(e.verified for e in context.evidence)


def test_staging_writes_nothing_to_the_seeds(env: Env) -> None:
    before = {p.name: p.read_bytes() for p in SEEDS_DIR.glob("*.yaml")}
    env.stage([fee(), fx()])
    assert {p.name: p.read_bytes() for p in SEEDS_DIR.glob("*.yaml")} == before


# ------------------------------------------------------------------ repeat behaviour


def test_staging_the_same_input_twice_changes_nothing(env: Env) -> None:
    first = env.stage([fee(), fx()])
    before = rows(env)
    later = datetime(2026, 11, 9, 9, 30, tzinfo=UTC)
    second = env.stage([fx(), fee()], now=lambda: later)  # record order does not matter
    assert second.status == "staged"
    assert (second.policy_state, second.target_state, second.snapshot_state) == (
        "already_stored",
        "already_stored",
        "already_stored",
    )
    assert second.proposals[0].state == "already_stored"
    assert second.proposals[0].proposal_id == first.proposals[0].proposal_id
    assert rows(env) == before  # no new policy, target, attempt, snapshot, proposal or audit row


def test_a_different_extraction_for_the_same_snapshot_is_a_conflict_not_an_overwrite(
    env: Env,
) -> None:
    first = env.stage([fee(), fx()])
    stored = env.store.get_proposal(first.proposals[0].proposal_id)
    before = rows(env)
    changed = env.stage([fee()])  # fewer fields: a different extraction
    assert changed.status == "refused"
    assert refusal_codes(changed) == [StageRefusalCode.PROPOSAL_CONFLICT]
    assert rows(env) == before
    assert env.store.get_proposal(first.proposals[0].proposal_id) == stored


def test_a_changed_curator_or_summary_is_also_a_distinct_request(env: Env) -> None:
    env.store.put_curator(CuratorRecord(curator_id="bob", display_name="Bob", created_at=NOW))
    env.stage([fee()])
    assert refusal_codes(env.stage([fee()], curator="bob")) == [StageRefusalCode.PROPOSAL_CONFLICT]
    assert refusal_codes(env.stage([fee()], summary="another")) == [
        StageRefusalCode.PROPOSAL_CONFLICT
    ]


def test_a_changed_document_is_a_new_snapshot_that_supersedes_the_old(env: Env) -> None:
    first = env.stage([fee()])
    env.capture.write_text(PAGE.replace("15,000", "16,000"), encoding="utf-8")
    second = env.stage([fee(raw_value="INR 16,000", quote=FEE_QUOTE.replace("15,000", "16,000"))])
    assert second.status == "staged" and second.snapshot_state == "stored"
    assert second.snapshot_id != first.snapshot_id
    snapshot = env.store.get_snapshot(second.snapshot_id or "")
    assert snapshot is not None and snapshot.supersedes_snapshot_id == first.snapshot_id


def test_an_interrupted_run_is_completed_by_running_it_again(env: Env) -> None:
    # A refused run keeps the capture evidence it stored...
    refused = env.stage([fee(quote="The annual fee is INR 99 per year.")])
    assert refused.status == "refused" and refused.proposals == ()
    assert refused.snapshot_state == "stored"
    snapshots = rows(env)["snapshot_manifests"]
    # ...so the corrected file is staged against the same snapshot, with nothing duplicated.
    fixed = env.stage([fee()])
    assert fixed.status == "staged" and fixed.snapshot_state == "already_stored"
    assert fixed.proposals[0].state == "stored"
    assert rows(env)["snapshot_manifests"] == snapshots


# ------------------------------------------------------------------ all-or-nothing


def test_one_bad_record_stores_no_proposal_even_when_other_rows_are_valid(env: Env) -> None:
    good_other_row = {
        "table": "cards",
        "id": "axis-atlas",
        "field_path": "annual_fee_minor",
        "raw_value": "INR 15,000",
        "quote": FEE_QUOTE,
    }
    outcome = env.stage(
        [fee(), good_other_row, fx(raw_value="3,5%")],
        target=env.target(target_fact_ids=("hdfc-infinia", "axis-atlas")),
    )
    assert outcome.status == "refused" and outcome.proposals == ()
    assert refusal_codes(outcome) == [StageRefusalCode.VALUE_UNRESOLVED]
    assert rows(env)["change_proposals"] == 0


def test_every_problem_is_reported_in_one_run(env: Env) -> None:
    outcome = env.stage([fee(quote="The annual fee is INR 16,000 per year."), fx(raw_value="3,5%")])
    assert refusal_codes(outcome) == [
        StageRefusalCode.QUOTE_NOT_FOUND,
        StageRefusalCode.VALUE_UNRESOLVED,
    ]
    assert [r.record_index for r in outcome.refusals] == [0, 1]
    assert [r.field_path for r in outcome.refusals] == ["annual_fee_minor", "forex_markup_bp"]


def test_two_rows_each_become_their_own_proposal(env: Env) -> None:
    axis = {
        "table": "cards",
        "id": "axis-atlas",
        "field_path": "annual_fee_minor",
        "raw_value": "INR 15,000",
        "quote": FEE_QUOTE,
    }
    outcome = env.stage(
        [fee(), axis], target=env.target(target_fact_ids=("hdfc-infinia", "cards:axis-atlas"))
    )
    assert outcome.status == "staged"
    assert {p.target_id for p in outcome.proposals} == {"hdfc-infinia", "axis-atlas"}


# ------------------------------------------------------------------ evidence integrity


def test_a_quote_that_is_not_in_the_document_is_refused_with_a_hint(env: Env) -> None:
    refused = env.stage([fee(quote="The  annual fee is\nINR 15,000 per year.")])
    assert refusal_codes(refused) == [StageRefusalCode.QUOTE_NOT_FOUND]
    assert repr(FEE_QUOTE) in refused.refusals[0].message  # shows the exact stored text


def test_an_ambiguous_quote_is_never_guessed(env: Env) -> None:
    refused = env.stage([fx(raw_value="3.5%", quote="3.5%")])
    assert refusal_codes(refused) == [StageRefusalCode.QUOTE_AMBIGUOUS]
    assert "2 times" in refused.refusals[0].message
    chosen = env.stage([fx(raw_value="3.5%", quote="3.5%", occurrence=1)])
    assert chosen.status == "staged"


def test_the_chosen_occurrence_decides_which_text_is_cited(env: Env) -> None:
    outcome = env.stage([fx(quote="3.5%", occurrence=2)])
    assert outcome.status == "staged"
    proposal = env.store.get_proposal(outcome.proposals[0].proposal_id)
    assert proposal is not None
    span = proposal.field_proposals[0].evidence_spans[0]
    snapshot = env.store.get_snapshot(outcome.snapshot_id or "")
    assert snapshot is not None
    assert (
        "Late payment"
        in snapshot.canonical_markdown[span.normalized_start - 20 : span.normalized_start]
    )


def test_locator_mistakes_are_typed(env: Env) -> None:
    assert refusal_codes(env.stage([fx(quote="3.5%", occurrence=3)])) == [
        StageRefusalCode.OCCURRENCE_OUT_OF_RANGE
    ]
    assert refusal_codes(env.stage([fx(quote="3.5%", occurrence=1, offset=5)])) == [
        StageRefusalCode.LOCATOR_CONFLICT
    ]
    assert refusal_codes(env.stage([fx(quote="3.5%", offset=5)])) == [
        StageRefusalCode.OFFSET_MISMATCH
    ]


def test_an_exact_offset_selects_the_quote(env: Env) -> None:
    from ingestion.canonical import canonicalize_html

    canonical = canonicalize_html(PAGE.encode(), max_chars=10_000)
    at = canonical.index("3.5%")  # offsets are into the stored canonical text
    outcome = env.stage([fx(quote="3.5%", offset=at)])
    assert outcome.status == "staged", outcome.refusals
    proposal = env.store.get_proposal(outcome.proposals[0].proposal_id)
    assert proposal is not None
    span = proposal.field_proposals[0].evidence_spans[0]
    assert (span.normalized_start, span.normalized_end) == (at, at + 4)


def test_a_page_belongs_only_to_pdf_evidence(env: Env) -> None:
    assert refusal_codes(env.stage([fee(page=1)])) == [StageRefusalCode.PAGE_NOT_APPLICABLE]


def test_a_value_the_quote_does_not_say_is_refused(env: Env) -> None:
    refused = env.stage([fee(raw_value="INR 9,999")])
    assert refusal_codes(refused) == [StageRefusalCode.VALUE_NOT_SUPPORTED_BY_QUOTE]


@pytest.mark.parametrize("raw", ["INR 1,2", "15000 rupees", "", "INR -5", "1e3"])
def test_malformed_values_are_unresolved_never_guessed(env: Env, raw: str) -> None:
    refused = env.stage([fee(raw_value=raw)])
    assert refusal_codes(refused) == [StageRefusalCode.VALUE_UNRESOLVED]
    assert env.store.list_proposals() == []


def test_a_boolean_is_not_a_source_value(env: Env) -> None:
    with pytest.raises(ValueError):
        ExtractionRecord.model_validate(fee(raw_value=True))


@pytest.mark.parametrize("path", ["provenance.needs_verification", "provenance.verified_by"])
def test_provenance_is_never_extractable(env: Env, path: str) -> None:
    refused = env.stage([fee(field_path=path, raw_value="false")])
    assert refusal_codes(refused) == [StageRefusalCode.PROVENANCE_FIELD_FORBIDDEN]


def test_identity_is_never_extractable_and_unknown_paths_are_refused(env: Env) -> None:
    assert refusal_codes(env.stage([fee(field_path="id", raw_value="x")])) == [
        StageRefusalCode.FIELD_PATH_INVALID
    ]
    assert refusal_codes(env.stage([fee(field_path="nonexistent_bp", raw_value="2%")])) == [
        StageRefusalCode.FIELD_PATH_INVALID
    ]


def test_two_individually_valid_but_different_values_for_one_field_are_refused(
    env: Env,
) -> None:
    earlier = fx(raw_value="2%", quote="the markup was 2% for premium accounts")
    refused = env.stage([fx(), earlier])
    assert refusal_codes(refused) == [StageRefusalCode.DUPLICATE_FIELD_CONFLICT]
    assert refused.proposals == () and rows(env)["change_proposals"] == 0


def test_the_same_value_quoted_twice_is_two_spans_of_one_field(env: Env) -> None:
    outcome = env.stage([fx(quote="3.5%", occurrence=1), fx(quote="3.5%", occurrence=2)])
    assert outcome.status == "staged"
    proposal = env.store.get_proposal(outcome.proposals[0].proposal_id)
    assert proposal is not None and len(proposal.field_proposals[0].evidence_spans) == 2


# ------------------------------------------------------------------ binding and trust


def test_the_curator_must_be_registered(env: Env) -> None:
    refused = env.stage([fee()], curator="mallory")
    assert refusal_codes(refused) == [StageRefusalCode.UNKNOWN_CURATOR]
    assert rows(env)["snapshot_manifests"] == 0  # refused before anything was stored


def test_a_row_the_target_does_not_list_is_refused(env: Env) -> None:
    other = fee(id="axis-atlas")
    refused = env.stage([other])
    assert refusal_codes(refused) == [StageRefusalCode.ROW_NOT_BOUND]
    assert rows(env)["snapshot_manifests"] == 0


def test_a_missing_row_or_table_is_typed(env: Env) -> None:
    assert refusal_codes(env.stage([fee(id="no-such-card")])) == [StageRefusalCode.ROW_NOT_FOUND]
    assert refusal_codes(env.stage([fee(table="loyalty_programs")])) == [
        StageRefusalCode.UNSUPPORTED_TABLE
    ]


def test_an_aggregator_is_refused_as_a_source_even_if_a_policy_names_it(env: Env) -> None:
    policy = env.policy(
        domain="cardexpert.in",
        source_url="https://www.cardexpert.in/card",
        terms_url="https://www.cardexpert.in/terms-of-use/",
    )
    target = env.target(canonical_url="https://www.cardexpert.in/card")
    refused = env.stage([fee()], policy=policy, target=target)
    assert StageRefusalCode.SOURCE_NOT_ALLOWED in refusal_codes(refused)
    assert rows(env)["source_policies"] == 0


def test_a_target_must_be_a_manual_capture_so_review_keeps_the_flag(env: Env) -> None:
    for bad in (
        env.target(page_kind=PageKind.CARD_PAGE),
        env.target(preferred_backend="local"),
        env.target(manual_only=False),
        env.target(status="paused"),
    ):
        assert StageRefusalCode.TARGET_INVALID in refusal_codes(env.stage([fee()], target=bad))


def test_the_target_must_belong_to_the_supplied_policy(env: Env) -> None:
    refused = env.stage([fee()], target=env.target(source_policy_id="other"))
    assert StageRefusalCode.TARGET_INVALID in refusal_codes(refused)


def test_a_url_outside_the_policy_domain_is_refused(env: Env) -> None:
    refused = env.stage([fee()], target=env.target(canonical_url="https://www.elsewhere.test/c"))
    assert StageRefusalCode.SOURCE_NOT_ALLOWED in refusal_codes(refused)


def test_the_document_class_must_be_allowed_and_match_the_capture(env: Env) -> None:
    only_card = env.policy(allowed_page_classes=("card_page",))
    assert refusal_codes(env.stage([fee()], document_class=PageKind.TNC_PDF, policy=only_card)) == [
        StageRefusalCode.DOCUMENT_CLASS_NOT_ALLOWED
    ]
    # an HTML capture cannot be declared a PDF
    assert refusal_codes(env.stage([fee()], document_class=PageKind.TNC_PDF)) == [
        StageRefusalCode.DOCUMENT_CLASS_MISMATCH
    ]


def test_stored_records_are_immutable_so_a_different_policy_or_target_conflicts(
    env: Env,
) -> None:
    env.stage([fee()])
    changed_policy = env.policy(name="renamed")
    assert StageRefusalCode.POLICY_CONFLICT in refusal_codes(
        env.stage([fee()], policy=changed_policy)
    )
    changed_target = env.target(check_frequency_days=30)
    assert StageRefusalCode.TARGET_CONFLICT in refusal_codes(
        env.stage([fee()], target=changed_target)
    )


def test_an_oversized_or_unreadable_capture_is_a_typed_refusal(env: Env, tmp_path: Path) -> None:
    missing = env.stage([fee()], capture=tmp_path / "nope.html")
    assert refusal_codes(missing) == [StageRefusalCode.CAPTURE_REJECTED]
    binary = tmp_path / "capture.bin"
    binary.write_bytes(b"\x00\x01")
    assert refusal_codes(env.stage([fee()], capture=binary)) == [StageRefusalCode.CAPTURE_REJECTED]


def test_an_edited_base_row_changes_the_request_so_the_old_proposal_conflicts(
    env: Env, tmp_path: Path
) -> None:
    import shutil

    seeds = tmp_path / "seeds"
    shutil.copytree(SEEDS_DIR, seeds)
    env.stage([fee()], seeds=seeds)
    cards = seeds / "cards.yaml"
    cards.write_text(cards.read_text().replace("forex_markup_bp: 200", "forex_markup_bp: 210", 1))
    refused = env.stage([fee()], seeds=seeds)
    assert refusal_codes(refused) == [StageRefusalCode.PROPOSAL_CONFLICT]


# ------------------------------------------------------------------ review findings


@pytest.mark.parametrize("raw", ["5", "15", "INR 1", "000", "0", "1,5"])
def test_a_fragment_of_the_quoted_number_is_not_support_for_a_different_amount(
    env: Env, raw: str
) -> None:
    """A bare substring test let "5", "15" or "000" be 'supported' by "INR 15,000" while
    parsing to INR 5, 15 or 0: a zero annual fee passed validation. Whole tokens only."""
    refused = env.stage([fee(raw_value=raw)])
    assert refused.status == "refused" and refused.proposals == ()
    assert refusal_codes(refused) in (
        [StageRefusalCode.VALUE_NOT_SUPPORTED_BY_QUOTE],
        [StageRefusalCode.VALUE_UNRESOLVED],
    )


@pytest.mark.parametrize(
    ("raw", "quote", "supported"),
    [
        ("15,000", "The annual fee is INR 15,000 per year.", True),
        ("INR 15,000", "The annual fee is INR 15,000 per year.", True),
        ("15,000", "Annual fee Rs.15,000 plus GST.", True),  # "Rs." before the number
        ("15,000", "Annual fee \u20b915,000.", True),
        ("12,500", "The fee is INR 12,500.", True),  # sentence-final full stop
        ("3.5%", "markup is 3.5% on every transaction", True),
        ("15", "fee is INR 0.15 only", False),  # inside a decimal
        ("15,000", "fee is INR 1,15,000", False),  # inside a longer grouped number
        ("5%", "markup is 3.5% on every transaction", False),
        ("2%", "markup is 12% on every transaction", False),
    ],
)
def test_the_quote_supports_a_value_only_as_a_whole_token(
    raw: str, quote: str, supported: bool
) -> None:
    from ingestion.parsing import parse_field_value
    from ingestion.validation import _quote_supports_value

    path = "forex_markup_bp" if "%" in raw else "annual_fee_minor"
    parsed = parse_field_value(path, raw, expected=1)
    assert (
        _quote_supports_value(
            field_path=path, raw_value=raw, parsed_value=parsed, expected=1, quote=quote
        )
        is supported
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://www.bankbazaar.com./cards",  # fully-qualified trailing dot
        "https://WWW.BANKBAZAAR.COM/cards",
        "https://www.bankbazaar.com../cards",
    ],
)
def test_the_aggregator_guard_is_not_defeated_by_how_a_host_is_spelled(env: Env, url: str) -> None:
    policy = env.policy(domain="bankbazaar.com", source_url="https://www.bankbazaar.com/c")
    refused = env.stage([fee()], policy=policy, target=env.target(canonical_url=url))
    assert StageRefusalCode.SOURCE_NOT_ALLOWED in refusal_codes(refused)
    assert rows(env)["source_policies"] == 0


def test_the_same_evidence_given_in_a_different_order_is_the_same_request(env: Env) -> None:
    first = env.stage([fx(quote="3.5%", occurrence=1), fx(quote="3.5%", occurrence=2)])
    assert first.status == "staged"
    before = rows(env)
    reordered = env.stage([fx(quote="3.5%", occurrence=2), fx(quote="3.5%", occurrence=1)])
    assert reordered.status == "staged", reordered.refusals
    assert reordered.proposals[0].state == "already_stored"
    assert rows(env) == before


def test_a_refusal_that_depends_only_on_the_capture_stores_no_policy_or_target(
    env: Env,
) -> None:
    """The operator must be able to correct a source description after such a refusal."""
    mismatch = env.stage([fee()], document_class=PageKind.TNC_PDF)
    assert refusal_codes(mismatch) == [StageRefusalCode.DOCUMENT_CLASS_MISMATCH]
    too_big = env.stage([fee()], limits=StageLimits(max_bytes=10))
    assert refusal_codes(too_big) == [StageRefusalCode.CAPTURE_REJECTED]
    assert (rows(env)["source_policies"], rows(env)["watch_targets"]) == (0, 0)
    corrected = env.policy(name="corrected description")
    assert env.stage([fee()], policy=corrected).status == "staged"
