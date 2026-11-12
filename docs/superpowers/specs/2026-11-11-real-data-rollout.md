# Real financial data rollout: India → Singapore, first slice

**Status:** design and procedure. **Nothing here approves a fact, confirms an origin, creates a source policy or applies data.** Owner-only steps are marked **OWNER**.
**Base:** `origin/main` `a9efea0`, read 2026-11-12. Permissions: `reports/change_feed_source_permissions.md`. Firecrawl commands come from `codex/firecrawl-ingestion` `15ec9eb` (not on `main`) and are labelled as such.

## 1. Decisions

1. **Repository seeds stay the legacy placeholder set and never receive real data** (§4). Real values go into a private seeds directory outside any git checkout, through the existing controlled `apply`.
   - `apply` already refuses repository and git-checkout destinations.
   - This settles pinning and the 2026-11-01 local-only decision together.
   - Public display waits for the owner's display decision (permissions report §4.1).
2. **First slice = fees and earn for the demonstration wallet**: HDFC Infinia and Axis Atlas on trip `demo-del-sin`, the same wallet the `readiness` command measures.
   - The tables are ones review/apply already supports: `cards`, `reward_rules`, `point_valuations`.
   - Transfers, programmes, award prices and welcome offers come later, behind bounded prerequisites (§3), never through hand-edited seeds.
3. **Order by measured financial consequence, not breadth** (§2.2).
4. **Ids are permanent.** No seed id is renamed, reused or remapped. Saved revisions are never recomputed in place (§5).

## 2. What the optimizer consumes, and what the pipeline can carry today

### 2.1 Entity support, checked end to end in code

| Entity (seed file) | Used by | FI2 validator `validation.TARGET_MODELS` | Review/apply `review_rows.SUPPORTED_TABLES` | Insert | Today |
|---|---|---|---|---|---|
| Card (`cards.yaml`) | optimizer (forex, base earn, network/issuer for offer eligibility) | yes | yes | yes | real names, placeholder values |
| RewardRule (`reward_rules.yaml`) | optimizer (rule earn, caps, shared pools) | yes | yes | yes | placeholder |
| PointValuation (`point_valuations.yaml`) | optimizer (benefit value) | yes | yes | yes | placeholder |
| Offer (`offers.yaml`, merchant/bank offers) | optimizer (discounts, stacking) | yes | yes | yes | placeholder |
| FxRate (`fx_rates.yaml`) | estimator | yes | **no** | no | reference importer exists (G2) but never writes seeds |
| TransferEdge (`transfer_edges.yaml`) | pathfinder | yes | **no** | no | **fictional** (`voyager-prime → lionmiles`, …) |
| TransferBonus (`transfer_bonuses.yaml`) | pathfinder | yes | **no** | no | fictional |
| LoyaltyProgram (`loyalty_programs.yaml`) | pathfinder | **no** | **no** | no | fictional |
| AwardChartEntry (`award_chart_entries.yaml`) | pathfinder | **no** | **no** | no | fictional |
| Card → points programme link | — | — | — | — | **does not exist** (no field on `Card` or `PointValuation`; `evals/test_a3_card_products.py` docstring) |
| Programme baseline valuation | pathfinder baseline | — | — | — | **hard-coded** `agents/kernel.py:11` `{"voyager-prime": 1_000_000}` |
| Welcome / acquisition offer | `welcome/` (spec 18) | — | — | — | **separate catalog** `welcome/data/card_acquisition_offers.yaml`, own loader; no ingestion table; shipped empty |

Consequences:
- **Transfers.** A validator that accepts `transfer_edges` rows is not an apply path. Neither the applier's KB-construct check nor the seed writer handles them.
- **Real points balances.** No real points balance can drive transfer advice today. The pathfinder runs only for wallet keys present in the hard-coded baseline dict.

### 2.2 Priority inside the first slice

From the measured `readiness` influence probe (`reports/financial_data_readiness.md` §3, 63 facts on this trip; annual fee and lounge measured not to move it):

