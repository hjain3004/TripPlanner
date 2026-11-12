"""Integer spend accounting and the durable reservation ledger for paid model calls.

Design: docs/superpowers/specs/2026-11-11-runtime-llm-design.md section 7. All amounts are
integer micro-USD computed in Python; none of this reaches the kernel's money arithmetic.

A dispatch reserves its worst-case cost *before* the request is sent, in a transaction that also
checks every cap, so a crash or a concurrent process cannot spend the same allowance twice. The
reservation is then settled with real usage, released when the provider confirms the request was
not processed, or kept as ``uncertain`` (charged in full) when nobody can tell.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from agents.llm import LLMBudgetExceeded

SCHEMA_VERSION = 1
# Message framing and the structured-output system prompt are added by the provider, not by the
# strings the caller passes; this is a deliberately generous allowance for them.
FRAMING_TOKENS = 2048
_MICRO = 1_000_000

PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing"


@dataclass(frozen=True)
class ModelPrice:
    """Integer micro-USD per million tokens, with provenance (non-negotiable 3)."""

    model: str
    input_micro_usd_per_mtok: int
    output_micro_usd_per_mtok: int
    cache_write_5m_micro_usd_per_mtok: int
    cache_read_micro_usd_per_mtok: int
    source_url: str
    last_verified: date
    verified_by: str
    needs_verification: bool
    long_prompt_threshold_tokens: int | None = None
    long_input_micro_usd_per_mtok: int | None = None
    long_output_micro_usd_per_mtok: int | None = None
    long_cache_write_5m_micro_usd_per_mtok: int | None = None
    long_cache_read_micro_usd_per_mtok: int | None = None


def _price(
    model: str,
    input_: int,
    output: int,
    cache_read: int,
    *,
    long_threshold: int | None = None,
    long_input: int | None = None,
    long_output: int | None = None,
    long_cache_read: int | None = None,
) -> ModelPrice:
    return ModelPrice(
        model=model,
        input_micro_usd_per_mtok=input_,
        output_micro_usd_per_mtok=output,
        cache_write_5m_micro_usd_per_mtok=input_ * 125 // 100,
        cache_read_micro_usd_per_mtok=cache_read,
        source_url=PRICING_URL,
        last_verified=date(2026, 11, 11),
        verified_by="docs-read:2026-11-11 (not owner-verified)",
        needs_verification=True,
        long_prompt_threshold_tokens=long_threshold,
        long_input_micro_usd_per_mtok=long_input,
        long_output_micro_usd_per_mtok=long_output,
        long_cache_write_5m_micro_usd_per_mtok=(
            long_input * 125 // 100 if long_input is not None else None
        ),
        long_cache_read_micro_usd_per_mtok=long_cache_read,
    )


# Read from the official pricing page on 2026-11-11. The owner's deployment-day check re-reads it
# and flips needs_verification; until then these rows say so.
PRICE_TABLE: Mapping[str, ModelPrice] = {
    "claude-opus-5-5": _price("claude-opus-5-5", 4_000_000, 20_000_000, 200_000),
    "claude-sonnet-5-5": _price("claude-sonnet-5-5", 2_000_000, 10_000_000, 100_000),
    "claude-haiku-5-5": _price(
        "claude-haiku-5-5",
        100_000,
        500_000,
        10_000,
        long_threshold=100_000,
        long_input=500_000,
        long_output=2_500_000,
        long_cache_read=50_000,
    ),
}


def price_for(model: str) -> ModelPrice:
    """An unknown model fails closed: its cost cannot be bounded."""
    try:
        return PRICE_TABLE[model]
    except KeyError:
        raise LLMBudgetExceeded(
            f"no price row for model {model!r}; refusing to dispatch", scope="unknown_model"
        ) from None


@dataclass(frozen=True)
class UsageCounts:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens


def input_token_upper_bound(*, system: str, user: str, wire_schema_json: str) -> int:
    """Tokens are formed from UTF-8 bytes, so a token covers at least one byte and the token
    count never exceeds the byte count. FRAMING_TOKENS covers what the request adds that is not
    in these strings."""
    return (
        len(system.encode("utf-8"))
        + len(user.encode("utf-8"))
        + len(wire_schema_json.encode("utf-8"))
        + FRAMING_TOKENS
    )


def _ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def _rates(price: ModelPrice, input_tokens: int) -> tuple[int, int, int, int]:
    """(input, output, cache_write_5m, cache_read) micro-USD per MTok for this prompt size."""
    threshold = price.long_prompt_threshold_tokens
    if threshold is not None and input_tokens > threshold:
        assert price.long_input_micro_usd_per_mtok is not None
        assert price.long_output_micro_usd_per_mtok is not None
        assert price.long_cache_write_5m_micro_usd_per_mtok is not None
        assert price.long_cache_read_micro_usd_per_mtok is not None
        return (
            price.long_input_micro_usd_per_mtok,
            price.long_output_micro_usd_per_mtok,
            price.long_cache_write_5m_micro_usd_per_mtok,
            price.long_cache_read_micro_usd_per_mtok,
        )
    return (
        price.input_micro_usd_per_mtok,
        price.output_micro_usd_per_mtok,
        price.cache_write_5m_micro_usd_per_mtok,
        price.cache_read_micro_usd_per_mtok,
    )


def reservation_micro_usd(price: ModelPrice, *, input_upper: int, max_tokens: int) -> int:
    """Worst case for one request: every input byte billed as a token, and max_tokens of output.

    max_tokens bounds all output including thinking. No cache_control is ever sent, so no cache
    write is reserved; a provider that reports cache usage anyway settles above the reservation
    and trips the underestimate breaker.
    """
    if input_upper < 0 or max_tokens <= 0:
        raise ValueError("input_upper must be >= 0 and max_tokens > 0")
    rate_in, rate_out, _, _ = _rates(price, input_upper)
    return max(1, _ceil_div(input_upper * rate_in + max_tokens * rate_out, _MICRO))


def settled_micro_usd(price: ModelPrice, usage: UsageCounts) -> int:
    rate_in, rate_out, rate_cache_write, rate_cache_read = _rates(price, usage.total_input_tokens)
    total = (
        usage.input_tokens * rate_in
        + usage.cache_creation_input_tokens * rate_cache_write
        + usage.cache_read_input_tokens * rate_cache_read
        + usage.output_tokens * rate_out
    )
    return _ceil_div(total, _MICRO)


_CAP_ENV_NAMES = {
    "per_plan_micro_usd": "TRIPWISE_LLM_CAP_PER_PLAN_MICRO_USD",
    "per_day_micro_usd": "TRIPWISE_LLM_CAP_PER_DAY_MICRO_USD",
    "per_month_micro_usd": "TRIPWISE_LLM_CAP_PER_MONTH_MICRO_USD",
    "paid_plans_per_user_per_day": "TRIPWISE_LLM_PAID_PLANS_PER_USER_PER_DAY",
}


@dataclass(frozen=True)
class SpendCaps:
    per_plan_micro_usd: int
    per_day_micro_usd: int
    per_month_micro_usd: int
    paid_plans_per_user_per_day: int

    def __post_init__(self) -> None:
        for name in _CAP_ENV_NAMES:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> SpendCaps:
        values: dict[str, int] = {}
        for field, name in _CAP_ENV_NAMES.items():
            raw = env.get(name, "").strip()
            if not raw.isdigit() or int(raw) <= 0:
                raise ValueError(f"{name} must be set to a positive integer")
            values[field] = int(raw)
        return cls(**values)


_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS reservations (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    user_id TEXT,
    node TEXT NOT NULL,
    model TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    reserved_micro_usd INTEGER NOT NULL CHECK (reserved_micro_usd > 0),
    settled_micro_usd INTEGER,
    state TEXT NOT NULL CHECK (state IN ('reserved','settled','released','uncertain')),
    created_at TEXT NOT NULL,
    settled_at TEXT,
    usage_json TEXT
);
CREATE INDEX IF NOT EXISTS reservations_plan ON reservations (plan_id);
CREATE INDEX IF NOT EXISTS reservations_created ON reservations (created_at);
CREATE TABLE IF NOT EXISTS breakers (
    scope TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    opened_at TEXT NOT NULL
);
"""

