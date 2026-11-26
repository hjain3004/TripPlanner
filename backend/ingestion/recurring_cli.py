"""Operator commands for the recurring welcome-offer workflow.

``acquire`` and ``refresh-due`` live in ``review_server``; this module adds what they need to
collect welcome offers through Firecrawl-hosted extraction and to be run on a schedule:

* ``--welcome-targets``: which watched pages are welcome-offer pages and what the operator (not
  the page) says about each card;
* ``--lifetime-credits`` / ``--opening-credits-used``: the persistent lifetime allowance;
* ``recurring-run``: one bounded, locked, repeatable ``refresh-due`` pass for a scheduler;
* ``init-welcome-catalog``, ``publish-welcome``, ``rollback-welcome``, ``welcome-history``,
  ``credit-status``: controlled publication and the credit ledger.

Nothing here approves a fact. Publication needs a prior approval by a registered curator.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from ingestion.acquisition_control import AcquisitionControlLimits, DurableAcquisitionControl
from ingestion.artifacts import ContentAddressedStore
from ingestion.extraction_runtime import ExtractionMode, ExtractionRuntimeConfig
from ingestion.firecrawl_transport import HTML_SCRAPE_CREDITS, JSON_EXTRACTION_EXTRA_CREDITS
from ingestion.review_rows import SeedRowError, SeedRowSource
from ingestion.storage import FinancialIngestionStore
from ingestion.welcome_extraction import WelcomeTargetConfig
from ingestion.welcome_publication import (
    PublicationRefused,
    WelcomePublisher,
    init_catalog,
    read_catalog_rows,
)

MANAGED_CREDITS = HTML_SCRAPE_CREDITS + JSON_EXTRACTION_EXTRA_CREDITS
BUSY_EXIT_CODE = 75  # EX_TEMPFAIL: another recurring run holds the lock; try again later


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Options shared by ``acquire``, ``refresh-due`` and ``recurring-run``."""
    parser.add_argument(
        "--welcome-targets",
        default=None,
        help="YAML naming the watched pages that carry welcome offers, and their card ids",
    )
    parser.add_argument(
        "--published-welcome-catalog",
        default=None,
        help="directory of the published catalog, so changed terms become updates",
    )
    parser.add_argument("--lifetime-credits", type=int, default=None)
    parser.add_argument("--opening-credits-used", type=int, default=0)


def _no_rows() -> Mapping[str, dict[str, Any]]:
    return {}


@dataclass(frozen=True)
class WelcomeWiring:
    targets: Mapping[str, WelcomeTargetConfig] = field(default_factory=dict)
    ext_by_target: Mapping[str, ExtractionRuntimeConfig] = field(default_factory=dict)
    published_rows: Callable[[], Mapping[str, dict[str, Any]]] = _no_rows


def build_welcome_wiring(args: argparse.Namespace, *, seeds_dir: Path) -> WelcomeWiring:
    path = getattr(args, "welcome_targets", None)
    catalog = getattr(args, "published_welcome_catalog", None)
    published: Callable[[], Mapping[str, dict[str, Any]]] = _no_rows
    if catalog:
        catalog_dir = Path(catalog)

        def published() -> Mapping[str, dict[str, Any]]:  # noqa: F811
            return read_catalog_rows(catalog_dir)

    if not path:
        return WelcomeWiring(published_rows=published)
    if int(args.per_request_credits) < MANAGED_CREDITS:
        raise ValueError(
            f"welcome extraction costs {MANAGED_CREDITS} credits per page "
            f"({HTML_SCRAPE_CREDITS} page + {JSON_EXTRACTION_EXTRA_CREDITS} extraction); "
            f"--per-request-credits must be at least {MANAGED_CREDITS}"
        )
    raw = yaml.safe_load(Path(path).read_bytes()) or {}
    entries = raw.get("targets") if isinstance(raw, dict) else None
    if not isinstance(entries, dict) or not entries:
        raise ValueError("--welcome-targets needs a non-empty 'targets' mapping")
    seeds = SeedRowSource(seeds_dir)
    targets: dict[str, WelcomeTargetConfig] = {}
    for target_id, item in entries.items():
        if not isinstance(item, dict) or not item.get("card_id") or not item.get("source_url"):
            raise ValueError(f"welcome target {target_id!r} needs card_id and source_url")
        currency = item.get("default_currency")
        if not currency:
            try:
                currency = seeds.current_row("cards", str(item["card_id"]))["fee_currency"]
            except SeedRowError as error:
                raise ValueError(
                    f"welcome target {target_id!r}: card {item['card_id']!r} is not a seeded "
                    "card, so its currency is unknown; set default_currency explicitly"
                ) from error
        targets[str(target_id)] = WelcomeTargetConfig(
            card_id=str(item["card_id"]),
            source_url=str(item["source_url"]),
            default_currency=str(currency),
            points_currency_id=(
                str(item["points_currency_id"]) if item.get("points_currency_id") else None
            ),
        )
    managed = ExtractionRuntimeConfig(mode=ExtractionMode.FIRECRAWL_MANAGED)
    return WelcomeWiring(
        targets=targets,
        ext_by_target={target_id: managed for target_id in targets},
        published_rows=published,
    )