| Rank | Facts (both cards unless noted) | Evidence document | Fetch path |
|---|---|---|---|
| 1 | `forex_markup_bp`, `forex_markup_tax_bp` | fees & charges / MITC | HDFC: manual capture. Axis: MITC not found on the Atlas page earlier, so the owner chooses the document (decision O7) |
| 2 | `base_earn.points`, `base_earn.per_amount_minor`, `base_earn.currency` | card page / rewards T&C | HDFC: manual. Axis: Firecrawl HTML (owner-authorized) or manual |
| 3 | Travel rules `infinia-portal`, `atlas-travel`: earn, `cap.max_points`, `cap.period`, `shared_cap_group`, categories, channels, exclusions, `valid_to` | rewards / portal T&C (often PDF) | manual capture + local PDF worker |
| 4 | Point valuations (`infinia-portal-val`, `atlas-transfer-val`, …) | redemption terms | manual. **See note** |
| 5 | `network`, `issuer` (decide which restricted offers apply) | card page | as rank 2 |
| 6 | `annual_fee_minor`, `lounge_intl_visits_per_year` | card page | as rank 2. Last: no effect on this trip |

Notes:
- **Valuations.** A portal redemption rate can be quoted. A *transfer* valuation (`atlas-transfer-val`, "2:1-ish sweet spot") is a judgment, not an issuer statement. Under D1 it can never clear `needs_verification`, and it must not be presented as verified. The owner decides the methodology (O5).
- **Not representable today** (from readiness §7): an "unlimited" lounge entitlement, a portal "up to N×" multiplier, a monthly redemption cap and an annual-spend fee waiver. Do not force them into existing fields. Each is recorded as a finding and stays unchanged.
- **Placeholder offers.** The placeholder merchant offers (HDFC 11 facts, Klook 10) move the result but are out of the first slice. The owner chooses (O4):
  - (a) keep them, with the plan labelled "contains placeholder offers" via the existing trust badges;
  - (b) wait for the retire intent P-4.

## 3. Bounded prerequisites (missing capabilities, not data edits)

Each is one focused PR with its own tests. None needs a network call or a model.

| ID | Capability | Shape | Needed for | Proposed owner |
|---|---|---|---|---|
| **P-0** | Pin the legacy data set | `backend/core/seeds/MANIFEST.json` `{data_set: "legacy-placeholder-v1", files: {name: sha256}}`, plus a test that fails if any seed byte changes without a manifest bump. | everything (do first) | core owner |
| **P-1** | Runtime seeds directory | `TRIPWISE_SEEDS_DIR` (absolute, outside any git checkout, must contain a `MANIFEST.json`); `make seed SEEDS_DIR=…`; startup validation names the variable, never a value. `FinalReport.data_set {id, manifest_sha256}` stamped on every new report and saved revision. This is a contract change: OpenAPI + generated client + MSW + trust-badge display in **one PR**. | any real run outside the operator compare tool | backend + frontend, one branch |
| **P-2** | Programme entities in review/apply | Add `loyalty_programs`, `transfer_edges`, `transfer_bonuses`, `award_chart_entries` to `SUPPORTED_TABLES` with update and insert. Reference checks: edge endpoints exist, bonus edge exists, award programme exists. Extend the applier's KB-construct check to them. | slice 2 | ingestion owner |
| **P-3** | Card → programme link and programme baseline valuation | New tables `card_programmes.yaml` `{id, card_id, program_id, provenance}` and `programme_valuations.yaml` `{id, program_id, value_micro_major_per_point, currency, provenance}`. **`Card` itself is not modified.** `agents/kernel.py` reads baselines from the KB. The hard-coded dict remains only for the legacy data set, so the transfer goldens stay byte-identical. Data-model addition: needs a SCOPE+ row and the owner's yes (O3). | slice 2 | core owner, after O3 |
| **P-4** | Retire intent | A reviewed proposal that removes a placeholder row, bound to its current hash, applied and rolled back like any other entry. | removing placeholder offers (O4b) | ingestion owner |
| **P-5** | Welcome offers through review/apply | Target `card_acquisition_offers` (spec 18 Case A) with its own file. Loaded from the private seeds directory when P-1 is set. Matches Sol's typed `welcome_offer` terms. | slice 3 | ingestion + welcome owners |
| **P-6** | Direct honest-UA fetcher (optional) | Only if the owner wants HDFC automated (permissions O2). Firecrawl's agent is disallowed there. | optional | ingestion owner |
| **P-7** | Unknown wallet programme keys | `points_balances` keys are free strings today. Writes keep accepting them, but plan and wallet responses list `unrecognized_programmes` instead of silently ignoring them. There is no remap. | slice 2 | backend owner |

P-0 must merge before any real-data step. P-1 must merge before real data appears anywhere outside the operator compare tool. Until P-1, the only consequence view is `python -m evals.card_bank_optimizer_compare --baseline <dir> --candidate <dir> --card-id <id>`.