_COMMITTED = (
    "COALESCE(SUM(CASE WHEN state='settled' THEN settled_micro_usd "
    "WHEN state IN ('reserved','uncertain') THEN reserved_micro_usd ELSE 0 END), 0)"
)


class LLMSpendLedger:
    def __init__(
        self,
        path: Path,
        caps: SpendCaps,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.path = path
        self.caps = caps
        self._now = now
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            conn.executescript(_DDL)
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            elif row[0] != SCHEMA_VERSION:
                raise RuntimeError(f"unsupported llm_spend schema version {row[0]}")
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")
        finally:
            conn.close()

    def _stamp(self) -> str:
        return self._now().astimezone(UTC).isoformat()

    def reserve(
        self,
        *,
        plan_id: str,
        user_id: str | None,
        node: str,
        model: str,
        amount_micro_usd: int,
    ) -> str:
        if amount_micro_usd <= 0:
            raise ValueError("amount_micro_usd must be positive")
        stamp = self._stamp()
        day, month = stamp[:10], stamp[:7]
        with self._tx() as db:
            breaker = db.execute("SELECT scope FROM breakers ORDER BY scope LIMIT 1").fetchone()
            if breaker is not None:
                raise LLMBudgetExceeded(
                    f"spend breaker {breaker[0]!r} is open", scope=str(breaker[0])
                )

            def committed(where: str, arg: str) -> int:
                row = db.execute(
                    f"SELECT {_COMMITTED} FROM reservations WHERE {where}", (arg,)
                ).fetchone()
                return int(row[0])

            if committed("plan_id=?", plan_id) + amount_micro_usd > self.caps.per_plan_micro_usd:
                raise LLMBudgetExceeded("per-plan spend cap reached", scope="per_plan")
            if (
                committed("substr(created_at,1,10)=?", day) + amount_micro_usd
                > self.caps.per_day_micro_usd
            ):
                raise LLMBudgetExceeded("daily spend cap reached", scope="per_day")
            if (
                committed("substr(created_at,1,7)=?", month) + amount_micro_usd
                > self.caps.per_month_micro_usd
            ):
                raise LLMBudgetExceeded("monthly spend cap reached", scope="per_month")
            if user_id is not None:
                known = db.execute(
                    "SELECT 1 FROM reservations WHERE plan_id=? AND user_id=? "
                    "AND substr(created_at,1,10)=? AND state != 'released' LIMIT 1",
                    (plan_id, user_id, day),
                ).fetchone()
                if known is None:
                    plans_today = int(
                        db.execute(
                            "SELECT COUNT(DISTINCT plan_id) FROM reservations WHERE user_id=? "
                            "AND substr(created_at,1,10)=? AND state != 'released'",
                            (user_id, day),
                        ).fetchone()[0]
                    )
                    if plans_today >= self.caps.paid_plans_per_user_per_day:
                        raise LLMBudgetExceeded(
                            "daily paid-plan limit for this account reached",
                            scope="plans_per_user_per_day",
                        )
            attempt = int(
                db.execute(
                    "SELECT COUNT(*) FROM reservations WHERE plan_id=? AND node=?",
                    (plan_id, node),
                ).fetchone()[0]
            )
            reservation_id = uuid.uuid4().hex
            db.execute(
                "INSERT INTO reservations (id, plan_id, user_id, node, model, attempt, "
                "reserved_micro_usd, state, created_at) VALUES (?,?,?,?,?,?,?,'reserved',?)",
                (reservation_id, plan_id, user_id, node, model, attempt, amount_micro_usd, stamp),
            )
            return reservation_id

    def settle(self, reservation_id: str, usage: UsageCounts, amount_micro_usd: int) -> None:
        """Record actual usage. A charge above its reservation is stored as spent, and the
        underestimate opens a breaker so no further dispatch happens until an operator looks."""
        if amount_micro_usd < 0:
            raise ValueError("amount_micro_usd cannot be negative")
        usage_json = json.dumps(
            {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                "cache_read_input_tokens": usage.cache_read_input_tokens,
            },
            sort_keys=True,
        )
        with self._tx() as db:
            row = db.execute(
                "SELECT state, reserved_micro_usd FROM reservations WHERE id=?",
                (reservation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(reservation_id)
            if row[0] not in ("reserved", "uncertain"):
                raise ValueError(f"reservation {reservation_id} is already {row[0]}")
            db.execute(
                "UPDATE reservations SET state='settled', settled_micro_usd=?, settled_at=?, "
                "usage_json=? WHERE id=?",
                (amount_micro_usd, self._stamp(), usage_json, reservation_id),
            )
            if amount_micro_usd > int(row[1]):
                self._open_breaker_in(db, "reservation_underestimated", reservation_id)

    def _transition(self, reservation_id: str, new_state: str) -> None:
        with self._tx() as db:
            row = db.execute(
                "SELECT state FROM reservations WHERE id=?", (reservation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(reservation_id)
            if row[0] != "reserved":
                raise ValueError(f"reservation {reservation_id} is already {row[0]}")
            db.execute(
                "UPDATE reservations SET state=?, settled_at=? WHERE id=?",
                (new_state, self._stamp(), reservation_id),
            )

    def release(self, reservation_id: str) -> None:
        """The provider confirmed the request was not processed, so nothing was billed."""
        self._transition(reservation_id, "released")

    def mark_uncertain(self, reservation_id: str) -> None:
        """Nobody knows whether the request was billed: it stays charged in full."""
        self._transition(reservation_id, "uncertain")

    def recover_stale(self, *, older_than: timedelta) -> int:
        cutoff = (self._now().astimezone(UTC) - older_than).isoformat()
        with self._tx() as db:
            cursor = db.execute(
                "UPDATE reservations SET state='uncertain', settled_at=? "
                "WHERE state='reserved' AND created_at < ?",
                (self._stamp(), cutoff),
            )
            return int(cursor.rowcount)

    def _open_breaker_in(self, db: sqlite3.Connection, scope: str, reason: str) -> None:
        db.execute(
            "INSERT OR IGNORE INTO breakers (scope, reason, opened_at) VALUES (?,?,?)",
            (scope, reason[:200], self._stamp()),
        )

    def open_breaker(self, scope: str, reason: str) -> None:
        with self._tx() as db:
            self._open_breaker_in(db, scope, reason)

    def open_breakers(self) -> dict[str, str]:
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            return dict(conn.execute("SELECT scope, reason FROM breakers").fetchall())
        finally:
            conn.close()

    def reset_breaker(self, scope: str, *, operator: str) -> None:
        """Operator CLI only; nothing at request time calls this."""
        if not operator.strip():
            raise ValueError("an operator name is required to reset a breaker")
        with self._tx() as db:
            db.execute("DELETE FROM breakers WHERE scope=?", (scope,))

    def plan_committed_micro_usd(self, plan_id: str) -> int:
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            row = conn.execute(
                f"SELECT {_COMMITTED} FROM reservations WHERE plan_id=?", (plan_id,)
            ).fetchone()
            return int(row[0])
        finally:
            conn.close()


def main(argv: list[str] | None = None) -> int:
    """``python -m agents.llm_budget --db PATH breakers|reset-breaker`` for the operator."""
    parser = argparse.ArgumentParser(prog="agents.llm_budget")
    parser.add_argument("--db", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("breakers")
    reset = sub.add_parser("reset-breaker")
    reset.add_argument("--scope", required=True)
    reset.add_argument("--operator", required=True)
    args = parser.parse_args(argv)
    ledger = LLMSpendLedger(args.db, SpendCaps(1, 1, 1, 1))  # caps are unused by these commands
    if args.command == "breakers":
        for scope, reason in sorted(ledger.open_breakers().items()):
            print(f"{scope}\t{reason}")
        return 0
    ledger.reset_breaker(args.scope, operator=args.operator)
    print(f"breaker {args.scope!r} reset by {args.operator}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
