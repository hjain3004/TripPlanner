# Indian Credit-Card Data Bank — Plan

**Status:** plan; not started. **Date:** 2026-10-31. **Base:** `main` `8d805e3`.
**Owner decision (2026-10-31):** build a verified bank of Indian credit-card facts. D1 and D2
are approved (see §2).
**Authority:** [spec 05](../../specs/05_ingestion_pipeline_phase2.md),
[spec 06](../../specs/06_implementation_protocol.md),
[robust ingestion plan](2026-10-07-robust-financial-ingestion.md) (FI5/FI6). Specs win over this
plan.

## 1. Outcome

Travelers get plans whose card advice rests on **issuer-verified** facts for the cards they hold,
not placeholder seeds. For each Indian card in scope, the KB holds:
- annual fee;
- forex markup;
- base earn;
- key reward rules and caps;
- point valuations.

Every value carries quoted evidence from the issuer's own page or MITC/fees PDF, a named
curator, and a date.

**Source rule.** Spec 05 is binding: an aggregator value can never become a stored fact.
- **Aggregators** (CardExpert, Paisabazaar, BankBazaar, …) are used only as discovery leads
  ("this card exists; its issuer page is X"), and only as their terms allow.
- **Issuer evidence.** Facts come only from issuer evidence, captured within each issuer's
  robots.txt and terms.

**Non-goals:**
- bulk scraping of any aggregator;
- login-walled pages;
- CAPTCHA or bot-protection workarounds;
- paid services;
- publishing captured page text. Captures stay local, outside Git.

## 2. Decisions recorded for this work

| ID | Decision (approved 2026-10-31) | Effect |
|---|---|---|
| D1 | Provenance is verified **per field**. A row clears `needs_verification` only when every non-identity field has quoted evidence from an approved decision (this one or an earlier one still valid). | FI5 tracks field-level evidence. Partly evidenced rows stay `needs_verification: true` and list their missing fields. |
| D2 | A manual capture may count as `official_page`/`tnc_pdf` when the capture's URL is on the issuer domain in its source policy and the curator confirms that in the decision. | FI5 adds a curator confirmation to the decision, and bundles drop `blocked_by: D2` for confirmed captures. |

Log both in `DEVIATIONS.md` when Phase 4 starts (one row each, citing this plan).

## 3. What exists vs. what is missing (verified on `8d805e3` plus FI3 fix branch `3ea31e9`)

| Exists | Missing |
|---|---|
| Manual upload → snapshot → FI2 validation → FI3 review → v2 bundle dry-run, proven on a real HDFC capture | A product CLI command to stage a capture (the pilot used a one-off script outside the repo) |
| `DiscoveryCandidate`, `promote_candidate_to_watch_target` (`backend/ingestion/policy.py`), `SourcePolicyRecord`, `WatchTarget` | Loaders for spec 05's `discovery_sources.yaml` and `watchlist.yaml` |
| PDF parsing in a killable child process | The real `pdfplumber` (the `ingestion-local` extra) has never run here |
| FI2 single-call extractor with recording/replay | Any approved live use of the free-tier model for extraction |
| Updates to existing seed rows | **Inserting a new card, rule, or valuation.** `validate_extraction` and the FI3 bundle require an existing row. |
| `Card` model (spec 01) | Fields for "unlimited" lounge visits, separate joining/renewal fees, and fee-waiver spend. These need a spec 01 change approved by you. |
| FI3 dry-run only | FI5: controlled apply to seeds with rollback; FI6: re-verification schedule |

## 4. Phases

Each phase ends with a demonstrated workflow, focused tests, and one `make gate`. Each phase is
one branch and one PR, with one independent review.

### Phase 0 — Land the FI3 fixes (prerequisite)
Push and merge `claude/fi3-real-capture-pilot` (`86b7855`, `3ea31e9`).

### Phase 1 — Source permissions (research; no code)
1. Read the public terms and robots.txt of three discovery aggregators: CardExpert, Paisabazaar,
   BankBazaar. For each, record:
   - whether automated access is permitted;
   - whether it must be `manual_only`;
   - any rate limit;
   - the date read.