## 4. Pinning legacy placeholders and replay inputs

- **Goldens are already independent.** `evals/test_optimizer.py` parametrizes `evals/golden/*.yaml`, each embedding its own rows, so the frozen expected values never read `core/seeds`.
- **Replay recordings are keyed by prompt hash.** `evals/recorded/{node}/{key}.json` uses `compute_recording_key(system, user, model)`. Intake prompts embed the KB card catalog, and critic prompts embed KB POI rows. A change to repository seeds would silently turn replays into "No recording" misses. Because repository seeds never change (decision 1), every recording stays valid. P-0's hash test is what makes that a checked fact rather than a promise.
- **36 eval files** read `core/seeds` or call `seed_database()` directly. They keep testing the legacy set. Real data is exercised only through the private-directory commands in §6 and, after P-1, through `TRIPWISE_SEEDS_DIR`.
- **Bootstrap of the private set.** It starts as a byte copy of the legacy set, recorded by manifest. From then on it changes only through `apply`, so every difference from legacy has a ledger entry and is reversible with `rollback`. No placeholder value is ever edited by hand.

## 5. Ids, wallets and saved revisions

- **Card ids** (`hdfc-infinia`, `axis-atlas`, …) are updated in place by reviewed proposals and keep their ids. Stored wallets keep working.
- **A new card** is an insert with a new id. An id is never reused for a different product.
- **Programme ids.** Stored balances use keys such as `voyager-prime`, a fictional id that is not even a seeded programme. Real programmes get new ids through P-2 inserts.
  - Legacy keys are never remapped to a real programme, because "voyager-prime = some bank's points" would be an invented fact.
  - After P-7 they are reported as unrecognized, and the user re-enters balances against real ids.
- **Saved revisions** are immutable report snapshots (`TripRevision`: report JSON, `schema_version`, `trace_id`, `created_at`).
  - They stay meaningful as what the user saw, with the trust badges of that time.
  - Revisions without P-1's `data_set` field are labelled "computed from placeholder data". There is no other data set before P-1.
  - A re-run appends a new revision computed from current data. An old revision is never rewritten.

## 6. Procedure (current commands)

All commands are run from `backend/` as `python -m ingestion.review_server <cmd>`, with these private locations, **all outside any git checkout**:

```bash
D=~/tripwise-ingestion-data/real-v1          # ingestion SQLite + artifacts (private)
S_REAL=~/tripwise-real-seeds/v1              # private applied seeds
S_SCR=$(mktemp -d)/seeds                     # scratch rehearsal copy
P=~/tripwise-ingestion-data/real-v1/policies.yaml   # OWNER-written source policies
W=~/tripwise-ingestion-data/real-v1/watchlist.yaml  # watch targets
```

Always pass `--seeds-dir "$S_REAL"`. A default of `None` falls back to the repository seeds, which diverge from `S_REAL` after the first apply.

