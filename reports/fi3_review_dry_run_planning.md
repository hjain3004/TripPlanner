# FI3 — Human Review and Activation Dry-Run: Planning Report

**Status:** planning complete; documentation only. FI3 implementation has not started.
**Date:** 2026-10-26
**Branch:** `codex/fi3-review-dry-run-plan`
**Base:** `c925d98077dd94a1f24d7c312243bfcee78f2d3c` (FI2). This is `origin/main` `6428b78`
plus six FI2 commits, and it is not yet an ancestor of `origin/main`. The plan is provisional
against it.

## Deliverables

| Document | Purpose |
|---|---|
| [`docs/superpowers/specs/2026-10-26-fi3-review-activation-dry-run-design.md`](../docs/superpowers/specs/2026-10-26-fi3-review-activation-dry-run-design.md) | Design: boundary, identity, review context, decisions, bundles, threat matrix, open decisions, recheck list |
| [`docs/superpowers/plans/2026-10-26-fi3-review-activation-dry-run.md`](../docs/superpowers/plans/2026-10-26-fi3-review-activation-dry-run.md) | Test-first plan: Task 0 recheck plus 9 tasks, with interfaces and named tests |
| `DEVIATIONS.md` | Three Tier-C planning entries under "FI3 — Review and activation dry-run planning" |

## What was read

- `AGENTS.md`/`CLAUDE.md` (identical) and the `DEVIATIONS.md` sections for FI0, FI1, and FI2.
- The FI0, FI1, and FI2 reports.
- Specs 05, 06, and 12 (§§1, 5–8), plus the outline of spec 17.
- The robust ingestion plan.
- All of `backend/ingestion/` (contracts, storage, migrations, validation, evidence, extraction,
  parsing, artifacts, snapshots, fetch), `api/auth.py`, the wiring in `api/main.py`,
  `core/db.py`, `core/models.Provenance`, the gate in `Makefile`,
  `scripts/check-contract-drift.sh`, `evals/test_contract_one_pr.py`, the FI0 boundary test,
  `deploy/` entry points, and the golden YAML structure.

## Key findings that shaped the plan

Reproduced on `c925d98` with a scratch script; no repository file was changed.

1. A second decision on an `edited` proposal raises a raw `sqlite3.IntegrityError`: the status
   check allows it, but `UNIQUE(proposal_id)` forbids it.
2. `decide_proposal(status=EDITED)` stores arbitrary, unevidenced, unparsed edits.
3. Default generated IDs restart per process and are reused across restarts. A colliding
   decision ID raises a raw `IntegrityError`. The audit retry loop is unbounded.
4. FI2 proposals may carry `current_row_hash=None`, which skips the stale-row check.
5. Reverify tasks are not atomic with their decision.
6. Evidence verification for PDFs still parses in-process; another branch is fixing this.

FI3 closes 1, 3, and 5 in storage (Task 1). It closes 2 and 4 in the review service and the
bundle builder (Tasks 3–5). It consumes 6 only through an injectable verifier.

## Contract boundary decision

The curator surface is a separate, loopback-only FastAPI app inside `backend/ingestion/`:
- it is never mounted on `api.main:app`, deployed, or proxied;
- its server HTML has no JavaScript;
- it has its own committed schema snapshot and an exact route allowlist;
- a test proves the product OpenAPI has no `/review` path.

This keeps `contract/openapi.json` and `frontend/` unchanged without silently bypassing spec 12.
It is recorded in `DEVIATIONS.md` and listed as open decision D5.

## Dependencies

- **New runtime or dev dependencies: none.** FI3 uses existing FastAPI/Starlette, uvicorn,
  Pydantic, and PyYAML, plus the stdlib. Templating is stdlib `html.escape`; forms use
  `urllib.parse.parse_qs` (no Jinja2, no `python-multipart`).
- **Milestone dependencies:** FI0–FI2 as integrated by Luna. Task 0 rechecks the interfaces in
  design §12 before any code is written.

## Open decisions (design §11)

| ID | Decision | FI3 default |
|---|---|---|
| D1 | Row-level provenance versus field-level evidence | Spec 05 literal, plus `unevidenced_fields` in each entry |
| D2 | Promoting manual captures to official provenance | No |
| D3 | Curator identity strength | Local shell plus a per-launch token |
| D4 | Supported tables | `cards`, `reward_rules`, `offers`, `point_valuations` only |
| D5 | Operator surface outside `contract/openapi.json` | Separate app |
| D7 | Approval expiry | None |
| D10 | Requiring the raw value inside the quote for FI2 extraction | Edits only |

D1 and D2 must be decided by a human before any apply step (FI5). FI3 itself never applies.

## Recommended bounded implementation sequence

| Order | Task | Can review independently |
|---|---|---|
| 0 | Recheck the FI2 interfaces at the integration commit; baseline `make gate` | — |
| 1 | Schema 3 and decision hardening (storage only) | Yes |
| 2 | Read-only seed rows and canonical row hash | Yes |
| 3 | Review context and computed findings | Yes |
| 4 | Decisions and validated edits | Yes |
| 5 | Activation bundles and in-memory dry-run | Yes |
| 6 | Escaped HTML rendering | Yes |
| 7 | Loopback app: sessions, CSRF, routes | Yes |
| 8 | Server CLI and local-only guards | Yes |
| 9 | Boundaries, end-to-end acceptance, operator schema snapshot, `make gate`, independent review, report | — |

Tasks 1–5 deliver a usable, fully tested review and dry-run core without any HTTP surface. Tasks
6–8 add the local UI. Stopping after Task 5 is a valid bounded checkpoint.

## Verification of this planning change

- Relative links in the three new or changed documents: checked by script (see the hand-off).
- The diff against `c925d98` contains only the two new documents, this report, and the
  `DEVIATIONS.md` append.
- No application code, test, dependency, spec, OpenAPI, frontend, seed, golden,
  `AGENTS.md`/`CLAUDE.md`, or other worktree was modified. No live service, credential, OAuth,
  crawl, model call, spending, or deployment occurred. Nothing was pushed.
