# HANDOFF — card-bank Phase 2 session (rolling checkpoint)

Update this file at each checkpoint. It contains no credentials and no captured document text.

## Where things are

- Repo: `hjain3004/TripPlanner`. Cloud checkout: `/home/user/TripPlanner`.
- Base: `origin/claude/fi3-real-capture-pilot` @ `3ea31e96488aad350e7377bd020707441ed59d24` (not yet merged to `main`; `main` is `8d805e3`). PR for it: **#22** (CI passed on `3ea31e9`).
- Milestone A branch: `codex/card-bank-phase2` (this file's branch).
- Milestone B branch (not started): `codex/card-bank-insert-proposals`, stacked on A.
- Milestone C branch (not started): `codex/card-bank-controlled-apply`, stacked on B.

## Status

| Milestone | State |
|---|---|
| A — stage-capture + loaders | implemented and demonstrated locally; focused tests pass; gate-equivalent, review, report and commit **pending** |
| B — new-row insert proposals | not started |
| C — controlled apply and rollback (scratch seeds) | not started |

## Required reading to resume

1. `AGENTS.md` / `CLAUDE.md`, `DEVIATIONS.md` (last section: "Card-bank Phase 2").
2. Plan: `git show origin/claude/card-data-bank-plan:docs/superpowers/plans/2026-10-31-indian-card-data-bank.md`.
3. Permissions: `git show origin/claude/card-source-permissions:reports/card_bank_source_permissions.md` (section 5A = owner decisions).
4. `reports/card_bank_phase2_capture_staging.md` (once written).

## Local-only files and environment

- `backend/.venv`: Python 3.14.6 from the hashed `requirements-dev.lock`, **plus** `pdfplumber 0.11.10` installed unhashed from PyPI per `pyproject.toml`'s `ingestion-local` range (task-owned venv; not in the lockfile).
- The regional catalogs are laptop-local and absent here, so `make gate` itself cannot pass in this cloud checkout (`TRIPWISE_REQUIRE_REGIONAL_CATALOGS=1` aborts the session by design). Equivalent steps are run with the guard unset and reported as such. See the last `DEVIATIONS.md` row.
- Scratch demo inputs are synthetic and live outside the repo (session scratchpad); they are not needed to resume.

## Exact next action

Milestone A: finish acceptance (full backend suite on the final tree, strict mypy, ruff, independent review, report), commit, push, open the PR into `main`... then start Milestone B on a new stacked branch.

## Outstanding failures

None recorded yet.