| # | Step | Who | Command |
|---|---|---|---|
| 0 | Bootstrap private seeds (byte copy) | OWNER | `mkdir -p "$S_REAL" && cp core/seeds/*.yaml "$S_REAL"/ && sha256sum "$S_REAL"/*.yaml` |
| 1 | Register curators | OWNER (own id); operator id may be registered for drafting | `add-curator --data-dir "$D" --curator-id <id> --display-name <name>` |
| 2 | Write and check policies and targets | **OWNER** writes `P` (values proposed in the permissions report); anyone checks | `check-config --source-policies "$P" --watchlist "$W"` |
| 3a | Capture HDFC (fees/MITC, rewards T&C) | **OWNER**, in a browser, saved locally | — |
| 3b | Capture Axis card page via Firecrawl (`codex/firecrawl-ingestion` only) | **OWNER** authorizes each live call | `acquire --data-dir "$D" --seeds-dir "$S_REAL" --source-policy "$P" --watch-target "$W" --target-id <t> --client-event-id <e> --live-firecrawl --confirm-no-overage --robots-file <saved robots.txt> --extraction-mode curator_authored --scripted-extraction <E.json> --per-request-credits 1 --per-run-credits <n>` |
| 4 | Write the extraction (quotes + values) | operator or owner; a draft is not a decision | curator-authored JSON. Model extraction is not activated |
| 5 | Stage | operator | `stage-capture --data-dir "$D" --seeds-dir "$S_REAL" --capture <file> --source-policy "$P" --watch-target "$W" --extraction <E.json> --document-class card_page\|tnc_pdf --captured-at <ISO-8601 with offset>` |
| 6 | Review packet | operator | `readiness --data-dir "$D" --seeds-dir "$S_REAL" --wallet-card hdfc-infinia --wallet-card axis-atlas --format md --out <outside git>`; `review-queue --data-dir "$D" --format md --out <outside git>`; `status --data-dir "$D" --seeds-dir "$S_REAL"`; `inspect --data-dir "$D" --seeds-dir "$S_REAL" --proposal-id <id>` |
| 7 | Decide | **OWNER** | `decision --data-dir "$D" --seeds-dir "$S_REAL" --proposal-id <id> --curator-id <owner> --action approve\|edit\|reject --reason <r> --expected-version <n> --client-event-id <e>` |
| 8 | Confirm origin (manual captures) | **OWNER** | `confirm-origin --data-dir "$D" --seeds-dir "$S_REAL" --proposal-id <id> --document-class <c> --curator-id <owner> --statement <s>` |
| 9 | Bundle + dry-run | operator | `bundle --data-dir "$D" --seeds-dir "$S_REAL" --curator-id <id> --client-event-id <e> --proposal-id <id> …` → `H`; `dry-run --data-dir "$D" --seeds-dir "$S_REAL" --bundle-sha256 "$H"` (expect `dry_run_consistent: true`, `seed_files_unchanged: true`) |
| 10 | Scratch rehearsal | operator | `cp -R "$S_REAL" "$S_SCR"`; `apply --data-dir "$D" --seeds-dir "$S_SCR" --bundle-sha256 "$H" --curator-id <id> --reason <r> --client-event-id <e>`; `coverage --data-dir "$D" --seeds-dir "$S_SCR"`; `python -m evals.card_bank_optimizer_compare --baseline "$S_REAL" --candidate "$S_SCR" --card-id hdfc-infinia`; `rollback --data-dir "$D" --seeds-dir "$S_SCR" --apply-id <A> --curator-id <id> --reason <r>`; `sha256sum` to confirm byte identity |
| 11 | Apply to the private set | **OWNER** | `apply --data-dir "$D" --seeds-dir "$S_REAL" --bundle-sha256 "$H" --curator-id <owner> --reason <r> --client-event-id <e>`; then `coverage` |
| 12 | Undo / interrupted run | **OWNER** | `rollback --data-dir "$D" --seeds-dir "$S_REAL" --apply-id <A> --curator-id <owner> --reason <r>`; after a crash `recover --data-dir "$D" --seeds-dir "$S_REAL"` |
| 13 | Run the planner on real data | OWNER (local) | **after P-1 only**: `TRIPWISE_SEEDS_DIR="$S_REAL" make seed` then the normal local stack |

Steps 7, 8, 11 and 12 on `S_REAL` are owner-only. No agent runs them, and no agent registers or uses the owner's curator id.

## 7. Slices after the first

- **Slice 2: transfer advice for DEL–SIN.** Needs P-2, P-3 and P-7.
  - Programme rows for each bank currency and for KrisFlyer.
  - Transfer edges evidenced from the **issuer's** pages where they state them.
  - Award prices only after the owner settles the KrisFlyer terms question (permissions O5).
  - Transfer-bonus news from the change feed stays a lead until a primary capture confirms it.
- **Slice 3: welcome offer, Case A.** Needs P-5. A held card's offer must have quoted minimum spend and window, or acquisition assessment stays blocked. A merchant offer is never used in its place.

## 8. Owner decisions

| ID | Decision |
|---|---|
| O1 | Display permission for issuer-derived numbers on the deployed site, and separately in the public repository (permissions §4.1). Until then real data stays in `S_REAL` and the site stays on legacy placeholders. |
| O2 | HDFC: manual capture only, or build P-6. |
| O3 | Approve the P-3 data-model addition (new link and programme-valuation tables; `Card` unchanged) as SCOPE+. |
| O4 | Placeholder offers in real-data runs: (a) keep with labels, or (b) wait for P-4 and retire them. |
| O5 | Valuation methodology: which valuations are quotable issuer rates and which are judgments that stay `needs_verification`. |
| O6 | Attest the source policies (`P`) for HDFC manual, Axis HTML (Firecrawl) and Axis PDF (manual). Authorize each live Firecrawl call. |
| O7 | Which Axis document evidences forex markup and tax (MITC not found on the Atlas page). Same question for SBI fees, later. |
| O8 | Each `decision`, `confirm-origin`, `apply` and `rollback` on `S_REAL`. |
