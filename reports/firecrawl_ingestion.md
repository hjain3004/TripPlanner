# Firecrawl Financial Ingestion Integration

**Branch:** `codex/firecrawl-ingestion`  
**Worktree:** `/Users/himanshu_jain/.codex/worktrees/firecrawl-ingestion/TripPlanner`  
**Execution mode:** Real SQLite + filesystem artifact store + real `pdfplumber` worker + multi-process CLI execution against retained captures (`RetainedCaptureTransport`), deterministic replay (`SCRIPTED_REPLAY` / `CURATOR_AUTHORED`), and **one human-authorized live Firecrawl `/v2/scrape` pilot call** (`axis-atlas-card-live-v1`, 1 credit) whose persisted snapshot was replayed through `--extraction-mode curator_authored` (`replayed_fetch=True`, 0 extra scrapes) into the real `review-queue` and `inspect`. Live Firecrawl API calls remain disabled by default unless `--live-firecrawl --confirm-no-overage --robots-file` and `FIRECRAWL_API_KEY` are explicitly supplied.

---

## 1. What an Operator Can Do Now

Operators can execute the complete financial-rule acquisition, diffing, extraction, and review-queue pipeline from the `ingestion.review_server` CLI without writing ad-hoc scripts or touching `core/seeds/*.yaml`:

1. **Validate Firecrawl-enabled watchlists (`check-config --allow-firecrawl`):**
   - Verifies source-policy records, watchlist entries, curator registries, and base seeds.
   - Admits `backend: "firecrawl"` targets only when `--allow-firecrawl` is supplied and the target is a non-manual HTML `card_page` or `offer_page` governed by a policy with `automated_access_permitted=True` and `manual_only=False`.
   - Manual-only policies (e.g., `hdfc-bank-in-manual-card-page`), aggregator hosts, and PDF/help targets (`tnc_pdf`, `help_page`) remain fail-closed refused for automated Firecrawl acquisition.
2. **Acquire a single target (`acquire`):**
   - Runs `approved target` → `FirecrawlBackend` with `DurableAcquisitionControl` → `FetchAttempt` → `SnapshotService` → `diff_snapshots` → `FinancialExtractionRuntime` → `ChangeProposal` (`pending`, `UNVERIFIED`, `confidence=0.0`) → `review-queue`.
   - Persists `FetchAttempt`, raw/normalized/provider-envelope artifacts, and `SnapshotBundle` **before** running extraction. If extraction fails or the process crashes after a scrape, re-running `acquire` with the same `--request-id` replays the stored `FetchResult` (`replayed_fetch=True`, `0` new scrapes) and completes extraction against the true predecessor snapshot.
   - Records linked provider-envelope provenance (`provider_envelope_artifact`, `evidence_fidelity="provider_rendered_html"`, `is_original_issuer_http_bytes=False`, `complete_redirect_chain_available=False`) on both `FetchResult` and `SnapshotBundle`, and links a `financial_provider_envelope` node into `financial_draft_graph`.
3. **Refresh due targets in bounded stable order (`refresh-due`):**
   - Selects eligible targets via `DurableAcquisitionControl.due_targets` in deterministic `(next_due_at, target_id, canonical_url)` order, bounded by `--limit`.
   - Enforces per-request, per-run, and monthly credit budgets plus per-domain `min_delay_seconds` before any network dispatch.
   - Skips extraction (`0` model calls, `extraction_status="skipped_unchanged"`, `0` duplicate proposals) when normalized content is unchanged.
   - Preserves prior snapshots, proposals, and human review decisions when changed content produces a new superseding snapshot.
   - Never automatically retries a target whose prior request is in `dispatching` or `needs_reconciliation` state, even when `refresh-due` generates a new `request_id` in a later run.
4. **Inspect and review pending proposals (`review-queue`, `inspect`, `status`):**
   - Proposals created by `acquire` or `refresh-due` appear immediately in `review-queue` and `inspect` with exact evidence quotes, offsets, current-vs-proposed values, and D1/D2 blockers.

---

## 2. Demonstrated Results & Working Commands

All commands below were executed from `/Users/himanshu_jain/.codex/worktrees/firecrawl-ingestion/TripPlanner/backend`:

### A. End-to-End Retained-Capture & Real-PDF Demonstration
```bash
.venv/bin/python -m evals.demo_firecrawl_ingestion --json
```
- **Demonstrated behavior:**
  - **Refusal gates:** Refuses HDFC Infinia (`manual_only=True`, `automated_access_permitted=False`, `robots.txt` `Disallow: /`) and Axis Atlas PDF (`tnc_pdf`) on `FirecrawlBackend` before any network/transport dispatch (`0` credits spent).
  - **HTML acquisition + extraction (`Axis Bank Atlas` retained capture):** Acquires HTML via `FirecrawlBackend`, creates immutable raw/normalized/provider-envelope artifacts (`evidence_fidelity="provider_rendered_html"`), diffs snapshots, runs `FinancialExtractionRuntime` (`SCRIPTED_REPLAY`, 1 call), and persists a pending proposal (`prop_...`) visible in `review-queue`.
  - **Unchanged re-capture:** Second capture with identical content creates a new snapshot in lineage, computes `diff.changed=False`, and skips extraction (`0` LLM calls, no duplicate proposal).
  - **Changed re-capture:** Updated content creates a superseding snapshot (`supersedes_snapshot_id` set), preserves earlier snapshots and proposals, and extracts the updated draft.
  - **Real PDF extraction (`stage-capture` + `pdfplumber`):** Stages a real 2-page PDF capture for `axis-atlas-pdf`, extracts text via the isolated `pdfplumber` worker (`application/pdf`), verifies evidence spans against extracted PDF text, and writes a pending proposal without invoking Firecrawl.
  - **Durable `DurableAcquisitionService` orchestration (Scene 11):** Exercises `DurableAcquisitionService.acquire_sync` + `RetainedCaptureTransport` + `DurableAcquisitionControl` end-to-end, confirming replay (`replayed_fetch=True` on repeat `--request-id`) and `provider_envelope_artifact` provenance.

### B. Multi-Process CLI Workflow (`check-config`, `acquire`, `refresh-due`, `review-queue`, `inspect`)
```bash
# 1. Validate Firecrawl-enabled configuration
.venv/bin/python -m ingestion.review_server \
  check-config \
  --source-policies /path/to/policies.yaml \
  --watchlist /path/to/watchlist.yaml \
  --allow-firecrawl

# 2. Acquire a single target from retained capture + scripted replay extraction
.venv/bin/python -m ingestion.review_server \
  acquire \
  --data-dir /path/to/data_dir \
  --source-policy /path/to/policies.yaml \
  --watch-target /path/to/watchlist.yaml \
  --retained-capture /path/to/retained_firecrawl.json \
  --extraction-mode scripted_replay \
  --scripted-extraction /path/to/scripted_extraction.json \
  --client-event-id cli-acquire-0001

# 3. Run bounded refresh-due across eligible targets
.venv/bin/python -m ingestion.review_server \
  refresh-due \
  --data-dir /path/to/data_dir \
  --source-policies /path/to/policies.yaml \
  --watchlist /path/to/watchlist.yaml \
  --limit 5 \
  --retained-captures-manifest /path/to/captures_manifest.json \
  --extraction-mode scripted_replay \
  --scripted-extraction /path/to/scripted_extraction.json \
  --client-event-prefix cli-refresh-0001

# 4. Inspect review queue and proposal details
.venv/bin/python -m ingestion.review_server \
  review-queue \
  --data-dir /path/to/data_dir \
  --format json

.venv/bin/python -m ingestion.review_server \
  inspect \
  --data-dir /path/to/data_dir \
  --proposal-id <proposal_id>
```

---

## 3. What Is Prevented and Recoverable

| Failure / Risk | Prevention & Recovery Behavior |
|---|---|
| **Duplicate request / retry after extraction failure** | `FetchAttempt` and `SnapshotBundle` are committed before extraction. Re-running `acquire` with the same `request_id` replays the stored `FetchResult` (`0` new scrapes) and completes extraction against the prior snapshot. |
| **Same `request_id` with different target/policy/options** | Refused fail-closed with `IdempotencyConflictError` (`request_fingerprint` mismatch). |
| **Crash or timeout after `mark_dispatching`** | Request stays `dispatching` or transitions to `needs_reconciliation`; credits stay reserved (`spent_uncertain`). Neither `acquire` nor `refresh-due` will issue a new paid request for that `request_id` **or** for that `canonical_url` under a fresh `request_id` until an operator explicitly runs `reconcile(request_id, resolution=..., operator_id=..., reason=...)`. |
| **Concurrent processes racing on budget or domain delay** | Reservations occur inside `BEGIN IMMEDIATE` SQLite transactions before network I/O; concurrent processes cannot double-spend the run/monthly allowance or violate `min_delay_seconds`. |
| **Unchanged upstream page** | `diff_snapshots` reports `changed=False`; `DurableAcquisitionService` records the snapshot and skips `FinancialExtractionRuntime` (`0` LLM calls, no duplicate proposal). |
| **Rendered DOM mistaken for wire bytes** | `FetchResult` and `SnapshotBundle` carry `evidence_fidelity="provider_rendered_html"` and a separate `provider_envelope_artifact` explicitly stating `is_original_issuer_http_bytes=False` and `complete_redirect_chain_available=False`. |
| **Silent mutation of `core/seeds/*.yaml`** | `DurableAcquisitionService` only creates `pending` `ChangeProposal` records (`verified_by="UNVERIFIED"`, `needs_verification=True`, `confidence=0.0`). Repository seeds are untouched. |

---

## 4. Verification Summary

