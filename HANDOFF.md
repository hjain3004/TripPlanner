# HANDOFF — card-bank Phases 2–4 session (rolling checkpoint)

Contains no credentials and no captured document text. Update at each checkpoint.

## Where things are

- Repo `hjain3004/TripPlanner`; cloud checkout `/home/user/TripPlanner` (worktrees `/home/user/tp-b`, `/home/user/tp-c`).
- Pilot base: `claude/fi3-real-capture-pilot` — PR #22.
- A `codex/card-bank-phase2` — PR #23 → targets the pilot branch.
- B `codex/card-bank-insert-proposals` — PR #24 → targets A.
- C `codex/card-bank-controlled-apply` — stacked on B (PR: see the final report).
- None of the PRs is independently mergeable; merge in order #22, #23, #24, C, retargeting each.

## Status

| Milestone | State |
|---|---|
| A stage-capture + loaders | reviewed, fixed, gate-equivalent passed (`4a24fe3`) |
| B insert proposals | reviewed, fixed, gate-equivalent passed (`987b258`: 2988 passed, 28 skipped) |
| C controlled apply/rollback (scratch seeds only) | implemented; tests, demo, mutation checks done; independent review and gate-equivalent: see `reports/card_bank_controlled_apply.md` "Verification" |

## Resume

1. Read `AGENTS.md`/`CLAUDE.md`, `DEVIATIONS.md` (sections "Card-bank Phase 2/3/4"), then the three reports `reports/card_bank_*.md`.
2. Demos: `python -m evals.card_bank_apply_demo` (C); the B flow is `evals/test_card_bank_insert_cli.py`; A is `evals/test_card_bank_cli.py`.
3. Backend suite needs the seeded KB first: `make seed PY=<venv python>` at the repo root. `make gate` cannot pass in a cloud checkout (laptop-local regional catalogs); run the same steps with `TRIPWISE_REQUIRE_REGIONAL_CATALOGS` unset and say so.
4. Local-only inputs not available here: the real HDFC capture, pilot database and original staging script (laptop). Real-document demonstrations are therefore pending.

## Hard limits that still apply

No real seed change, no real financial fact applied, no credentials, paid services, live crawling or live model calls, no deployment, bookings or transfers. Do not merge PRs without the owner.

## Outstanding failures

None recorded.