def control_limits(args: argparse.Namespace, *, managed: bool) -> AcquisitionControlLimits:
    return AcquisitionControlLimits(
        per_request_credits=args.per_request_credits,
        per_run_credits=args.per_run_credits,
        per_month_credits=args.per_month_credits,
        pricing_version=args.pricing_version,
        extraction_intent="raw_html+firecrawl_json_v2" if managed else "raw_html",
        lifetime_credits=getattr(args, "lifetime_credits", None),
        lifetime_opening_used=int(getattr(args, "opening_credits_used", 0) or 0),
    )


# --------------------------------------------------------------------------- publication


def add_commands(sub: Any) -> None:
    before = set(sub.choices)
    _add_commands(sub)
    for name in set(sub.choices) - before:
        sub.choices[name].add_argument("--seeds-dir", default=None)


def _add_commands(sub: Any) -> None:
    init = sub.add_parser("init-welcome-catalog")
    init.add_argument("--data-dir", default=None)
    init.add_argument("--catalog-dir", required=True)
    publish = sub.add_parser("publish-welcome")
    publish.add_argument("--data-dir", default=None)
    publish.add_argument("--catalog-dir", required=True)
    publish.add_argument("--proposal-id", required=True)
    rollback = sub.add_parser("rollback-welcome")
    rollback.add_argument("--data-dir", default=None)
    rollback.add_argument("--catalog-dir", required=True)
    rollback.add_argument("--publication-id", required=True)
    history = sub.add_parser("welcome-history")
    history.add_argument("--data-dir", default=None)
    incomplete = sub.add_parser("incomplete-drafts")
    incomplete.add_argument("--data-dir", default=None)
    reextract = sub.add_parser("reextract-welcome")
    reextract.add_argument("--data-dir", default=None)
    reextract.add_argument("--target-id", required=True)
    reextract.add_argument("--client-event-id", required=True)
    reextract.add_argument("--per-request-credits", type=int, default=MANAGED_CREDITS)
    add_arguments(reextract)
    credits = sub.add_parser("credit-status")
    credits.add_argument("--data-dir", default=None)
    raise_cap = sub.add_parser("raise-lifetime-cap")
    raise_cap.add_argument("--data-dir", default=None)
    raise_cap.add_argument("--new-cap", type=int, required=True)
    raise_cap.add_argument("--operator", required=True)
    raise_cap.add_argument("--note", required=True)


WELCOME_COMMANDS = frozenset(
    {
        "init-welcome-catalog",
        "publish-welcome",
        "rollback-welcome",
        "welcome-history",
        "incomplete-drafts",
        "reextract-welcome",
        "credit-status",
        "raise-lifetime-cap",
    }
)


class _NoNetwork:
    """Re-extraction never fetches: any attempt to is refused."""

    async def scrape(self, request: Any) -> dict[str, Any]:
        raise RuntimeError("re-extraction must not make a network request")


def _seeds_dir(args: argparse.Namespace) -> Path:
    from core.db import SEEDS_DIR

    return Path(args.seeds_dir) if getattr(args, "seeds_dir", None) else SEEDS_DIR


