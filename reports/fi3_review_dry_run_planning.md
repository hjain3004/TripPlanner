# FI3 — Human Review and Activation Dry-Run: Planning Report

**Status:** planning only; FI3 is not implemented.
**Branch:** `codex/fi3-review-dry-run-plan`.
**Checked against:** `main` at `6f0859b146f69d0a6f55e3a3c9ac1146353f455e` (PR #20, FI2 parser and
PDF hardening, on top of PR #19 `3471747`).
**Revisions:** the first revision (2026-10-26, commit `664de1f`) was written against `c925d98`;
this revision (2026-10-29) corrects it against current `main`.

## Deliverables

| Document | Purpose |
|---|---|
| [Design](../docs/superpowers/specs/2026-10-26-fi3-review-activation-dry-run-design.md) | Outcome, boundary, review context, decisions, bundle, requirement → test map, decisions |
| [Plan](../docs/superpowers/plans/2026-10-26-fi3-review-activation-dry-run.md) | Task 0 plus Tasks 1–9; Checkpoint A (CLI workflow, Tasks 1–6) before Checkpoint B (loopback UI, Tasks 7–9) |

## Target outcome

A named local curator:
1. opens a real stored FI2 proposal;
2. inspects its evidence, hashes, and lineage;
3. approves, edits, rejects, or re-verifies it;
4. reopens the durable result after a restart;
5. exports a deterministic activation dry-run.

Nothing is applied to the KB. This is an operator tool; travelers see no change. Demo proposals
come from the real FI2 path (manual upload → snapshot → extractor), driven by synthetic capture
text and a scripted extractor response, and are labelled as such.

## What changed since the first revision

| Earlier assumption | On `6f0859b` | Plan change |
|---|---|---|
| FI2 not on `main` | FI2 landed in PR #19, and its parser/PDF hardening in PR #20 | Reference is `main`; Task 0 only checks for further drift |
| FI3 takes schema 3 | `SCHEMA_VERSION = 3` is used by `change_proposals.request_fingerprint` | FI3 migration is **version 4** |
| Parser findings open | F1–F4 fixed: grouping validation, 24-digit bound, typed scaling errors, exact ISO dates, negatives rejected | No FI3 parser rules; edits rely on `parse_field_value` through `validate_extraction` |
| FI3 needs its own value-in-quote rule (D10) | `validate_extraction` now runs `_quote_supports_value` | Rule removed; D10 closed |
| Sanity rules | New blocking rules: `invalid_confidence`, `implausible_forex_markup`, `currency_country_mismatch`, `implausible_rate`. The real seed cards pass them. | Edits re-run them automatically |
| PDF verification in-process | A process-isolated runner: synchronous, 30 s default, 2 concurrent; failures become a generic `EvidenceVerificationError`; real `pdfplumber` never executed | `serve` runs `use_runner(PdfProcessRunner(default_timeout_seconds=10.0))`; one verification per span per request; an explicit `pdf_verification_unavailable` finding; tests use `fixtures/pdf_double` |
| A separate FI3 row-hash function | `validation._row_hash` is the canonical hash | One public alias, `canonical_row_hash`; no reimplementation |
| Proposal creation | `FinancialExtractor` now has request-fingerprint replay (`create_proposal_with_fingerprint`) | The demo staging goes through it |
| Bundle field `applicable`, and spec-05 provenance written into `new_row` | — | `activation_authorized: false` always. `new_row.provenance` is unchanged, `provenance_candidate.needs_verification` is `null`, and entries carry `blocked_by` D1/D2 and `unevidenced_fields`. |
| Process overhead | — | Removed: per-task fresh reviewers, a full gate after each task, the operator OpenAPI snapshot fixture. Kept: focused tests per task, `make gate` at each checkpoint, one independent review of the completed change. |

## Storage concerns: retained only where reproduced on `6f0859b`

Reproduced with a scratch script against an archive of `6f0859b` (FI0 fixtures; no repository file
changed):

| # | Observed |
|---|---|
| S1 | `decide_proposal(EDITED, edits={"annual_fee_minor": 1})` stores an unvalidated edit |
| S2 | Re-deciding an `edited` or `reverify` proposal raises a raw `sqlite3.IntegrityError` |
| S3 | After a reopen, the decision ID `audit-1` duplicated an audit event ID; a colliding decision ID raises a raw `IntegrityError` |
| S4 | `_audit` loops without bound under an ID factory that keeps colliding (injected-factory only; minor) |
| S5 | `put_reverify_task` is a separate transaction from the decision |
| S6 | `validate_extraction` skips the stale-row check when `current_row_hash is None` |

All six are addressed in Tasks 1, 3, 4, and 5. No other storage concern is carried forward.

## Remaining decisions

| ID | Decision | FI3 behavior while open |
|---|---|---|
| D1 | Row-level provenance versus field-level evidence | Not resolved; the bundle never upgrades trust and lists unevidenced fields |
| D2 | Promoting manual captures to official provenance | Not allowed; entries carry `blocked_by: ["D2"]` |
| D3 | Curator identity is local shell plus a one-time token | Human acknowledgement requested |
| D4 | Supported tables | Cards, reward rules, offers, point valuations only |

D1 and D2 must be decided before any apply step (FI5). FI3 does not need either answer.

## Dependencies and limits

- **No new packages.**
- **Real `pdfplumber` is not installed, and has never been executed.** PDF proposals are
  verifiable only once the `ingestion-local` extra is installed. Until then they show a blocking
  `pdf_verification_unavailable` finding. This does not block FI3, which works fully for
  text/HTML captures.
- **Not unblocked by FI3:**
  - FI1's live-crawl blockers: durable cross-process throttling, a response-byte bound, and DNS
    pinning;
  - any KB apply step.

## Verification of this revision

- Every relative link in the three documents resolves (scripted check; result in the hand-off).
- The diff touches only the design, the plan, and this report.
- No application code, test, dependency, spec, OpenAPI, frontend, seed, golden, or other worktree
  was modified.
- No live service, credential, crawl, model call, spending, deployment, or push occurred.
