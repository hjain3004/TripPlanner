# FI2 — Extraction, Validation, and Replay

## Status

FI2 offline development is complete. The implementation stops at immutable,
evidence-backed draft proposals and human review state. It does not approve,
activate, mutate the knowledge base, crawl live sources, or add an API/UI.
FI3 review/activation remains unstarted.

## Delivered

- Added a single-attempt typed `financial_extractor` boundary. Unchanged
  normalized snapshots return before the client is touched; changed snapshots
  receive exactly one temperature-zero call with no repair, retry, fallback
  model, or network fallback.
- Added deterministic parsing for money minor units, basis points,
  micro-valuations, points, ratios, and ISO dates. Unsupported or ambiguous
  notation fails closed; the extractor's claimed parsed value is ignored.
- Added full-row, target-table, target-id, permitted-field-path, field-type,
  schema, sanity, evidence-span, snapshot-hash, artifact-integrity, and PDF
  page validation. Every accepted draft field has an exact immutable quote.
- Added shared evidence-graph draft claims using
  `ReferenceFactIdentity(namespace="financial_draft", ...)`,
  `REFERENCE_FACT`, `VERIFY_REQUIRED`, and `needs_verification=true`.
  Conflicting snapshots therefore remain separate claims; no financial truth
  resolver is invoked.
- Preserved FI0 SQLite CAS, immutable proposal lineage, audit history, and
  replay/idempotency semantics. Deterministic proposal replays return the
  original immutable payload; divergent payloads raise a typed conflict.
  Blocking validator findings cannot be approved or edited at the storage
  boundary.
- Added offline scripted/recording/replay and prompt-injection fixtures. No
  provider/model/crawler calls occur in the tests.

No authoritative spec, financial seed, golden, Tier-F arithmetic, OpenAPI,
frontend, travel adapter, request-time planning, or runtime configuration was
changed.

## Verification evidence

All commands ran in the isolated FI2 worktree with ignored regional catalogs
and the existing offline virtualenv linked locally. `make seed
PY=.venv/bin/python` seeded 42 rows.

| Check | Measured result |
|---|---|
| Seeded pre-change baseline | 2220 passed, 1 skipped, 3 warnings |
| Complete backend pytest after FI2 | 2231 passed, 1 skipped, 3 warnings |
| Focused FI0/FI1/FI2 regressions before review fixes | 41 passed |
| Focused FI0/FI1/FI2 regressions after review fixes | 45 passed |
| FI2 extraction/replay tests after review fixes | 11 passed |
| Strict mypy | 185 source files in existing packages + 16 ingestion files; clean |
| Ruff zero-tolerance scopes | clean, including ingestion and FI2 evals |
| Ruff legacy `core/` + `api/` | 8 findings, ceiling 12; unchanged pre-existing debt |
| Frozen goldens | `GOLDENS_OK` |
| OpenAPI/client contract | `CONTRACT_OK`; unchanged |
| Deterministic brief checks | `BRIEFS_IDENTICAL` |
| Final committed-tree gate before this report update | `make gate` passed; `TREE_CLEAN` |

The report update is followed by one more fresh gate run; its result is
recorded in the final handoff, not pre-written as a self-referential hash.

## Independent review

An independent whole-branch review was performed read-only against commit
`37894f2`. It found no Critical issue and five Important issues. All five were
verified and fixed test-first in the follow-up commits:

1. PDF snapshots could be labelled as non-PDF spans. Validation now requires
   `artifact_kind="pdf"` for PDF media and rejects PDF spans for other media.
2. A span's field path was not tied to its extracted field. Validation now
   requires an exact field-path match.
3. Manual material could self-escalate provenance. The manual-capture path now
   rejects provenance edits and any unverified-to-verified transition.
4. Unlisted proposed-row changes were silently discarded. Validation now
   compares the complete proposed row with the current row plus every listed,
   evidenced field and rejects any remaining change.
5. Row identity was not cross-checked. ID-bearing targets must match the
   requested target and `id` is not an extractable field.

The review also found three strict-mypy errors in the FI2 test file; explicit
typing was added and `mypy --strict ingestion/ evals/test_fi2_extraction.py`
now passes for 17 files. No other Critical/Important finding was verified.

## Safety and limitations

- No live crawling, Crawl4AI activation, Firecrawl, credentials, OAuth,
  provider/model activation, spending, bookings, transfers, scheduling, or
  deployment occurred.
- FI1's four pre-live blockers remain unchanged and open: connection-time DNS
  pinning, response-byte bounds before Crawl4AI materializes content,
  durable cross-process throttling, and process isolation/hard termination for
  hostile PDF parsing.
- FI2 does not implement review UI, approval/apply activation, FI3, or any
  financial-fact write path. A draft remains `VERIFY_REQUIRED` until a future
  human review/activation milestone.
- The parser intentionally supports only explicitly recognized target fields
  and notation. Unsupported currencies, free-form dates, ambiguous ratios,
  and unrecognized financial fields remain unresolved rather than guessed.
- The existing kernel and its frozen arithmetic, seeds, goldens, stage order,
  and LLM roles are untouched.
