# HANDOFF — card-bank Phases 2–4 session (rolling checkpoint)

Contains no credentials and no captured document text. Update at each checkpoint.

## Where things are

- Repo `hjain3004/TripPlanner`; cloud checkout `/home/user/TripPlanner` (worktrees `/home/user/tp-b`, `/home/user/tp-c`).
- Pilot base: `claude/fi3-real-capture-pilot` — PR #22.
- A `codex/card-bank-phase2` — PR #23 → targets the pilot branch.
- B `codex/card-bank-insert-proposals` — PR #24 → targets A.
- C `codex/card-bank-controlled-apply` — PR #25 → targets B.
- None of the PRs is independently mergeable; merge in order #22, #23, #24, #25, retargeting each.

## Status

| Milestone | State |
|---|---|
| A stage-capture + loaders | reviewed, fixed, gate-equivalent passed (`4a24fe3`) |
| B insert proposals | reviewed, fixed, gate-equivalent passed (`987b258`: 2988 passed, 28 skipped) |
| C controlled apply/rollback (scratch seeds only) | reviewed, fixed, gate-equivalent passed (`c2a3d6c`: 3060 passed, 28 skipped) |

## Resume

1. Read `AGENTS.md`/`CLAUDE.md`, `DEVIATIONS.md` (sections "Card-bank Phase 2/3/4"), then the three reports `reports/card_bank_*.md`.
2. Demos: `python -m evals.card_bank_apply_demo` (C); the B flow is `evals/test_card_bank_insert_cli.py`; A is `evals/test_card_bank_cli.py`.
3. Backend suite needs the seeded KB first: `make seed PY=<venv python>` at the repo root. The original cloud runs lacked the regional catalogs and were gate-equivalent only. Laptop catalog-backed evidence is now in `reports/card_bank_controlled_apply.md`; the final committed-tree gate result and current CI status are recorded on PR #25. Do not report a catalog-less run as `make gate`.
4. Local-only inputs not available here: the real HDFC capture, pilot database and original staging script (laptop). Real-document demonstrations are therefore pending.

## Hard limits that still apply

No real seed change, no real financial fact applied, no credentials, paid services, live crawling or live model calls, no deployment, bookings or transfers. Do not merge PRs without the owner.

## Outstanding failures

None recorded.

## Laptop acceptance checkpoint (2026-11-04)

- Combined code checked: `f7e26028013cee11ed0c6dbf2418ff2e60e0a28b`; all six regional catalogs validated.
- Full catalog-required pytest phase: 3055 passed, 53 skipped (52 optional-PDF checks plus CP1 merge-base guard), zero catalog skips.
- An initial gate stopped on old shared PyYAML stubs. A private environment using the lockfile-pinned check tools resolves that mismatch without a source change; all strict typing and zero-tolerance lint scopes then pass. See the report for versions and measured evidence.
- Actual CLI staging/configuration, insert/collision, and scratch apply/rollback/recovery demonstrations passed. No real seed or fact was applied.
- No PR has been merged or retargeted. Owner merge order remains #22, #23, #24, #25, retargeting each next PR only after its parent lands.
- Final committed-tree `make gate` status is maintained in PR #25; do not infer its result from the earlier cloud counts or pre-write it here.
