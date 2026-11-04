# Card-bank Phase 3 — insert proposals (a new card, rule or valuation)

Branch `codex/card-bank-insert-proposals`, stacked on `codex/card-bank-phase2` (Milestone A, PR #23);
**not independently mergeable**. Plan: `docs/superpowers/plans/2026-10-31-indian-card-data-bank.md`
Phase 3. Decisions: `DEVIATIONS.md`, section "Card-bank Phase 3".

**Status: implemented, independently reviewed (findings fixed), gate-equivalent passed (see
"Verification").**

## Who can do what now

An operator can take a *discovery lead* (a hint that a card exists) to a *reviewed, bundled
insert* whose dry-run says `would_insert`, one command per step, no network and no model:

```text
add-curator   → add-lead (manual-only source: a name and an issuer URL, never a fact)
promote-lead  → a manual-capture target on the ISSUER's page (writes the watch-target file)
stage-capture → an insert proposal from a capture the operator saved + a curator extraction
inspect / decision / serve → review (values shown, unevidenced ones flagged)
bundle → dry-run → "would_insert", kb_constructs, dry_run_consistent
```

Nothing is applied. The bundle still says `activation_authorized: false` with D1/D2 open
(applying is Milestone C).

## Update versus insert (explicit)

| | update | insert |
|---|---|---|
| bound to | the existing row's canonical hash | the **absence** of `(table, id)` (`absent_row_hash`) |
| proposal | `intent` omitted (stored bytes unchanged) | `intent: "insert"`, `current_row_hash: null` |
| row | existing row with evidenced fields replaced | a **complete, schema-validated** new row |
| provenance | the current row's, unchanged | built by code: `crawl_draft`, `UNVERIFIED`, `needs_verification: true`, `confidence: 0.0`, source URL = target URL, date = the snapshot's capture date |
| edits in review | yes | no (reject and stage a corrected extraction) |
| id already present | n/a | blocking `insert_id_exists` finding at review; entry refused at bundle; `id_conflict` in the dry-run |

An update proposal serializes to exactly the bytes it did before this milestone (a test pins the
SHA-256 measured on the pre-insert commit).

## Evidenced and unevidenced values

The extraction may declare `inserts: [{table, id, row}]`. A value in `row` counts as quoted
evidence only when a record quotes it; otherwise it is stored as an `unevidenced_field` warning
and shown to the reviewer (page table "typed by curator" vs "quoted evidence"; computed finding;
recorded in the decision attestation) and listed in the bundle entry's `unevidenced_fields`. A
schema-required value with neither a quote nor a template is refused `needs_more_evidence`; no
value is ever padded. `None` values assert nothing and need no evidence.

## References

A bundle is validated as a unit against the seeds plus the bundle. A rule, valuation or offer that
names a card present in neither is reported (`unknown card reference: …`) and the dry-run is not
consistent; bundled with its card insert it is consistent. **Related inserts must be bundled
together.**

## Replay and concurrency

Staging derives its event id from the content, so identical input is `already_stored` (no new
row) and changed content under the same snapshot is a typed `proposal_conflict`. Store writers take
`BEGIN IMMEDIATE`; concurrency tests with a moving clock found and fixed two real defects
(snapshot identity compared timestamps; a simultaneous proposal replay raised a spurious
idempotency conflict), both mutation-checked.

## Demonstration (synthetic, separate processes, real SQLite between steps)

Inputs are synthetic (`example.invalid`; "SYNTHETIC FIXTURE" in the page). Output condensed:

```text
add-lead      {"facts_carried": 0, "lead_id": "lead-voyager", "state": "stored", "status": "filed"}
promote-lead  {"aggregator_url_carried": false, "status": "promoted",
               "target_fact_ids": ["candidate:lead-voyager", "cards:synthetic-voyager"], ...}
stage-capture status staged, extraction curator-authored, llm_calls 0, network_calls 0,
              proposal intent insert, 4 evidenced fields, 7 unevidenced_field findings
inspect       blocking findings: []   current_row: None
decision      approved; attestation.computed_finding_codes = 7 x unevidenced_field + manual_capture
bundle        schema tripwise.financial-activation-bundle/v2
dry-run       kb_constructs True, dry_run_consistent True, activation_authorized False,
              unresolved_decisions [D1, D2], seed_files_unchanged True
              [('synthetic-voyager', 'would_insert')]
--- the same id appears in the seeds before the dry-run (scratch copy)
dry-run       kb_constructs False, dry_run_consistent False  [('synthetic-voyager', 'id_conflict')]
inspect       review-time blocking findings: ['insert_id_exists']
repo seeds    0 modified files
```

The same flow is an automated test (`evals/test_card_bank_insert_cli.py`).

## Independent review

An independent reviewer examined `e1df442` (read-only, with reproductions). No way to approve,
bundle or dry-run a consistent insert over an existing id and no verified-provenance leak were
found. Two Important and several Minor findings were verified and fixed (reviewer visibility of
unevidenced values; the manual-only lead restriction; host spelling; duplicate-lead matching;
`promote-lead` argument handling; offer reference integrity; stored findings; confidence pin) —
each with a regression in `evals/test_card_bank_review_fixes.py`. Accepted/unchanged: see the
last DEVIATIONS rows (duplicate-lead check outside the write transaction; replay by fingerprint).

## Not done / limits

* No apply: seeds are never written (Milestone C).
* Proposal ids carry no table component (FI2); a future shared id surfaces as `proposal_conflict`.
* A quote spanning a PDF page boundary cannot be cited.
* Synthetic documents demonstrate the workflow, not any issuer's terms; the real HDFC capture is
  laptop-only and was not available, so a real-document insert demonstration is **pending**.

## Verification

Gate-equivalent run on `987b25812c5b9ce0dd60319eab546de770da9453` (clean tree, seeded database;
`make gate` itself cannot run in this cloud checkout because the laptop-local regional catalogs are
absent and `TRIPWISE_REQUIRE_REGIONAL_CATALOGS=1` aborts by design, so the same steps were run with
that guard unset and **this is not a `make gate` result**; catalog tests skip with a visible reason):

| Step | Result |
|---|---|
| full backend suite | **2988 passed, 28 skipped** |
| `mypy --strict` core/accounts/planning/agents/api/gateway (200 files), ingestion (29), welcome (4) | clean |
| `ruff check` (accounts, planning, agents, gateway, evals, ingestion, welcome) | clean |
| core/+api/ ruff findings | 8 (ceiling 12) |
| goldens, contract one-PR test, AGENTS.md == CLAUDE.md, clean tree | all OK |

Milestone B tests: `test_card_bank_inserts.py` (34), `test_card_bank_insert_cli.py` (8),
`test_card_bank_review_fixes.py` (23), plus the store-race tests. Repository seeds were not
modified (checked by `git status` after every demonstration).
