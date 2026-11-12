"""Unit and regression tests for change-feed contracts, identity, diff blocks, and validation.

Verifies:
- AST boundary: backend/feed/ must never import from ingestion, api, accounts, or core.
- Contextual changed blocks with absolute offsets, deletion-only handling, and boundary enforcement.
- Stable semantic identity: identical content produces the exact same event_id regardless of
  subject permutation or display names.
- Different material terms produce distinct event_ids.
- Subject resolution with explicit unmapped state;
  unmapped subjects cannot produce personal impacts.
- Deterministic event validation: mandatory evidence coverage, quote matching, artifact integrity.
- Required invalid evidence is refused with typed reasons.
- Supersession versus conflict classification.
- PageKind and candidate promotion with manual-safe defaults.
"""

from __future__ import annotations

import ast
import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from feed.contracts import (
    BlockLimits,
    ChangeEvent,
    EarnRateChangeTerms,
    EffectiveWindow,
    FieldSpan,
    SubjectRef,
    TransferBonusTerms,
    WelcomeOfferTerms,
)
from ingestion.contracts import DiscoveryCandidate, FetchRequest, PageKind
from ingestion.diff import changed_blocks, diff_text
from ingestion.events import (
    EventRefusal,
    ExtractedEvent,
    KBSubjectResolver,
    SnapshotEvidenceResolver,
    ValidatedEvent,
    classify_event_relationship,
    compute_event_id,
    validate_event,
)
from ingestion.policy import CuratorPromotion, promote_candidate_to_watch_target

# --- 1. AST Boundary Tests ---


