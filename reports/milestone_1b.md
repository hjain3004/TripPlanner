# Milestone 1b - deterministic transfer pathfinder

**Date:** 2026-07-24
**Status:** PASS

## Gate

- [x] Canonical LionMiles worked example recommends `REDEEM(lion-award:E1)`.
- [x] Canonical example computes 124,000 source points, INR 18,000 fees, 1,387,096 micro-major value per point, INR 142,000 effective redemption cost, and INR 48,000 savings.
- [x] SkyOrchid worked example is infeasible with an 85,000-point `voyager-prime` shortfall.
- [x] Increment rounding, existing destination balances, active/expired bonuses, zero-transfer, minimum-transfer, margin gate, `NO_DATA`, dominated two-hop retention, and foreign-fee FX conversion are covered.
- [x] Transfer advice serializes byte-identically across repeated runs.
- [x] Checklist step 1 is the blocking verify-before-transfer instruction.
- [x] Fictional seed facts carry provenance and `needs_verification: true`.
- [x] No provider, MCP, network, LLM, booking, payment, or transfer execution path was added.
- [x] `mypy --strict core/` is clean.

## Test summary

- `make gate-m1 PY=.venv/bin/python`: PASS
  - Optimizer selection: `12 passed, 28 deselected in 0.37s`
  - Determinism selection: `5 passed, 35 deselected in 0.42s`
  - Strict type check: `Success: no issues found in 16 source files`
  - Canonical demo diff: no output, exit code 0
  - Float audit reviewed
- `make gate-m1b PY=.venv/bin/python`: PASS
  - Transfer suite: `20 passed in 0.32s`
  - Strict type check: `Success: no issues found in 16 source files`
- Full regression from `backend/`: `40 passed in 0.67s`
- Seed command: `Seeded ... (42 rows)`, including 3 loyalty programs, 4 transfer edges, 1 transfer bonus, and 2 award chart entries.

## Spec-07 cases

- Worked example: PASS
- Increment rounding: PASS
- Existing destination balance: PASS
- Bonus inside validity window: PASS
- Bonus outside validity window: PASS
- Zero-transfer behavior: PASS
- Minimum-transfer behavior: PASS
- 1.15 margin gate: PASS
- `NO_DATA` route: PASS
- Dominated two-hop plan retained and marked: PASS
- Foreign-currency fee conversion: PASS
- Byte determinism: PASS

## Unit audit

Spec 07's prose formula uses a `1_000_000` divisor/multiplier, but the worked example and existing unit model require conversion between minor units and micro-major units by `10_000`.

Canonical hand audit:

```text
value_per_point_micro = (19_000_000 - 1_800_000) * 10_000 // 124_000 = 1_387_096
opportunity_cost_minor = 124_000 * 1_000_000 // 10_000 = 12_400_000
effective_redemption_cost_minor = 1_800_000 + 12_400_000 = 14_200_000
savings_vs_cash_minor = 19_000_000 - 14_200_000 = 4_800_000
```

Golden values were not changed.

## Float audit

Reviewed command:

```bash
grep -rn "float" backend/core/transfer backend/core/models.py
```

Findings:

- No matches in `backend/core/transfer`.
- `backend/core/models.py` matches are docstrings, provenance/report confidence, and geo fields (`lat`, `lon`, `centrality_score`), not money, points, ratios, percentages, valuations, fees, or FX arithmetic.

## Deviations

See `DEVIATIONS.md` M1b rows:

- `AwardTarget.home_currency` default for deterministic FX conversion.
- Spec-07 prose unit correction using the worked example's dimensional arithmetic.

## Next milestone

M2 is next: pipeline and FastAPI integration. Provider/MCP work remains deferred.