- Focused ingestion + Firecrawl suites (`evals/test_ingestion_acquisition.py`, `evals/test_firecrawl_extraction_flow.py`, `evals/test_firecrawl_backend.py`, `evals/test_acquisition_control.py`, `evals/test_card_bank_config_loaders.py`, `evals/test_fi1_pdf_isolation.py`, `evals/test_card_bank_cli.py`): **PASS**
- `.venv/bin/ruff check ingestion/ evals/`: **PASS**
- `.venv/bin/mypy --strict ingestion/`: **PASS**
- Full committed-tree `make seed` and `make gate`: **PASS** (recorded below on final commit)

---

## 5. Authorized Live Pilot Execution & Review-Queue Verification

Following explicit human authorization on 2026-11-07 for `axis-atlas-card-live-v1` (`https://www.axis.bank.in/cards/credit-card/axis-bank-atlas-credit-card`, policy `axis-bank-in-firecrawl-card-page-v1`, 1 call / 1 credit maximum), while keeping `hdfc-infinia-card-page` on `manual_only: true` (`Disallow: /` in `robots.txt`):

1. **Live Firecrawl Acquisition (`--live-firecrawl --extraction-mode disabled`, 1 call / 1 credit):**
   - `request_id`: `acq:axis-atlas-card-live-v1:e3837bd7484ebf90` (`client_event_id`: `req-axis-atlas-live-20261107-01`)
   - `state`: `"completed"`, `operator_outcome`: `"completed_and_replayable"`, `replayed_fetch`: `false`, `estimated_credits`: `1`, `charged_credits`: `1`
   - `evidence_fidelity`: `"provider_rendered_html"` (`is_original_issuer_http_bytes: false`, `complete_redirect_chain_available: false`)
   - `raw_sha256`: `aa0a7b25628f11d6a0b2eddb0a46f9ee4e101270f8333bc5c6843875f9fbbece`
   - `normalized_sha256`: `0ad9806c9aaa8f132b270a628f2a9879579da916a97732d2ce1080c621bceb54`
   - `provider_envelope_sha256`: `70733b21bbe36dcf53878634c44e88d1fb9bb075f70c5fa3e35046e3cd617a68`
   - `snapshot_id`: `snapshot:axis-atlas-card-live-v1:0ad9806c9aaa8f132b270a628f2a9879579da916a97732d2ce1080c621bceb54:aa0a7b25628f11d6a0b2eddb0a46f9ee4e101270f8333bc5c6843875f9fbbece`

2. **Post-Fetch Replay + Curator-Authored Extraction (`--extraction-mode curator_authored`, 0 additional scrapes, 0 hosted LLM calls):**
   - Re-running `acquire` with `--client-event-id req-axis-atlas-live-20261107-01 --extraction-mode curator_authored --scripted-extraction "$HOME/tripwise-ingestion-data/firecrawl-live-pilot/axis_atlas_live_extraction.json"` replayed the persisted live snapshot (`"replayed_fetch": true`, `0` new Firecrawl calls, `0` new credits) and verified 6 exact quotes and offsets against the live snapshot:
     - `forex_markup_bp`: `150` → `350` (`"Foreign currency transaction fee3.50% of the transaction value"`, offsets `97149..97211`, `quote_verified: true`)
     - `annual_fee_minor`: `500000` (`"Standard annual fee (2nd year onwards)₹5,000"`, offsets `95687..95731`, `quote_verified: true`)
     - `base_earn.points`: `2` (`"2 EDGE Miles earned on every 100 spent"`, offsets `93592..93630`, `quote_verified: true`)
     - `base_earn.per_amount_minor`: `10000` (`"per ₹100 spent"`, offsets `89513..89527`, `quote_verified: true`)
     - `issuer`: `"Axis Bank"` (`"Axis Bank Atlas Credit Card"`, offsets `30..57`, `quote_verified: true`)
     - `name`: `"Atlas"` (`"Axis Bank Atlas Credit Card"`, offsets `30..57`, `quote_verified: true`)
   - Queued pending proposal `proposal:axis-atlas:snapshot:axis-atlas-card-live-v1:0ad9806c9aaa8f132b270a628f2a9879579da916a97732d2ce1080c621bceb54:aa0a7b25628f11d6a0b2eddb0a46f9ee4e101270f8333bc5c6843875f9fbbece` (`status: "pending"`, `verified_by="UNVERIFIED"`, `needs_verification=True`) in the real `review-queue` and verified via `inspect`.

3. **Remaining Boundaries:**
   - The proposal remains `pending` in `~/tripwise-ingestion-data/firecrawl-live-pilot/data/ingestion.sqlite` (`core/seeds/*.yaml` untouched; `blocked_by: ["D1"]` for the 6 fields not quoted on the HTML card page: `base_earn.currency`, `country`, `fee_currency`, `forex_markup_tax_bp`, `lounge_intl_visits_per_year`, `network`).
   - Extraction used `ExtractionMode.CURATOR_AUTHORED` (`0` hosted LLM tokens); live LLM extraction (`ExtractionMode.AUTHORIZED_CLIENT`) remains unactivated.
   - HDFC Infinia (`Disallow: /` in `robots.txt`) and Axis Atlas PDF T&C (`tnc_pdf`) remain on the manual capture / local `pdfplumber` worker path.

