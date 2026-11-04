# Card-bank Phase 2 — reusable capture staging and configuration loaders

Branch `codex/card-bank-phase2` (base: `claude/fi3-real-capture-pilot` @ `3ea31e9`, PR #22).
Plan: `docs/superpowers/plans/2026-10-31-indian-card-data-bank.md` (branch
`claude/card-data-bank-plan`), Phase 2. Decisions: `DEVIATIONS.md`, section "Card-bank Phase 2".

**Status: ACCEPTED on its own terms** (offline, local operator tooling): gate-equivalent
passed on code revision `4a24fe3` (see "Verification"; `make gate` itself cannot run in this
cloud checkout, and why is stated there). The real-document demonstration is still pending.

## Who can do what now

An operator with the local FI3 setup can turn a document they saved themselves into validated,
reviewable proposals with **one command**, instead of a one-off script:

```text
python -m ingestion.review_server add-curator   --data-dir D --curator-id alice --display-name Alice
python -m ingestion.review_server check-config  --source-policies P --watchlist W [--discovery-sources S]
python -m ingestion.review_server stage-capture --data-dir D --capture FILE --source-policy P \
        --watch-target W --extraction E --document-class card_page|offer_page|tnc_pdf
# then the existing commands: inspect, decision, reopen, bundle, dry-run, serve
```

`stage-capture` runs the real pipeline, `ManualUploadBackend → SnapshotService →
FinancialExtractor → proposal storage`. The curator-authored extraction reaches the extractor
through the existing scripted-client seam and is labelled `curator-authored` in every output and
in the stored proposal (`extractor_version = curator-authored-v1`). There is **no model call and
no network access** (outcomes report `llm_calls: 0`, `network_calls: 0`; a test blocks sockets).

Nothing is applied: proposals are `pending`, the capture stays `manual_capture`, seeds are never
written, and the bundle still reports `activation_authorized: false` with D1/D2 open.

## Inputs

| File | Format | Validated by |
|---|---|---|
| source policy | YAML/JSON list or one mapping of `SourcePolicyRecord` | `load_source_policies` (unknown keys, bare domain, `source_url` inside the domain, duplicates, aggregator domains refused) |
| watch target | `watchlist.yaml` entries (`target_id, url, kind, target, source_policy_id, check_frequency_days, css_hint?, backend, manual_only`) | `load_watchlist` (policy exists, URL inside the policy domain, page class and access mode allowed by the policy, aggregator URLs and `firecrawl` refused) |
| curator extraction | `schema: tripwise.curator-extraction/v1`, `curator_id`, optional `change_summary`, `records: [{table, id, field_path, raw_value, quote, occurrence?, offset?, page?}]` | `CuratorExtraction` (`extra="forbid"`), then FI2's own validator per record and per row |
| discovery sources (optional) | spec 05 §0 fields | `load_discovery_sources`: a terms record is mandatory; exactly one of `automated_access_permitted` / `manual_only`; no field that can hold a fact |

Evidence disambiguation: a quote must be an **exact** substring of the stored canonical text. An
ambiguous quote is refused with its locations (`occurrence` is 1-based, or give `offset`); a PDF
quote must cite its `page`, and the real page text is checked by the isolated PDF child process.
A near miss (whitespace or NFKC difference) is refused with the exact stored text shown as a hint.
For a PDF the pages' text is mapped onto the stored text, so a span must lie inside the page it
cites (`page_offset_mismatch` otherwise) and an ambiguous quote lists the page of each candidate.

## Batch semantics (decision)

* **Validation is all-or-nothing.** Every record is validated on its own and then every row as a
  whole, by the same `validate_extraction` the extractor uses, before any proposal is written.
  Any refusal stores no proposal, and all problems are reported together.
* **Writes are per-record and idempotent**: source policy → watch target → snapshot → one proposal
  per row. This is **not** a single database transaction, and every outcome states it.
* A refused run keeps the capture evidence it stored (policy, target, snapshot), so a corrected
  extraction file can be staged against the same snapshot; an interrupted run is completed by
  repeating the same command.
* Capture-dependent refusals (unreadable capture, byte bound, a declared class that does not
  match the real format) happen **before** any policy or target row is written, so the operator
  can correct the source description and try again.
* Repeat behavior: identical input returns `already_stored` for every record and adds **no** row
  (counted in the tests). A *different* extraction for the same snapshot and row, curator, summary,
  or base row is refused as `proposal_conflict`; stored history is never overwritten. (FI2's
  fingerprint does not cover the extraction itself, so the event id is derived from it.)

## Typed refusals

`unknown_curator`, `source_not_allowed`, `target_invalid`, `document_class_not_allowed`,
`document_class_mismatch`, `policy_conflict`, `target_conflict`, `capture_rejected`,
`unsupported_table`, `row_not_found`, `row_not_bound`, `duplicate_field_conflict`,
`locator_conflict`, `page_offset_mismatch`, `page_map_unavailable`, `quote_not_found`, `quote_ambiguous`, `offset_mismatch`,
`occurrence_out_of_range`, `page_required`, `page_not_applicable`, `field_path_invalid`,
`provenance_field_forbidden`, `value_unresolved`, `value_not_supported_by_quote`,
`evidence_rejected`, `row_schema_invalid`, `validation_refused`, `proposal_conflict`; file-level
problems are `config_*` issues with a file and location. Exit code 2, typed JSON on stdout, one
line on stderr.

## Not done / limits

* Existing rows only. Inserting a new card, rule or valuation is Milestone B.
* No live fetching and no model extraction. The documented transport blockers (connection-time DNS
  pinning, response-size bounds before materialization, durable cross-process throttling) are
  untouched; nothing here bypasses them.
* Synthetic documents show the workflow works; they establish nothing about any issuer's terms.
  The real HDFC capture, pilot database and original staging script are laptop-only and were not
  available in this environment, so **the real-document demonstration remains pending**.

## Verification

Execution mode: real SQLite, the real CLI in separate processes, the real installed
`pdfplumber 0.11.10` (task-owned venv, installed unhashed from PyPI per the `ingestion-local`
range; it is not in the hashed lockfile), synthetic documents on `example.invalid`. No model
call, no network, no credential; seeds and goldens untouched.

**Demonstrated** (synthetic inputs; scratch data directory outside the repository): `add-curator`
→ `check-config` → `stage-capture` (HTML) → repeat (`already_stored` for policy, target, snapshot
and proposal) → `inspect` → `decision approve` → `reopen` (new process, status `approved`) →
`bundle` (`activation_authorized: false`, `blocked_by: [D1, D2]`) → `dry-run`
(`dry_run_consistent: true`, `kb_constructs: true`, `seed_files_unchanged: true`,
`would_update` on `annual_fee_minor` 1250000→1500000 and `forex_markup_bp` 200→350). Refusals
shown with typed codes: invalid quote and malformed value together (`quote_not_found`,
`value_unresolved`), whitespace near-miss with the exact stored text as a hint, unsupported
value, row outside the target, provenance field, conflicting second extraction after approval
(`proposal_conflict`), unknown curator, unknown key in a file. PDF with the real parser:
`page_required`, ambiguous quote listing each page, wrong page (`page_offset_mismatch`), a PDF
declared a card page (`document_class_mismatch`), and a staged two-field proposal whose
evidence cites page 2.

**Focused regressions** (new, `backend/evals/`): `test_card_bank_config_loaders.py` 47,
`test_card_bank_staging.py` 61, `test_card_bank_cli.py` 11 (real subprocess flow; the PDF test
skips itself with an explicit reason where the library is absent), `test_card_bank_store_races.py`
2 (six threads, 25 trials, separate store handles). Mutation spot-checks of the five guards the
review stressed (whole-token quote support, host normalization, the store's write lock, the
page/offset check, canonical span order) each fail a test when removed.

**Independent review** (one subagent, read-only, reproduced each finding): three Important and
four Minor findings; all verified and fixed in `4a24fe3` with regressions (details and the
decision rows in `DEVIATIONS.md`). The most serious was in the shared FI2 validator: a bare
substring test let the raw value `"000"` be "supported" by the quote "INR 15,000" and parse to
0 (also `"5"`, `"15"`, `"INR 1"`). It now requires a whole token. The reviewer's remaining
notes are recorded as accepted limits: proposal ids have no table component (no collision in the
current seeds), and a quote that spans a PDF page boundary cannot be cited.

**Gate-equivalent, code revision `4a24fe34cb49b94bf99b60b2c897be2a50d96e8b`, clean tree, KB
seeded with `make seed`:** complete backend suite **2920 passed, 28 skipped, 0 failed** (the
skips: regional catalogs not provisioned, a test that needs a non-root user, and empty
parametrisation where no catalog exists); `mypy --strict` clean (`core accounts planning agents
api gateway`: 200 files; `ingestion`: 28; `welcome`: 4); `ruff` clean in every zero-tolerance
scope; `core/`+`api/` legacy findings 8 (ceiling 12); `GOLDENS_OK`, `CONTRACT_OK`,
`BRIEFS_IDENTICAL`, `TREE_CLEAN`. **This is not `make gate`:** the six regional catalogs are
laptop-local and their provisioning inputs are not in the repository, so `make gate`
(`TRIPWISE_REQUIRE_REGIONAL_CATALOGS=1`) aborts by design in a clean cloud checkout. The same
commands ran with that variable unset, as CI does; the guard was not weakened. A first run
before seeding the KB showed 158 failures and 29 errors, all `no such table: cards`, which is the
documented `make seed` prerequisite, not a defect. GitHub CI results for the pull request are
recorded on the PR.

The code-bearing revision is `4a24fe3`; later commits on this branch change documentation only.
