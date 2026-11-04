# Card-bank Phase 2 — reusable capture staging and configuration loaders

Branch `codex/card-bank-phase2` (base: `claude/fi3-real-capture-pilot` @ `3ea31e9`, PR #22).
Plan: `docs/superpowers/plans/2026-10-31-indian-card-data-bank.md` (branch
`claude/card-data-bank-plan`), Phase 2. Decisions: `DEVIATIONS.md`, section "Card-bank Phase 2".

**Status: VERIFICATION PENDING** (see "Verification" at the end; nothing below it is claimed
until it is filled in with the actual runs).

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

## Batch semantics (decision)

* **Validation is all-or-nothing.** Every record is validated on its own and then every row as a
  whole, by the same `validate_extraction` the extractor uses, before any proposal is written.
  Any refusal stores no proposal, and all problems are reported together.
* **Writes are per-record and idempotent**: source policy → watch target → snapshot → one proposal
  per row. This is **not** a single database transaction, and every outcome states it.
* A refused run keeps the capture evidence it stored (policy, target, snapshot), so a corrected
  extraction file can be staged against the same snapshot; an interrupted run is completed by
  repeating the same command.
* Repeat behavior: identical input returns `already_stored` for every record and adds **no** row
  (counted in the tests). A *different* extraction for the same snapshot and row, curator, summary,
  or base row is refused as `proposal_conflict`; stored history is never overwritten. (FI2's
  fingerprint does not cover the extraction itself, so the event id is derived from it.)

## Typed refusals

`unknown_curator`, `source_not_allowed`, `target_invalid`, `document_class_not_allowed`,
`document_class_mismatch`, `policy_conflict`, `target_conflict`, `capture_rejected`,
`unsupported_table`, `row_not_found`, `row_not_bound`, `duplicate_field_conflict`,
`locator_conflict`, `quote_not_found`, `quote_ambiguous`, `offset_mismatch`,
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

_To be filled in with the actual runs on the final committed tree._
