# FI2 parser and PDF hardening integration

**Status: offline correction complete; live financial crawling and parser activation remain pending.**

This branch started at `origin/main` `3471747457968b3d1b3ceb392576d010ec9caed7`, the
normal merge of FI2/G3b/Instagram PR #19. It merged the exact PDF-isolation source commit
`18eda70f06f29b29de4006b7fc784a16e606cba0` with normal merge commit `e9d8bbd`. The parser audit
branch was inspected but not merged wholesale; its reproductions were ported as regressions.

## Corrections

- F1 grouped-number validation from PR #19 remains intact: recognized international, Indian,
  and unambiguous space grouping is accepted; malformed grouping remains unresolved.
- F2 oversized money, rate, and basis-point inputs are bounded at 24 normalized integer digits;
  Decimal scaling failures become typed `UnresolvedValueError`, never raw `decimal.InvalidOperation`.
- F3 text dates require exact extended `YYYY-MM-DD`; typed `date` values remain accepted.
- F4 negative financial values are rejected before half-up rounding, so tiny negatives cannot
  become zero. Accepted rounding behavior is unchanged.
- Extraction validation now proves an oversized value returns `invalid_response` with no proposal
  or audit-event write.
- All numeric fast paths, ratios, and fractional inputs share the same bounded unresolved-value
  behavior; direct PDF deadlines reject expired work before spawning and fetch plus PDF
  normalization consume one monotonic request budget.

## PDF isolation integration

Manual upload, Crawl4AI `tnc_pdf`, PDF evidence-span verification, and direct canonicalization
continue to use the child-process runner with bounded input/reply/time, a private reply channel,
a new session/process group, cancellation/deadline cleanup, process-group termination, and reaping.
The existing FI2 evidence checks and stable snapshot-time evidence-graph timestamp were preserved.

This is process isolation, not an OS sandbox: it does not provide filesystem or network isolation,
CPU/memory rlimits, Windows support, or protection from a parser exploit before the deadline.
Durable cross-process throttling, response-byte bounds before Crawl4AI materializes content, and
connection-time DNS pinning remain FI1 pre-live blockers. The real optional `pdfplumber` package
is not installed here; tests use the repository synthetic double and real subprocesses. No live
crawling, credentials, provider/model activation, or spending occurred.

## Verification evidence

`make seed PY=.venv/bin/python` seeded 42 rows. The complete backend suite from `backend/` with
regional catalogs required passed **2702 tests**, **1 skipped**, and emitted 3 warnings on the
final committed tree. Focused FI1/FI2 tests passed **102 tests** after the fix pass. Strict mypy
passed for 199 source files plus 19 ingestion files. Ruff reported 8 pre-existing core/api
findings against a ceiling of 12; all zero-tolerance scopes were clean. The exact final `make gate`
passed with `GOLDENS_OK`, `CONTRACT_OK`, `BRIEFS_IDENTICAL`, and `TREE_CLEAN`.
Ruff passed all zero-tolerance scopes and the existing legacy ceiling was checked separately.
Frontend, OpenAPI, seeds, financial goldens, Tier-F arithmetic, and authoritative specs were not
modified.

## Independent review

The independent whole-branch review reported no Critical findings. It found Important issues in
numeric fast-path/ratio bounds and per-phase PDF deadline accounting; both were fixed test-first.
The follow-up also caught the typed `10**5000` formatting edge, which was fixed before the final
focused run. Minor documentation drift and the process-group guarantee wording were corrected.

## Limitations and exclusions

FI2 financial facts remain drafts requiring human approval. This branch does not implement FI2
activation, FI3, Firecrawl, scheduling, Instagram, OpenBnB changes, frontend screens, live Crawl4AI,
OAuth, bookings, transfers, or deployment hardening. The source PDF branch, parser-audit branch,
primary checkout, and unrelated worktrees remain preserved.
