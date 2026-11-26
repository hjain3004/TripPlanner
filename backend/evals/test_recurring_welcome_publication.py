"""Review, controlled publication, catalog reload and API consumption of welcome offers.

Execution mode: retained synthetic captures (no network, no credits), real SQLite and artifacts,
the real review/decision service, the real publisher and journaled writer, and the real
authenticated API reading the published file. The curator is a registered acceptance identity, and
every row is synthetic: nothing here approves or publishes a real issuer fact.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from api.main import app
from api.welcome import get_as_of
from core.db import SEEDS_DIR
from evals.test_recurring_welcome_extraction import (
    World,
    capture,
    offer_json,
    page,
)
from evals.welcome_support import plan_and_save, request_status
from ingestion.contracts import CuratorRecord, ProposalStatus
from ingestion.review import ReviewService
from ingestion.review_queue import build_review_queue
from ingestion.review_rows import SeedRowSource
from ingestion.review_types import DecisionRequest
from ingestion.welcome_publication import (
    CATALOG_FILE,
    PublicationRefused,
    WelcomePublisher,
    init_catalog,
    read_catalog_rows,
)
from welcome import catalog as welcome_catalog

CARD = "hdfc-infinia"  # a seeded card, so the real planning path can hold it
OPENED = date(2026, 10, 1)
AS_OF = date(2026, 10, 24)


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(welcome_catalog.OFFERS_PATH_ENV, raising=False)
    welcome_catalog.reload_offer_catalog()
    yield
    app.dependency_overrides.clear()
    monkeypatch.delenv(welcome_catalog.OFFERS_PATH_ENV, raising=False)
    welcome_catalog.reload_offer_catalog()


class Rig:
    def __init__(self, tmp_path: Path, payloads: list[dict[str, Any]]) -> None:
        self.world = World(tmp_path, payloads, published=None, card=CARD)
        self.catalog_dir = tmp_path / "published"
        init_catalog(self.catalog_dir)
        self.world.published = {}
        self.world.store.put_curator(
            CuratorRecord(
                curator_id="acceptance-curator",
                display_name="Acceptance curator",
                created_at=self.world.clock,
            )
        )
        self.event = 0
        self._wire()

    def _wire(self) -> None:
        self.world.published = read_catalog_rows(self.catalog_dir)
        self.review = ReviewService(
            store=self.world.store,
            artifacts=self.world.artifacts,
            rows=SeedRowSource(SEEDS_DIR, catalog_dir=self.catalog_dir),
            now=lambda: self.world.clock,
        )
        self.publisher = WelcomePublisher(
            store=self.world.store,
            artifacts=self.world.artifacts,
            catalog_dir=self.catalog_dir,
            state_dir=self.world.root / "publisher",
            now=lambda: self.world.clock,
        )

    def acquire(self) -> Any:
        self.event += 1
        self.world.published = read_catalog_rows(self.catalog_dir)
        return self.world.run(f"evt-{self.event}")

    def approve(self, proposal_id: str) -> None:
        proposal = self.world.store.get_proposal(proposal_id)
        assert proposal is not None
        self.review.decide(
            DecisionRequest(
                proposal_id=proposal_id,
                action="approve",
                reason="synthetic acceptance approval of retained synthetic capture",
                expected_version=proposal.version,
                client_event_id=f"approve-{self.event:016d}",
                curator_confidence=0.8,
            ),
            curator_id="acceptance-curator",
        )

    def point_service_at_catalog(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(welcome_catalog.OFFERS_PATH_ENV, str(self.catalog_dir / CATALOG_FILE))


def test_publication_is_refused_until_a_registered_curator_approves(tmp_path: Path) -> None:
    rig = Rig(tmp_path, [capture(page(), offer_json())])
    outcome = rig.acquire()
    with pytest.raises(PublicationRefused) as refused:
        rig.publisher.publish(outcome.proposal_ids[0])
    assert refused.value.code == "not_approved"
    assert read_catalog_rows(rig.catalog_dir) == {}


def test_approved_insert_is_published_with_the_curators_provenance_and_stays_unverified(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, [capture(page(), offer_json())])
    outcome = rig.acquire()
    queue = build_review_queue(
        store=rig.world.store,
        service=rig.review,
        as_of=rig.world.clock,
        statuses=(ProposalStatus.PENDING,),
    )
    assert [item.proposal_id for item in queue] == list(outcome.proposal_ids)

    rig.approve(outcome.proposal_ids[0])
    record = rig.publisher.publish(outcome.proposal_ids[0])
    rows = read_catalog_rows(rig.catalog_dir)
    row = rows[rig.world.offer_id]
    assert row["provenance"]["verified_by"] == "acceptance-curator"
    assert row["provenance"]["source_type"] == "official_page"
    assert row["provenance"]["confidence"] == 0.8
    # Currency, the points-currency mapping and the exclusions had no quoted evidence, so the
    # row stays flagged for verification instead of being declared verified.
    assert record.needs_verification is True and row["provenance"]["needs_verification"] is True
    assert record.catalog_sha256_before != record.catalog_sha256_after
    assert [e["event_type"] for e in rig.publisher.history()] == ["published"]

    again = rig.publisher.publish(outcome.proposal_ids[0])  # safe to repeat
    assert again.already_published and again.publication_id == record.publication_id
    assert len(rig.publisher.history()) == 1


def test_the_publisher_never_writes_inside_the_repository(tmp_path: Path) -> None:
    rig = Rig(tmp_path, [capture(page(), offer_json())])
    outcome = rig.acquire()
    rig.approve(outcome.proposal_ids[0])
    inside = WelcomePublisher(
        store=rig.world.store,
        artifacts=rig.world.artifacts,
        catalog_dir=Path(__file__).resolve().parent.parent / "welcome" / "data",
        state_dir=tmp_path / "state",
        now=lambda: rig.world.clock,
    )
    with pytest.raises(PublicationRefused) as refused:
        inside.publish(outcome.proposal_ids[0])
    assert refused.value.code == "protected_catalog"


def test_a_published_offer_reaches_the_authenticated_api_and_reloads_without_a_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(
        tmp_path,
        [capture(page(), offer_json()), capture(page(spend="40,000"), offer_json(spend="40,000"))],
    )
    client, _store, trip_id, entry_id = (lambda r: (r[0], r[1], r[2]["trip"]["id"], r[3][0]))(
        plan_and_save(tmp_path, monkeypatch, cards=[(CARD, OPENED)])
    )
    app.dependency_overrides[get_as_of] = lambda: AS_OF

    # 1. The service starts on the shipped, empty catalog.
    before = request_status(client, entry_id, trip_id, prior=100).json()
    assert {item["code"] for item in before["limitations"]} == {"NO_APPROVED_OFFER"}

    # 2. Collect, review, approve, publish; point the service at the operator catalog.
    first = rig.acquire()
    rig.approve(first.proposal_ids[0])
    rig.publisher.publish(first.proposal_ids[0])
    rig.point_service_at_catalog(monkeypatch)

    after = request_status(client, entry_id, trip_id, prior=100).json()
    assert after["offer"] is not None and after["offer"]["id"] == rig.world.offer_id
    assert after["offer"]["min_spend_minor"] == 3_000_000
    assert "NO_APPROVED_OFFER" not in {item["code"] for item in after["limitations"]}

    # 3. The issuer changes the terms: a new collection proposes an update, a curator approves
    #    it, and the very next request sees it, with no restart and no manual reload.
    second = rig.acquire()
    update = rig.world.store.get_proposal(second.proposal_ids[0])
    assert update is not None and update.intent == "update"
    rig._wire()
    rig.approve(second.proposal_ids[0])
    rig.publisher.publish(second.proposal_ids[0])
    changed = request_status(client, entry_id, trip_id, prior=100).json()
    assert changed["offer"]["min_spend_minor"] == 4_000_000


def test_rollback_restores_the_previous_catalog_and_the_service_follows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, [capture(page(), offer_json())])
    rig.point_service_at_catalog(monkeypatch)
    empty_sha = (rig.catalog_dir / CATALOG_FILE).read_bytes()
    assert welcome_catalog.shipped_offer_catalog().offers_for_card(CARD) == []

    outcome = rig.acquire()
    rig.approve(outcome.proposal_ids[0])
    record = rig.publisher.publish(outcome.proposal_ids[0])
    assert len(welcome_catalog.shipped_offer_catalog().offers_for_card(CARD)) == 1

    rig.publisher.rollback(record.publication_id)
    assert (rig.catalog_dir / CATALOG_FILE).read_bytes() == empty_sha
    assert welcome_catalog.shipped_offer_catalog().offers_for_card(CARD) == []
    assert [e["event_type"] for e in rig.publisher.history()] == ["published", "rolled_back"]
    with pytest.raises(PublicationRefused) as refused:
        rig.publisher.rollback(record.publication_id)
    assert refused.value.code == "already_rolled_back"


def test_a_corrupt_catalog_edit_keeps_serving_the_last_good_one_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, [capture(page(), offer_json())])
    rig.point_service_at_catalog(monkeypatch)
    outcome = rig.acquire()
    rig.approve(outcome.proposal_ids[0])
    rig.publisher.publish(outcome.proposal_ids[0])
    assert len(welcome_catalog.shipped_offer_catalog().offers_for_card(CARD)) == 1

    (rig.catalog_dir / CATALOG_FILE).write_text("- id: [unterminated\n", encoding="utf-8")
    assert len(welcome_catalog.shipped_offer_catalog().offers_for_card(CARD)) == 1
    assert welcome_catalog.last_reload_error is not None


def test_a_synthetic_verifier_is_never_served_from_the_service_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, [capture(page(), offer_json())])
    rig.world.store.put_curator(
        CuratorRecord(
            curator_id="synthetic-reviewer",
            display_name="Synthetic",
            created_at=rig.world.clock,
        )
    )
    outcome = rig.acquire()
    proposal = rig.world.store.get_proposal(outcome.proposal_ids[0])
    assert proposal is not None
    rig.review.decide(
        DecisionRequest(
            proposal_id=outcome.proposal_ids[0],
            action="approve",
            reason="synthetic",
            expected_version=proposal.version,
            client_event_id="approve-synthetic-0001",
            curator_confidence=0.5,
        ),
        curator_id="synthetic-reviewer",
    )
    rig.publisher.publish(outcome.proposal_ids[0])
    rig.point_service_at_catalog(monkeypatch)
    # The loader refuses the file, so the service keeps its last good (here: empty) catalog.
    assert welcome_catalog.shipped_offer_catalog().offers_for_card(CARD) == []
    assert welcome_catalog.last_reload_error is not None
    assert "synthetic" in welcome_catalog.last_reload_error


def _publish_one(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    rig.point_service_at_catalog(monkeypatch)
    outcome = rig.acquire()
    rig.approve(outcome.proposal_ids[0])
    rig.publisher.publish(outcome.proposal_ids[0])


def test_a_catalog_file_that_disappears_keeps_the_last_good_copy_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, [capture(page(), offer_json())])
    _publish_one(rig, monkeypatch)
    path = rig.catalog_dir / CATALOG_FILE
    good = path.read_bytes()
    assert len(welcome_catalog.shipped_offer_catalog().offers_for_card(CARD)) == 1
    assert welcome_catalog.catalog_status()["serving_last_good_copy"] is False

    path.unlink()  # temporarily gone
    served = welcome_catalog.shipped_offer_catalog()
    assert len(served.offers_for_card(CARD)) == 1  # the earlier approved copy, not invented data
    status = welcome_catalog.catalog_status()
    assert status["serving_last_good_copy"] is True
    assert "FileNotFoundError" in str(status["last_reload_error"])
    assert status["failing_since"] is not None

    path.write_bytes(good)  # restored: the failure clears and nothing is reported stale
    assert len(welcome_catalog.shipped_offer_catalog().offers_for_card(CARD)) == 1
    status = welcome_catalog.catalog_status()
    assert status["serving_last_good_copy"] is False and status["last_reload_error"] is None


def test_with_no_good_catalog_ever_loaded_the_failure_is_controlled_and_nothing_is_invented(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(welcome_catalog.OFFERS_PATH_ENV, str(tmp_path / "missing.yaml"))
    welcome_catalog._loaded = None
    with pytest.raises(welcome_catalog.OfferCatalogError, match="unavailable"):
        welcome_catalog.shipped_offer_catalog()
    assert welcome_catalog.catalog_status()["loaded"] is False


def test_the_api_answers_503_not_an_empty_success_when_the_catalog_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, trip_id, entry_id = (lambda r: (r[0], r[1], r[2]["trip"]["id"], r[3][0]))(
        plan_and_save(tmp_path, monkeypatch, cards=[(CARD, OPENED)])
    )
    app.dependency_overrides[get_as_of] = lambda: AS_OF
    monkeypatch.setenv(welcome_catalog.OFFERS_PATH_ENV, str(tmp_path / "missing.yaml"))
    welcome_catalog._loaded = None
    response = request_status(client, entry_id, trip_id, prior=100)
    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"]


def test_historical_and_expired_offer_rules_still_apply_to_a_last_good_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, [capture(page(), offer_json())])
    _publish_one(rig, monkeypatch)
    catalog = welcome_catalog.shipped_offer_catalog()
    (rig.catalog_dir / CATALOG_FILE).unlink()
    stale = welcome_catalog.shipped_offer_catalog()
    assert stale is catalog
    # The offer's campaign ended 2026-11-30. A card opened before then still gets it; a card
    # opened after is not matched to an expired campaign, whether or not the catalog is stale.
    assert stale.select_offer(CARD, date(2026, 10, 1)).offer is not None
    expired = stale.select_offer(CARD, date(2026, 12, 15))
    assert expired.offer is None and expired.reason == "OFFER_NOT_IN_FORCE_AT_OPEN_DATE"
