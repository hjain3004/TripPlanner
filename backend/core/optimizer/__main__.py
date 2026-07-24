"""`python -m core.optimizer demo` — prints the spec 02 §8 worked example.

Output is deterministic and ASCII-only so it can be committed as a byte-exact
fixture (``evals/golden/demo_expected_output.txt``) and diffed by Gate M1.
"""

from __future__ import annotations

import sys

from core.models import OptimizerResult
from core.optimizer import optimize
from core.optimizer.demo_data import demo_kb, demo_trip, demo_wallet


def _rs(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    minor = abs(minor)
    return f"{sign}Rs{minor // 100:,}.{minor % 100:02d}"


def _pct(savings_minor: int, gross_minor: int) -> str:
    if gross_minor <= 0:
        return "0.00%"
    bp = (savings_minor * 10_000 + gross_minor // 2) // gross_minor  # nearest bp
    return f"{bp // 100}.{bp % 100:02d}%"


def render(result: OptimizerResult) -> str:
    lines: list[str] = []
    lines.append("Tripwise -- Rewards Optimizer")
    lines.append("Demo trip: DEL -> SIN (spec 02 section 8, fictional cards)")
    lines.append("=" * 78)
    header = (
        f"{'Line':<12} {'Card / channel / offers':<40} "
        f"{'Points':>7} {'Pts value':>11} {'Discount':>10} {'Forex':>9} {'Benefit':>11}"
    )
    lines.append(header)
    lines.append("-" * 78)
    for a in result.assignments:
        offers = "+".join(o.offer_id for o in a.offers_applied)
        combo = f"{a.card_id} / {a.channel.value}"
        if offers:
            combo += f" / {offers}"
        lines.append(
            f"{a.line.id:<12} {combo:<40} "
            f"{a.points_earned:>7} {_rs(a.points_value_minor):>11} "
            f"{_rs(_line_discount(a)):>10} {_rs(a.forex_fee_minor):>9} "
            f"{_rs(a.benefit_minor):>11}"
        )
    lines.append("-" * 78)
    savings = result.gross_minor - result.effective_cost_minor
    lines.append(f"Gross:            {_rs(result.gross_minor)}")
    lines.append(f"Instant discounts: {_rs(result.discounts_minor)}")
    lines.append(f"Rewards value:    {_rs(result.rewards_value_minor)}")
    lines.append(f"Forex fees:       {_rs(result.forex_fees_minor)}")
    lines.append(f"Effective cost:   {_rs(result.effective_cost_minor)}")
    lines.append(
        f"Savings:          {_rs(savings)} "
        f"({_pct(savings, result.gross_minor)}, savings_pct_bp={result.savings_pct_bp})"
    )
    lines.append(f"Cash outlay now:  {_rs(result.cash_outlay_now_minor)}")
    lines.append(f"Deferred value:   {_rs(result.deferred_value_minor)}")
    pools = ", ".join(f"{k}={v}" for k, v in sorted(result.cap_pools_final.items()))
    lines.append(f"Final cap pools:  {pools}")
    lines.append(f"Confidence:       {result.confidence:.2f}")
    return "\n".join(lines) + "\n"


def _line_discount(assignment: object) -> int:
    total = 0
    for offer in assignment.offers_applied:  # type: ignore[attr-defined]
        total += offer.discount_minor
    return total


def _main(argv: list[str]) -> int:
    if len(argv) >= 1 and argv[0] == "demo":
        result = optimize(demo_trip(), demo_wallet(), demo_kb())
        sys.stdout.write(render(result))
        return 0
    sys.stderr.write("usage: python -m core.optimizer demo\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