def run_welcome_command(
    args: argparse.Namespace,
    *,
    data_dir: Path,
    store: FinancialIngestionStore,
    artifacts: ContentAddressedStore,
    now: Callable[[], datetime],
) -> int:
    def say(payload: object) -> None:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))

    try:
        if args.command == "init-welcome-catalog":
            say({"catalog": str(init_catalog(Path(args.catalog_dir)))})
            return 0
        if args.command in {"publish-welcome", "rollback-welcome"}:
            publisher = WelcomePublisher(
                store=store,
                artifacts=artifacts,
                catalog_dir=Path(args.catalog_dir),
                state_dir=data_dir / "welcome_publisher",
                now=now,
            )
            if args.command == "publish-welcome":
                say(publisher.publish(args.proposal_id).to_dict())
            else:
                say(publisher.rollback(args.publication_id).to_dict())
            return 0
        if args.command == "welcome-history":
            say(store.list_publication_events())
            return 0
        if args.command == "incomplete-drafts":
            say(store.list_incomplete_extractions())
            return 0
        if args.command == "reextract-welcome":
            from ingestion.acquisition import DurableAcquisitionService

            wiring = build_welcome_wiring(args, seeds_dir=_seeds_dir(args))
            service = DurableAcquisitionService(
                store=store,
                artifacts=artifacts,
                control=DurableAcquisitionControl(store, limits=control_limits(args, managed=True)),
                transport=_NoNetwork(),
                extraction_configs_by_target=wiring.ext_by_target,
                welcome_targets=wiring.targets,
                published_welcome_rows=wiring.published_rows,
                now=now,
            )
            outcome = service.reextract_welcome_sync(
                args.target_id, client_event_id=args.client_event_id
            )
            say(outcome.to_dict())
            return 0 if outcome.state == "completed" else 2
        control = DurableAcquisitionControl(
            store,
            limits=AcquisitionControlLimits(
                per_request_credits=0,
                per_run_credits=0,
                per_month_credits=0,
                pricing_version="status-only",
            ),
        )
        if args.command == "credit-status":
            status = control.lifetime_status()
            say(status if status is not None else {"lifetime_cap": None})
            return 0
        control.raise_lifetime_cap(args.new_cap, operator=args.operator, note=args.note)
        say(control.lifetime_status())
        return 0
    except PublicationRefused as refused:
        print(f"refused: {refused.code}: {refused}", file=sys.stderr)
        return 2
    except ValueError as invalid:
        print(f"refused: invalid input: {invalid}", file=sys.stderr)
        return 2


# --------------------------------------------------------------------------- scheduled run


def add_recurring_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--slot",
        default=None,
        help="stable name for this scheduled slot (default: the UTC hour). A repeated slot "
        "replays stored results and spends nothing",
    )


def run_recurring(
    args: argparse.Namespace,
    *,
    data_dir: Path,
    refresh_due: Callable[[argparse.Namespace], int],
    now: Callable[[], datetime],
) -> int:
    """One locked, bounded, repeatable pass. Safe to start from cron, launchd or CI.

    The slot name makes the pass idempotent: a scheduler that fires twice for the same slot (a
    retry, an overlap, a restart) replays the stored outcomes and spends no credits, because the
    acquisition control keys every request by it.
    """
    started = now()
    slot = args.slot or started.strftime("%Y%m%dT%H")
    args.client_event_prefix = f"recurring-{slot}"
    run_dir = data_dir / "recurring"
    run_dir.mkdir(parents=True, exist_ok=True)
    lock = (run_dir / "run.lock").open("w")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("busy: another recurring run holds the lock", file=sys.stderr)
        lock.close()
        return BUSY_EXIT_CODE
    try:
        summary: dict[str, Any] = {
            "slot": slot,
            "started_at": started.isoformat(),
            "client_event_prefix": args.client_event_prefix,
            "limit": args.limit,
        }
        code = refresh_due(args)
        summary.update({"exit_code": code, "finished_at": now().isoformat()})
        (run_dir / "last_run.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        with (run_dir / "history.jsonl").open("a", encoding="utf-8") as history:
            history.write(json.dumps(summary, sort_keys=True) + "\n")
        return code
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