def test_feed_package_boundary_imports_nothing_from_forbidden_packages() -> None:
    feed_dir = Path(__file__).resolve().parent.parent / "feed"
    assert feed_dir.is_dir(), f"feed directory {feed_dir} must exist"

    forbidden_roots = {"ingestion", "api", "accounts", "core"}

    for py_file in feed_dir.glob("**/*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_pkg = alias.name.split(".")[0]
                    assert root_pkg not in forbidden_roots, (
                        f"Forbidden import '{alias.name}' found in {py_file}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_pkg = node.module.split(".")[0]
                    assert root_pkg not in forbidden_roots, (
                        f"Forbidden from-import '{node.module}' found in {py_file}"
                    )


# --- 2. Changed Blocks Tests ---


def test_changed_blocks_baseline_on_none_before() -> None:
    outcome = changed_blocks(None, "Line 1\nLine 2\n")
    assert outcome.status == "baseline"
    assert outcome.blocks == ()
    assert outcome.total_blocks == 0


def test_changed_blocks_unchanged_on_identical_text() -> None:
    text = "Line 1\nLine 2\n"
    outcome = changed_blocks(text, text)
    assert outcome.status == "unchanged"
    assert outcome.blocks == ()
    assert outcome.total_blocks == 0


def test_changed_blocks_addition_with_context_and_char_offsets() -> None:
    before = "Header\nIntro\nItem A\nItem B\nFooter\n"
    after = "Header\nIntro\nItem A\nItem A-Plus\nItem B\nFooter\n"

    outcome = changed_blocks(before, after)
    assert outcome.status == "ok"
    assert outcome.total_blocks == 1

    block = outcome.blocks[0]
    assert block.change_kind == "addition"
    assert "Item A-Plus" in block.after_content
    assert block.after_char_range is not None

    start, end = block.after_char_range
    assert after[start:end] == block.after_content


def test_changed_blocks_deletion_only_preserved() -> None:
    before = "Header\nIntro\nDeprecated Term\nItem B\nFooter\n"
    after = "Header\nIntro\nItem B\nFooter\n"

    outcome = changed_blocks(before, after)
    assert outcome.status == "ok"
    assert outcome.total_blocks == 1

    block = outcome.blocks[0]
    assert block.change_kind == "deletion"
    assert "Deprecated Term" in block.before_content
    assert "Deprecated Term" not in block.after_content


def test_changed_blocks_context_merging() -> None:
    # Two edits separated by 1 line (within 2 context lines) must merge into 1 block
    before = "Line 1\nEdit A Old\nBetween\nEdit B Old\nLine 5\n"
    after = "Line 1\nEdit A New\nBetween\nEdit B New\nLine 5\n"

    outcome = changed_blocks(before, after, limits=BlockLimits(context_lines=2))
    assert outcome.status == "ok"
    assert outcome.total_blocks == 1  # merged!


def test_changed_blocks_limits_enforced() -> None:
    # 1. Text oversize
    limits = BlockLimits(max_text_chars=50)
    outcome = changed_blocks("A" * 60, "B" * 60, limits=limits)
    assert outcome.status == "oversize"

    # 2. Block count exceeds limit -> needs_review
    before_lines = [f"Line {i}\n" for i in range(200)]
    after_lines = list(before_lines)
    for i in range(10, 190, 10):
        after_lines[i] = f"Modified {i}\n"

    tight_limits = BlockLimits(max_blocks=5, context_lines=1)
    outcome = changed_blocks("".join(before_lines), "".join(after_lines), limits=tight_limits)
    assert outcome.status == "needs_review"
    assert outcome.total_blocks > 5


def test_existing_diff_text_caller_compatibility() -> None:
    diff = diff_text("old text\n", "new text\n")
    assert diff.changed is True
    assert diff.before_sha256 is not None
    assert diff.after_sha256 is not None
    assert "-old text" in diff.unified_diff
    assert "+new text" in diff.unified_diff


# --- 3. Deterministic Semantic Identity Tests ---


def test_event_id_stable_under_subject_permutation() -> None:
    sub1 = SubjectRef(kind="card", source_name="Axis Atlas", kb_id="axis-atlas")
    sub2 = SubjectRef(kind="loyalty_program", source_name="ITC Culinaire", kb_id="itc-culinaire")
    window = EffectiveWindow(start_date=date(2026, 11, 1), end_date=date(2026, 11, 30))
    terms = TransferBonusTerms(
        from_program=SubjectRef(kind="loyalty_program", source_name="Axis Edge", kb_id="axis-edge"),
        to_program=sub2,
        bonus_bp=2500,
        quoted_dates="Nov 1 to Nov 30, 2026",
    )

    id1 = compute_event_id(1, "transfer_bonus", [sub1, sub2], window, terms)
    id2 = compute_event_id(1, "transfer_bonus", [sub2, sub1], window, terms)
    assert id1 == id2, "event_id must be invariant to subject list permutation"


def test_event_id_stable_under_display_name_change_when_kb_id_resolved() -> None:
    sub_a = SubjectRef(kind="card", source_name="Axis Bank ATLAS Credit Card", kb_id="axis-atlas")
    sub_b = SubjectRef(kind="card", source_name="Atlas Card by Axis", kb_id="axis-atlas")
    window = EffectiveWindow(start_date=date(2026, 11, 1))
    terms = EarnRateChangeTerms(
        card=sub_a,
        new_points=5,
        new_per_amount_minor=10000,
        currency="INR",
        effective_start=date(2026, 11, 1),
        spend_scope="Travel Bookings",
    )

    id1 = compute_event_id(1, "earn_rate_change", [sub_a], window, terms)
    id2 = compute_event_id(1, "earn_rate_change", [sub_b], window, terms)
    assert id1 == id2, "event_id must depend on kind/kb_id, not volatile display names"


def test_different_terms_produce_distinct_event_ids() -> None:
    sub = SubjectRef(kind="card", source_name="Atlas", kb_id="axis-atlas")
    window = EffectiveWindow(start_date=date(2026, 11, 1))

    terms_25bp = TransferBonusTerms(
        from_program=SubjectRef(kind="loyalty_program", source_name="P1", kb_id="p1"),
        to_program=SubjectRef(kind="loyalty_program", source_name="P2", kb_id="p2"),
        bonus_bp=2500,
        quoted_dates="Nov 1-30",
    )
    terms_30bp = TransferBonusTerms(
        from_program=SubjectRef(kind="loyalty_program", source_name="P1", kb_id="p1"),
        to_program=SubjectRef(kind="loyalty_program", source_name="P2", kb_id="p2"),
        bonus_bp=3000,
        quoted_dates="Nov 1-30",
    )

    id_25 = compute_event_id(1, "transfer_bonus", [sub], window, terms_25bp)
    id_30 = compute_event_id(1, "transfer_bonus", [sub], window, terms_30bp)
    assert id_25 != id_30, "different bonus rates must produce distinct event_ids"


# --- 4. Subject Resolution & Personal Impact Invariant ---


def test_subject_resolution_and_unmapped_state() -> None:
    resolver = KBSubjectResolver(
        card_ids=["axis-atlas", "hdfc-infinia"],
        program_ids=["krisflyer", "intermiles"],
        alias_map={
            ("card", "atlas"): "axis-atlas",
            ("loyalty_program", "singapore krisflyer"): "krisflyer",
        },
    )

    # 1. Exact KB ID
    res1 = resolver.resolve(SubjectRef(kind="card", source_name="Axis", kb_id="axis-atlas"))
    assert res1.kb_id == "axis-atlas"

    # 2. Alias resolution
    res2 = resolver.resolve(SubjectRef(kind="card", source_name="Atlas"))
    assert res2.kb_id == "axis-atlas"

    # 3. Direct normalized name match
    res3 = resolver.resolve(SubjectRef(kind="card", source_name="HDFC Infinia"))
    assert res3.kb_id == "hdfc-infinia"

    # 4. Unknown subject remains unmapped
    res_unknown = resolver.resolve(SubjectRef(kind="card", source_name="Unknown New Card"))
    assert res_unknown.kb_id is None


def test_unmapped_subjects_cannot_produce_personal_impact() -> None:
    snapshot_text = (
        "Get 25% bonus points when transferring to Virgin Atlantic from Nov 1 to Nov 30."
    )
    snapshot_hash = hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest()

    span_bonus = FieldSpan(
        field_path="bonus_bp",
        quote="25%",
        start_offset=4,
        end_offset=7,
    )
    span_dates = FieldSpan(
        field_path="quoted_dates",
        quote="Nov 1 to Nov 30",
        start_offset=63,
        end_offset=78,
    )

    raw_event = ExtractedEvent(
        event_type="transfer_bonus",
        title="Virgin Atlantic 25% Bonus",
        summary="Transfer bonus to Virgin Atlantic",
        source_url="https://example.com/promo",
        subjects=(
            SubjectRef(kind="loyalty_program", source_name="Unknown Bank"),
            SubjectRef(kind="loyalty_program", source_name="Virgin Atlantic"),
        ),
        effective_window=EffectiveWindow(start_date=date(2026, 11, 1), end_date=date(2026, 11, 30)),
        terms=TransferBonusTerms(
            from_program=SubjectRef(kind="loyalty_program", source_name="Unknown Bank"),
            to_program=SubjectRef(kind="loyalty_program", source_name="Virgin Atlantic"),
            bonus_bp=2500,
            quoted_dates="Nov 1 to Nov 30",
        ),
        evidence_spans=(span_bonus, span_dates),
        source_policy_id="test-policy",
        source_policy_hash="hash-1",
        target_id="target-1",
        snapshot_id="snap-1",
        artifact_sha256="art-1",
        raw_sha256="raw-1",
        normalized_sha256=snapshot_hash,
        fetch_attempt_id="fetch-1",
        observed_at=datetime.now(UTC),
        fidelity="original_issuer_bytes",
        snapshot_text=snapshot_text,
    )

    # Empty resolver -> unmapped subjects
    resolver = KBSubjectResolver()
    evidence_verifier = SnapshotEvidenceResolver()

    outcome = validate_event(raw_event, evidence=evidence_verifier, subjects=resolver)
    assert isinstance(outcome, ValidatedEvent)
    assert outcome.event.event_id is not None
    assert len(outcome.unmapped_subjects) > 0
    # Core requirement: unmapped subjects cannot produce a personal financial impact
    assert outcome.is_personal_impact_eligible is False


# --- 5. Deterministic Validation and Refusals ---


def test_validation_succeeds_with_exact_evidence_and_mapped_subjects() -> None:
    snapshot_text = "Earn 5 EDGE Miles per 100 spent on Dining from Dec 1, 2026."
    snapshot_hash = hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest()

    span_points = FieldSpan(
        field_path="new_points",
        quote="5 EDGE Miles",
        start_offset=5,
        end_offset=17,
    )
    span_scope = FieldSpan(
        field_path="spend_scope",
        quote="Dining",
        start_offset=35,
        end_offset=41,
    )

    card_ref = SubjectRef(kind="card", source_name="Axis Atlas", kb_id="axis-atlas")

    raw_event = ExtractedEvent(
        event_type="earn_rate_change",
        title="Axis Atlas Dining Earn Rate Update",
        summary="5 EDGE Miles per 100 on dining",
        source_url="https://www.axis.bank.in/cards/atlas",
        subjects=(card_ref,),
        effective_window=EffectiveWindow(start_date=date(2026, 12, 1)),
        terms=EarnRateChangeTerms(
            card=card_ref,
            new_points=5,
            new_per_amount_minor=10000,
            currency="INR",
            effective_start=date(2026, 12, 1),
            spend_scope="Dining",
        ),
        evidence_spans=(span_points, span_scope),
        source_policy_id="axis-policy-v1",
        source_policy_hash="pol-hash",
        target_id="axis-atlas-target",
        snapshot_id="snap-axis-1",
        artifact_sha256="art-sha",
        raw_sha256="raw-sha",
        normalized_sha256=snapshot_hash,
        fetch_attempt_id="fetch-axis-1",
        observed_at=datetime.now(UTC),
        fidelity="original_issuer_bytes",
        snapshot_text=snapshot_text,
    )

    resolver = KBSubjectResolver(card_ids=["axis-atlas"])
    verifier = SnapshotEvidenceResolver()

    outcome = validate_event(raw_event, evidence=verifier, subjects=resolver)
    assert isinstance(outcome, ValidatedEvent)
    assert outcome.is_personal_impact_eligible is True
    assert outcome.facts_status == "valid_proposal"
    assert len(outcome.evidence_receipts) == 1
    assert outcome.evidence_receipts[0].receipt_id.startswith("rcpt:")


def test_validation_refuses_invalid_evidence_quote() -> None:
    snapshot_text = "Earn 5 EDGE Miles per 100 spent on Dining."
    snapshot_hash = hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest()

    # Wrong quote at given offsets
    span_points = FieldSpan(
        field_path="new_points",
        quote="10 EDGE Miles",  # text actually says 5 EDGE Miles
        start_offset=5,
        end_offset=17,
    )
    span_scope = FieldSpan(
        field_path="spend_scope",
        quote="Dining",
        start_offset=35,
        end_offset=41,
    )

    card_ref = SubjectRef(kind="card", source_name="Axis Atlas", kb_id="axis-atlas")

    raw_event = ExtractedEvent(
        event_type="earn_rate_change",
        title="Axis Atlas Dining Earn Rate Update",
        summary="10 EDGE Miles per 100 on dining",
        source_url="https://www.axis.bank.in/cards/atlas",
        subjects=(card_ref,),
        effective_window=EffectiveWindow(start_date=date(2026, 12, 1)),
        terms=EarnRateChangeTerms(
            card=card_ref,
            new_points=10,
            new_per_amount_minor=10000,
            currency="INR",
            effective_start=date(2026, 12, 1),
            spend_scope="Dining",
        ),
        evidence_spans=(span_points, span_scope),
        source_policy_id="axis-policy-v1",
        source_policy_hash="pol-hash",
        target_id="axis-atlas-target",
        snapshot_id="snap-axis-1",
        artifact_sha256="art-sha",
        raw_sha256="raw-sha",
        normalized_sha256=snapshot_hash,
        fetch_attempt_id="fetch-axis-1",
        observed_at=datetime.now(UTC),
        fidelity="original_issuer_bytes",
        snapshot_text=snapshot_text,
    )

    resolver = KBSubjectResolver(card_ids=["axis-atlas"])
    verifier = SnapshotEvidenceResolver()

    outcome = validate_event(raw_event, evidence=verifier, subjects=resolver)
    assert isinstance(outcome, EventRefusal)
    assert outcome.reason == "invalid_evidence_quote"
    assert outcome.field_path == "new_points"


def test_validation_refuses_missing_mandatory_evidence() -> None:
    snapshot_text = "Earn 5 EDGE Miles per 100 spent on Dining."
    snapshot_hash = hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest()

    # Omit span for new_points
    span_scope = FieldSpan(
        field_path="spend_scope",
        quote="Dining",
        start_offset=35,
        end_offset=41,
    )

    card_ref = SubjectRef(kind="card", source_name="Axis Atlas", kb_id="axis-atlas")

    raw_event = ExtractedEvent(
        event_type="earn_rate_change",
        title="Axis Atlas Dining Earn Rate Update",
        summary="5 EDGE Miles per 100 on dining",
        source_url="https://www.axis.bank.in/cards/atlas",
        subjects=(card_ref,),
        effective_window=EffectiveWindow(start_date=date(2026, 12, 1)),
        terms=EarnRateChangeTerms(
            card=card_ref,
            new_points=5,
            new_per_amount_minor=10000,
            currency="INR",
            effective_start=date(2026, 12, 1),
            spend_scope="Dining",
        ),
        evidence_spans=(span_scope,),
        source_policy_id="axis-policy-v1",
        source_policy_hash="pol-hash",
        target_id="axis-atlas-target",
        snapshot_id="snap-axis-1",
        artifact_sha256="art-sha",
        raw_sha256="raw-sha",
        normalized_sha256=snapshot_hash,
        fetch_attempt_id="fetch-axis-1",
        observed_at=datetime.now(UTC),
        fidelity="original_issuer_bytes",
        snapshot_text=snapshot_text,
    )

    resolver = KBSubjectResolver(card_ids=["axis-atlas"])
    verifier = SnapshotEvidenceResolver()

    outcome = validate_event(raw_event, evidence=verifier, subjects=resolver)
    assert isinstance(outcome, EventRefusal)
    assert outcome.reason == "missing_mandatory_evidence"
    assert outcome.field_path == "new_points"


def test_validation_refuses_artifact_hash_mismatch() -> None:
    snapshot_text = "Actual snapshot text"
    wrong_hash = "0" * 64

    card_ref = SubjectRef(kind="card", source_name="Atlas", kb_id="axis-atlas")

    raw_event = ExtractedEvent(
        event_type="earn_rate_change",
        title="Test",
        summary="Test",
        source_url="https://example.com",
        subjects=(card_ref,),
        effective_window=EffectiveWindow(start_date=date(2026, 1, 1)),
        terms=EarnRateChangeTerms(
            card=card_ref,
            new_points=2,
            new_per_amount_minor=10000,
            currency="INR",
            effective_start=date(2026, 1, 1),
            spend_scope="All",
        ),
        evidence_spans=(),
        source_policy_id="pol",
        source_policy_hash="pol-hash",
        target_id="target",
        snapshot_id="snap",
        artifact_sha256="art",
        raw_sha256="raw",
        normalized_sha256=wrong_hash,
        fetch_attempt_id="fetch",
        observed_at=datetime.now(UTC),
        fidelity="synthetic_fixture",
        snapshot_text=snapshot_text,
    )

    outcome = validate_event(
        raw_event,
        evidence=SnapshotEvidenceResolver(),
        subjects=KBSubjectResolver(),
    )
    assert isinstance(outcome, EventRefusal)
    assert outcome.reason == "artifact_hash_mismatch"


# --- 6. Supersession vs. Conflict Classification ---


def test_supersession_requires_verified_source_occurrence_otherwise_conflict() -> None:
    now = datetime.now(UTC)
    card_ref = SubjectRef(kind="card", source_name="Atlas", kb_id="axis-atlas")
    window = EffectiveWindow(start_date=date(2026, 11, 1))

    terms_v1 = EarnRateChangeTerms(
        card=card_ref,
        new_points=2,
        new_per_amount_minor=10000,
        currency="INR",
        effective_start=date(2026, 11, 1),
        spend_scope="All",
    )
    terms_v2 = EarnRateChangeTerms(
        card=card_ref,
        new_points=3,
        new_per_amount_minor=10000,
        currency="INR",
        effective_start=date(2026, 11, 1),
        spend_scope="All",
    )

    ev1 = compute_event_id(1, "earn_rate_change", [card_ref], window, terms_v1)
    ev2 = compute_event_id(1, "earn_rate_change", [card_ref], window, terms_v2)

    event_1 = ChangeEvent(
        event_id=ev1,
        event_type="earn_rate_change",
        subjects=(card_ref,),
        effective_window=window,
        terms=terms_v1,
        first_seen_at=now,
        latest_observed_at=now,
        title="v1",
        summary="v1",
        source_url="https://example.com/promo1",
    )

    # Case A: Same source URL, newer observation -> supersedes
    later = datetime.fromtimestamp(now.timestamp() + 3600, tz=UTC)
    event_2_same_url = ChangeEvent(
        event_id=ev2,
        event_type="earn_rate_change",
        subjects=(card_ref,),
        effective_window=window,
        terms=terms_v2,
        first_seen_at=later,
        latest_observed_at=later,
        title="v2",
        summary="v2",
        source_url="https://example.com/promo1",
    )
    assert classify_event_relationship(event_1, event_2_same_url) == "supersedes"

    # Case B: Different source URL, matching subject/dates -> conflict (not automatic supersession!)
    event_2_diff_url = ChangeEvent(
        event_id=ev2,
        event_type="earn_rate_change",
        subjects=(card_ref,),
        effective_window=window,
        terms=terms_v2,
        first_seen_at=later,
        latest_observed_at=later,
        title="v2",
        summary="v2",
        source_url="https://other.com/different-promo",
    )
    assert classify_event_relationship(event_1, event_2_diff_url) == "conflict"


def test_supersession_handles_unmapped_subjects_correctly() -> None:
    now = datetime.now(UTC)
    unmapped_card = SubjectRef(kind="card", source_name="Unmapped Brand New Card", kb_id=None)
    window = EffectiveWindow(start_date=date(2026, 11, 1))

    terms_v1 = EarnRateChangeTerms(
        card=unmapped_card,
        new_points=2,
        new_per_amount_minor=10000,
        currency="INR",
        effective_start=date(2026, 11, 1),
        spend_scope="All",
    )
    terms_v2 = EarnRateChangeTerms(
        card=unmapped_card,
        new_points=4,
        new_per_amount_minor=10000,
        currency="INR",
        effective_start=date(2026, 11, 1),
        spend_scope="All",
    )

    ev1 = compute_event_id(1, "earn_rate_change", [unmapped_card], window, terms_v1)
    ev2 = compute_event_id(1, "earn_rate_change", [unmapped_card], window, terms_v2)

    event_1 = ChangeEvent(
        event_id=ev1,
        event_type="earn_rate_change",
        subjects=(unmapped_card,),
        effective_window=window,
        terms=terms_v1,
        first_seen_at=now,
        latest_observed_at=now,
        title="v1",
        summary="v1",
        source_url="https://example.com/unmapped-promo",
    )

    later = datetime.fromtimestamp(now.timestamp() + 3600, tz=UTC)
    event_2 = ChangeEvent(
        event_id=ev2,
        event_type="earn_rate_change",
        subjects=(unmapped_card,),
        effective_window=window,
        terms=terms_v2,
        first_seen_at=later,
        latest_observed_at=later,
        title="v2",
        summary="v2",
        source_url="https://example.com/unmapped-promo",
    )

    # Must classify as supersedes rather than returning independent
    assert classify_event_relationship(event_1, event_2) == "supersedes"


# --- 7. PageKind and Candidate Promotion ---


def test_candidate_promotion_uses_manual_safe_defaults_for_new_kinds() -> None:
    curator_dec = CuratorPromotion(
        curator_id="curator-alice",
        decided_at=datetime.now(UTC),
        source_policy_id="manual-policy-v1",
    )

    # 1. transfer_bonus candidate
    tb_cand = DiscoveryCandidate(
        id="cand-tb-1",
        found_at=date(2026, 11, 1),
        hint_url="https://aggregator.example/lead",
        hint_source="lead_aggregator",
        corridor="IN",
        kind="transfer_bonus",
        issuer_guess="Axis",
        product_guess="EDGE Rewards",
        claim_summary="30% bonus to Marriott",
        issuer_url_to_verify="https://www.axis.bank.in/partners",
        status="pending",
    )
    target_tb = promote_candidate_to_watch_target(tb_cand, curator_dec)
    assert target_tb.page_kind == PageKind.PARTNER_TABLE
    assert target_tb.preferred_backend == "manual"
    assert target_tb.manual_only is True

    # 2. welcome_offer candidate
    wo_cand = DiscoveryCandidate(
        id="cand-wo-1",
        found_at=date(2026, 11, 1),
        hint_url="https://aggregator.example/lead2",
        hint_source="lead_aggregator",
        corridor="IN",
        kind="welcome_offer",
        issuer_guess="HDFC",
        product_guess="Infinia",
        claim_summary="10,000 bonus points on activation",
        issuer_url_to_verify="https://www.hdfc.bank.in/infinia",
        status="pending",
    )
    target_wo = promote_candidate_to_watch_target(wo_cand, curator_dec)
    assert target_wo.page_kind == PageKind.OFFER_PAGE
    assert target_wo.preferred_backend == "manual"
    assert target_wo.manual_only is True

    # 3. earn_rate_change candidate
    er_cand = DiscoveryCandidate(
        id="cand-er-1",
        found_at=date(2026, 11, 1),
        hint_url="https://aggregator.example/lead3",
        hint_source="lead_aggregator",
        corridor="IN",
        kind="earn_rate_change",
        issuer_guess="Axis",
        product_guess="Atlas",
        claim_summary="5x on dining",
        issuer_url_to_verify="https://www.axis.bank.in/atlas",
        status="pending",
    )
    target_er = promote_candidate_to_watch_target(er_cand, curator_dec)
    assert target_er.page_kind == PageKind.CARD_PAGE
    assert target_er.preferred_backend == "manual"
    assert target_er.manual_only is True


def test_fetch_request_refuses_new_page_kinds_for_automated_official_page() -> None:
    # Sol's spec: Enum additions must not silently authorize new crawling
    with pytest.raises(
        ValueError,
        match="official_page evidence requires a card_page or offer_page class",
    ):
        FetchRequest(
            request_id="req-1",
            canonical_url="https://example.com/promo",
            source_policy_id="policy-1",
            evidence_kind="official_page",
            page_class=PageKind.PARTNER_TABLE,  # not permitted for official_page
            max_bytes=100_000,
            max_pages=1,
            timeout_seconds=10,
            run_id="run-1",
        )


# --- 8. Terms Validation and Boundaries ---


def test_welcome_offer_terms_validation_rules() -> None:
    card_ref = SubjectRef(kind="card", source_name="Infinia", kb_id="hdfc-infinia")
    prog_ref = SubjectRef(kind="loyalty_program", source_name="SmartBuy", kb_id="hdfc-smartbuy")

    # 1. Neither points nor cash -> fails
    with pytest.raises(
        ValueError,
        match="requires either positive bonus_points or positive bonus_cash_minor",
    ):
        WelcomeOfferTerms(
            card=card_ref,
            min_spend_minor=10000000,
            min_spend_currency="INR",
            spend_window_days=90,
            quoted_spend_window="spend 1,00,000 within 90 days",
        )

    # 2. Points without program -> fails
    with pytest.raises(ValueError, match="points bonus requires bonus_program SubjectRef"):
        WelcomeOfferTerms(
            card=card_ref,
            bonus_points=10000,
            min_spend_minor=10000000,
            min_spend_currency="INR",
            spend_window_days=90,
            quoted_spend_window="spend 1,00,000 within 90 days",
        )

    # 3. Cash without currency -> fails
    with pytest.raises(ValueError, match="cash bonus requires currency ISO code"):
        WelcomeOfferTerms(
            card=card_ref,
            bonus_cash_minor=200000,
            min_spend_minor=10000000,
            min_spend_currency="INR",
            spend_window_days=90,
            quoted_spend_window="spend 1,00,000 within 90 days",
        )

    # 4. Missing spend window -> fails
    with pytest.raises(ValueError, match="requires spend_window_days or spend_window_months"):
        WelcomeOfferTerms(
            card=card_ref,
            bonus_points=10000,
            bonus_program=prog_ref,
            min_spend_minor=10000000,
            min_spend_currency="INR",
            quoted_spend_window="spend 1,00,000",
        )

    # 5. Valid points bonus succeeds
    valid_points = WelcomeOfferTerms(
        card=card_ref,
        bonus_points=10000,
        bonus_program=prog_ref,
        min_spend_minor=10000000,
        min_spend_currency="INR",
        spend_window_days=90,
        quoted_spend_window="spend 1,00,000 within 90 days",
    )
    assert valid_points.bonus_points == 10000
    assert valid_points.spend_window_basis == "approval"

    # 6. Valid cash bonus succeeds
    valid_cash = WelcomeOfferTerms(
        card=card_ref,
        bonus_cash_minor=500000,
        currency="INR",
        min_spend_minor=10000000,
        min_spend_currency="INR",
        spend_window_months=3,
        quoted_spend_window="spend 1,00,000 within 3 months",
    )
    assert valid_cash.bonus_cash_minor == 500000


def test_transfer_bonus_bounds_and_dates() -> None:
    p1 = SubjectRef(kind="loyalty_program", source_name="P1", kb_id="p1")
    p2 = SubjectRef(kind="loyalty_program", source_name="P2", kb_id="p2")

    # Outlier bonus_bp > 100,000 is rejected by model bounds
    with pytest.raises(ValueError):
        TransferBonusTerms(
            from_program=p1,
            to_program=p2,
            bonus_bp=100001,
            quoted_dates="Nov 1-30",
        )

    # Negative bonus_bp is rejected
    with pytest.raises(ValueError):
        TransferBonusTerms(
            from_program=p1,
            to_program=p2,
            bonus_bp=-100,
            quoted_dates="Nov 1-30",
        )


def test_welcome_offer_end_to_end_validation() -> None:
    text = "Get 10,000 Reward Points on spending ₹1,00,000 within 90 days of card issuance."
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    span_pts = FieldSpan(
        field_path="bonus_points",
        quote="10,000 Reward Points",
        start_offset=4,
        end_offset=24,
    )
    span_spend = FieldSpan(
        field_path="min_spend_minor",
        quote="₹1,00,000",
        start_offset=37,
        end_offset=46,
    )
    span_win = FieldSpan(
        field_path="quoted_spend_window",
        quote="within 90 days of card issuance",
        start_offset=47,
        end_offset=78,
    )

    card_ref = SubjectRef(kind="card", source_name="Infinia", kb_id="hdfc-infinia")
    prog_ref = SubjectRef(kind="loyalty_program", source_name="SmartBuy", kb_id="hdfc-smartbuy")

    raw = ExtractedEvent(
        event_type="welcome_offer",
        title="HDFC Infinia 10k Welcome Points",
        summary="10,000 points on 1L spend in 90 days",
        source_url="https://www.hdfc.bank.in/infinia",
        subjects=(card_ref,),
        effective_window=EffectiveWindow(start_date=date(2026, 11, 1)),
        terms=WelcomeOfferTerms(
            card=card_ref,
            bonus_points=10000,
            bonus_program=prog_ref,
            min_spend_minor=10000000,
            min_spend_currency="INR",
            spend_window_days=90,
            spend_window_basis="approval",
            quoted_spend_window="within 90 days of card issuance",
        ),
        evidence_spans=(span_pts, span_spend, span_win),
        source_policy_id="hdfc-policy",
        source_policy_hash="pol-hash",
        target_id="hdfc-infinia-target",
        snapshot_id="snap-hdfc-1",
        artifact_sha256="art-sha",
        raw_sha256="raw-sha",
        normalized_sha256=text_hash,
        fetch_attempt_id="fetch-hdfc-1",
        observed_at=datetime.now(UTC),
        fidelity="original_issuer_bytes",
        snapshot_text=text,
    )

    resolver = KBSubjectResolver(card_ids=["hdfc-infinia"], program_ids=["hdfc-smartbuy"])
    verifier = SnapshotEvidenceResolver()

    outcome = validate_event(raw, evidence=verifier, subjects=resolver)
    assert isinstance(outcome, ValidatedEvent)
    assert outcome.is_personal_impact_eligible is True
    # Welcome offer is unsupported_target for review_rows facts lane (Sol §4)
    assert outcome.facts_status == "unsupported_target"
    assert len(outcome.evidence_receipts) == 1