2. Do the same for the issuers in scope. Start with the four seeded issuers (HDFC is done:
   `hdfc.bank.in` robots allows all agents; the website usage terms are read, and the content
   is personal, non-commercial, local-only per the owner's decision). Add the next issuers by
   card share.
3. **Output:** `reports/card_bank_source_permissions.md`, a table per source with its terms
   quotes and the resulting policy.
4. **Human checkpoint:** you confirm each source's policy before it is used.

### Phase 2 — Real-document path as a product feature
1. **Install the `ingestion-local` extra** (`pdfplumber`) in the backend virtualenv. This is a
   dependency install, so it needs your OK. Run the existing real-library PDF tests that are
   currently skipped.
2. **Add a `stage-capture` subcommand** to `backend/ingestion/review_server.py`. It replaces
   `~/tripwise-ingestion-data/stage_hdfc_capture.py`.
   - **Inputs:** a capture file, a source-policy file, a watch-target file, and a curator
     extraction file.
   - **Curator extraction file:** a JSON list of `{table, id, field_path, raw_value, quote}`.
     Quotes must be exact text from the stored snapshot; ambiguous quotes need an occurrence.
   - **Path:** it runs `ManualUploadBackend` → `SnapshotService` → `FinancialExtractor`, using
     the curator response through `ScriptedLLMClient` and labelled `curator-authored`.
   - **Refusals:** any validation refusal is printed per field and nothing is stored for it.
3. **Add loaders** for `discovery_sources.yaml` and `watchlist.yaml` (spec 05 §§0–1), validated
   into the existing contracts. They live in the data directory, not the repository, when they
   name captured content.
4. **Demo.** Capture HDFC's MITC PDF (linked from the approved Infinia page). Extract
   `forex_markup_bp` and `forex_markup_tax_bp` with page-cited quotes, review them in FI3, and
   dry-run.

### Phase 3 — New rows (insert proposals)
1. **Validation.** Extend `validate_extraction` (`backend/ingestion/validation.py`) with an
   insert mode: `current_row=None`, every field evidenced or explicitly marked unevidenced, a
   schema-valid row, an ID that is not already present, and provenance `crawl_draft` with
   `needs_verification: true`.
2. **Review.** Extend FI3 review and bundles:
   - an `insert` entry type;
   - dry-run status `would_insert`;
   - a conflict when the ID appears meanwhile.
3. **Discovery.** Promote discovery candidates to watch targets for 5–10 new cards from the
   Phase 1 sources, and stage their issuer captures.
4. **Demo.** One new card goes from discovery lead → issuer capture → insert proposal → review →
   dry-run.

### Phase 4 — FI5: controlled apply with D1/D2
1. **Apply.** Add an `apply` command that writes approved bundle entries to
   `backend/core/seeds/*.yaml` atomically:
   - it re-checks each base-row hash and refuses stale entries;
   - it computes `needs_verification` per D1, and the source type per D2;
   - it records a rollback bundle (the exact prior bytes of each seed file).
2. **Rollback.** Add a `rollback` command that restores those bytes after verifying their hash.
3. **Goldens.** Goldens embed their own KB, so they must stay `GOLDENS_OK`. Run the demo and
   A3/A4 tests that read the seeds after each apply.
4. **Commits.** Seed-data changes ship as their own reviewed "fact-data" commit, never mixed
   with code (spec 06 §3).
5. **Demo.** Apply the four pilot cards' verified fields, show the before/after trust badges in
   a plan, then roll back and re-apply.

### Phase 5 — Scale and keep fresh (FI6)
1. **LLM extraction.** If you approve it, use the configured free-tier model for extraction (one
   call per changed snapshot, recorded for replay, $0 ceiling). Curator-authored extraction
   stays the fallback.
2. **Re-verification.** Run the staleness sweeper on spec 05's thresholds (offers at 90 days,
   rules at 365 days); it creates re-verify tasks.
3. **Metrics.** Track approval and edit rates. If the field-level edit rate exceeds 30%, stop
   adding sources (spec 05).

## 5. Approvals you will be asked for

| When | Approval |
|---|---|
| Phase 1 | Each source's policy; any live read of a terms page or robots.txt |
| Phase 2 | Installing `pdfplumber`; each Chrome-assisted capture URL |
| Phase 3 | A spec 01 change, if you want "unlimited lounge" or the extra fee fields modeled |
| Phase 4 | Each fact-data commit that changes seeds |
| Phase 5 | Live free-tier LLM extraction |

## 6. Risks

- **Terms vary by source.** A source that forbids automation stays manual-only. A source that
  forbids storage is not used.
- **Bot protection** (as seen on `hdfcbank.com`) means some issuers will be capture-by-browser
  only.
- **Manual capture effort** limits scale until Phase 5. The first realistic target is the four
  seeded cards plus 5–10 popular cards.
- **No KB value changes without a reviewed fact-data commit**, and rollback is required.
