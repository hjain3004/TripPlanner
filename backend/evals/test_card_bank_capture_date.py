"""stage-capture records when the document was captured, not when it was staged.

Found staging a real issuer capture days after it was saved: the snapshot (and so every
``last_verified`` derived from it) carried the staging date, which made a stale capture look
current. The operator now states the capture time; the stored snapshot is immutable evidence, so
a later contradictory claim is refused rather than overwritten. Synthetic documents only.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from evals.test_card_bank_cli import FEE as CLI_FEE
from evals.test_card_bank_cli import Workspace, cli, extraction, rec, seed_hashes
from evals.test_card_bank_staging import NOW, PAGE, Env, StageRefusalCode, fee

CAPTURED = datetime(2026, 10, 31, 5, 40, tzinfo=UTC)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def _counts(env: Env) -> dict[str, int]:
    with env.store._connect() as connection:
        return {
            name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for name in (
                "source_policies",
                "watch_targets",
                "snapshot_manifests",
                "change_proposals",
            )
        }


def test_a_stated_capture_time_is_what_the_snapshot_records(env: Env) -> None:
    outcome = env.stage([fee()], captured_at=CAPTURED)
    assert outcome.status == "staged", outcome.refusals
    assert outcome.captured_at == CAPTURED
    assert outcome.captured_at_source == "operator_supplied"
    snapshot = env.store.get_snapshot(outcome.snapshot_id or "")
    assert snapshot is not None and snapshot.captured_at == CAPTURED
    (attempt,) = snapshot.attempts
    assert attempt.started_at == CAPTURED and attempt.ended_at == CAPTURED


def test_without_one_the_staging_time_is_used_and_said_so(env: Env) -> None:
    outcome = env.stage([fee()])
    assert outcome.captured_at == NOW and outcome.captured_at_source == "staging_time"


def test_restaging_the_same_snapshot_reports_the_stored_time(env: Env) -> None:
    first = env.stage([fee()], captured_at=CAPTURED)
    later = NOW + timedelta(days=3)
    again = env.stage([fee()], captured_at=CAPTURED, now=lambda: later)
    assert again.status == "staged", again.refusals
    assert again.snapshot_state == "already_stored"
    assert again.captured_at == CAPTURED and again.captured_at_source == "stored_snapshot"
    assert first.proposals[0].proposal_id == again.proposals[0].proposal_id
    silent = env.stage([fee()], now=lambda: later)
    assert silent.captured_at == CAPTURED and silent.captured_at_source == "stored_snapshot"


def test_a_contradicting_capture_time_is_refused_and_writes_nothing(env: Env) -> None:
    env.stage([fee()], captured_at=CAPTURED)
    before = _counts(env)
    other = env.stage([fee()], captured_at=CAPTURED + timedelta(days=2))
    assert other.status == "refused"
    assert [r.code for r in other.refusals] == [StageRefusalCode.CAPTURED_AT_CONFLICT]
    assert _counts(env) == before


def test_a_capture_time_earlier_than_the_targets_latest_snapshot_is_refused(env: Env) -> None:
    env.stage([fee()], captured_at=CAPTURED)
    newer_content = env.root / "other.html"
    newer_content.write_text(PAGE + "<p>An extra paragraph.</p>", encoding="utf-8")
    before = _counts(env)
    backdated = env.stage([fee()], capture=newer_content, captured_at=CAPTURED - timedelta(days=30))
    assert backdated.status == "refused"
    assert [r.code for r in backdated.refusals] == [StageRefusalCode.CAPTURED_AT_CONFLICT]
    assert _counts(env) == before
    later = env.stage([fee()], capture=newer_content, captured_at=CAPTURED + timedelta(days=1))
    assert later.status == "staged", later.refusals


@pytest.mark.parametrize(
    "bad",
    [datetime(2026, 10, 31, 5, 40), NOW + timedelta(minutes=1)],
    ids=["naive", "in_the_future"],
)
def test_an_unusable_capture_time_is_refused_before_any_write(env: Env, bad: datetime) -> None:
    before = _counts(env)
    outcome = env.stage([fee()], captured_at=bad)
    assert outcome.status == "refused"
    assert [r.code for r in outcome.refusals] == [StageRefusalCode.CAPTURED_AT_INVALID]
    assert _counts(env) == before


def test_the_cli_flag_reaches_the_stored_snapshot(tmp_path: Path) -> None:
    work = Workspace(tmp_path)
    work.write("extraction.yaml", extraction(rec("annual_fee_minor", "INR 15,000", CLI_FEE)))
    added = cli(
        [
            "add-curator",
            "--data-dir",
            str(work.data),
            "--curator-id",
            "alice",
            "--display-name",
            "Alice",
        ]
    )
    assert added.returncode == 0, added.stderr
    before = seed_hashes()
    done = work.stage("extraction.yaml", extra=["--captured-at", "2026-10-31T05:40:00+00:00"])
    assert done.returncode == 0, done.stderr
    report = json.loads(done.stdout)
    assert report["captured_at"] == "2026-10-31T05:40:00Z"
    assert report["captured_at_source"] == "operator_supplied"
    for text in ("yesterday", "2026-10-31T05:40:00"):
        bad = work.stage("extraction.yaml", extra=["--captured-at", text])
        assert bad.returncode == 2 and "captured-at" in bad.stderr, text
    assert seed_hashes() == before
