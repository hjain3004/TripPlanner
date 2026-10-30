# FI3 — Human Review and Activation Dry-Run: Design

**Status:** design for implementation. Not implemented.
**Checked against:** `main` at `6f0859b146f69d0a6f55e3a3c9ac1146353f455e` (PR #20, FI2 parser and
PDF hardening, merged on top of PR #19 `3471747`). The first version (2026-10-26) was written
against `c925d98` and is superseded by this revision (2026-10-29).
**Authority:** implements the FI3 row of
[`2026-10-07-robust-financial-ingestion.md` §13](../plans/2026-10-07-robust-financial-ingestion.md#13-implementation-sequence-and-gates)
under [spec 05](../../specs/05_ingestion_pipeline_phase2.md) and
[spec 06](../../specs/06_implementation_protocol.md). Specs win over this document.
**Implementation plan:** [`2026-10-26-fi3-review-activation-dry-run.md`](../plans/2026-10-26-fi3-review-activation-dry-run.md)

## 1. Outcome

A named local curator:
1. opens a real stored FI2 proposal;
2. inspects the current row, the proposed row, field diffs, and the exact quoted evidence, with
   hashes and lineage;
3. approves, edits, rejects, or re-verifies it;
4. restarts the review server and reopens the durable result;
5. exports a deterministic activation bundle with an in-memory dry-run against the current seeds.

**Nothing is applied to the KB.** FI3 never writes `backend/core/seeds/`, the KB SQLite file,
goldens, `contract/openapi.json`, or `frontend/`.

**Who benefits:** this is an operator tool, not a traveler-facing feature. Travelers see no
change until a later, separately approved apply step (FI5) exists.

**Demo inputs:** a demo stores proposals by running the real FI2 path offline:
`ManualUploadBackend` → `SnapshotService` → `FinancialExtractor`, with a scripted extractor
response and synthetic capture text, against the real seed rows. These are synthetic inputs, not
verified issuer data, so every demo bundle entry stays `manual_curation` and unverified.

## 2. What `main` provides, and what FI3 changes

### 2.1 Reused as-is

| Interface on `6f0859b` | FI3 use |
|---|---|
| `ingestion.validation.validate_extraction(*, response, target_table, target_id, current_row, current_row_hash, snapshot, artifacts, now, extractor_version, manual_capture=False)` | The only validator for curator edits. Through it, edits get deterministic parsing (`parse_field_value`), quote-support checks (`_quote_supports_value`), schema validation, and the blocking sanity rules (`invalid_confidence`, `implausible_forex_markup`, `currency_country_mismatch`, `implausible_rate`, `non_positive_rate`, `ambiguous_discount`, ...) |
| `ingestion.validation._row_hash(row)`: SHA-256 of `json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)` | The single canonical row hash. FI3 exposes it under a public name and does not reimplement it. |
| `ingestion.evidence.verify_evidence_span(span, *, snapshot, artifacts)` | Re-verifies evidence on every view, decision, and bundle. PDF spans go through the process-isolated runner (§5.2). |
| `ingestion.pdf_isolation.PdfProcessRunner`, `use_runner` | The review server bounds PDF verification time with these; there is no second PDF path |
| `ingestion.extraction.FinancialExtractor` (one call, request-fingerprint replay via `create_proposal_with_fingerprint`) | Produces the stored proposals the curator reviews, including in the demo |
| `ingestion.storage.FinancialIngestionStore`: `create_proposal*`, `get_proposal`, `get_snapshot`, `latest_snapshot`, `list_decisions`, `list_audit_events`, `decide_proposal` (FI0 CAS + request fingerprint) | Queue, CAS, idempotency, audit |
| `ingestion.artifacts.ContentAddressedStore.read/put` | Reads by verified digest only; holds bundle blobs |
| `core.models` (`Card`, `RewardRule`, `Offer`, `PointValuation`), `core.db.SEEDS_DIR`, `KnowledgeBase.from_models` | Current-row truth (read only) and the in-memory dry-run |

PR #19 and PR #20 already fixed the parser and PDF issues; FI3 does not repeat or re-audit them.
- Malformed thousands grouping is rejected.
- Oversized numbers and Decimal scaling failures become `UnresolvedValueError`.
- Text dates must be exact `YYYY-MM-DD`.
- Negative amounts are rejected before rounding.
- PDF parsing runs in a killable child process under a deadline.

### 2.2 Storage concerns reproduced on `6f0859b`

Reproduced with a scratch script against an archive of `6f0859b` and the FI0 test fixtures; no
repository file was changed. FI3 fixes only these.

| # | Observed on `6f0859b` | Where | FI3 fix |
|---|---|---|---|
| S1 | `decide_proposal(status=EDITED, edits={"annual_fee_minor": 1})` stores an arbitrary edit with no evidence or parsing | `storage.py` `_decide_proposal` | Edits are created only by the review service through `validate_extraction`. The bundle builder recomputes and refuses any edited decision without a matching attestation. |
| S2 | Re-deciding an `edited` or `reverify` proposal passes the status check but raises a raw `sqlite3.IntegrityError` from `UNIQUE(review_decisions.proposal_id)` | `storage.py:495`, `:72` | Only `pending` is decidable; a decided proposal raises `AlreadyDecidedError` |
| S3 | After a reopen, the default counter gave a new decision the ID `audit-1`, already used by an audit event. A colliding decision ID raises a raw `IntegrityError`. | `storage.py:105` | Default IDs come from `uuid4` |
| S4 | With an ID factory that keeps returning an existing audit ID, `_audit` loops forever | `storage.py:184` | Retries are bounded (3), then raise `IngestionStoreError`. Only reachable with an injected factory, so this is a minor fix. |
| S5 | `put_reverify_task` runs in its own transaction, separate from the decision | `storage.py:568` | The decision and its reverify task commit in one transaction |
| S6 | `validate_extraction` skips the stale-row check when `current_row_hash is None` | `validation.py:331` | The review service blocks approve/edit with `unbound_base_row`; FI2 itself is unchanged |

**Schema:** `SCHEMA_VERSION` is **3** on `main`; version 3 added
`change_proposals.request_fingerprint`. FI3's migration is therefore **version 4**.

## 3. Process and contract boundary

```text
  product: api.main:app ──(contract/openapi.json, spec 12)──> frontend/        [unchanged]

  operator, loopback only:
  python -m ingestion.review_server serve ──> ingestion.review_app (FastAPI, 127.0.0.1/::1)
        ├─ ingestion.review       (context, findings, decisions, edits)
        ├─ ingestion.activation   (bundle, in-memory dry-run)
        ├─ ingestion.review_html  (escaped server HTML, no JavaScript)
        └─ FinancialIngestionStore + ContentAddressedStore + seeds (read only)
```

- **Why separate.**
  - Spec 05 §6 asks for a minimal FastAPI curator page.
  - Spec 12 §1 makes `api.main:app`'s schema the only product contract.
  - Mounting curator routes there would put approval authority on the public surface and force
    operator routes into OpenAPI, codegen, and MSW.
  - The FI0 AST test already forbids `api/` from importing `ingestion/`.
- **Boundaries that tests pin:**
  - `api.main.app.openapi()` has no `/review` path, and `contract/openapi.json` is unchanged.
  - `deploy/` and `backend/Dockerfile` never reference the review server.
  - The review app's route set equals an exact allowlist, and `openapi_url`, `docs_url`, and
    `redoc_url` are disabled.
- **Local-only guards:**
  - It binds to `127.0.0.1` or `::1` only, and refuses `TRIPWISE_ENV=production`.
  - The data directory must be outside the Git work tree.
  - A `Host` header other than a loopback name with the configured port gets 400, which blocks
    DNS rebinding.
  - uvicorn runs with `access_log=False`, `server_header=False`, and `proxy_headers=False`.
- **Moving the UI into `frontend/` would be a new decision** following the spec 12 §8 one-PR
  rule. The separate app is recorded in `DEVIATIONS.md`, as an FI3 planning entry.

## 4. Curator identity, sessions, and CSRF

No new authentication dependency, and no accounts linkage; spec 17 defines no curator role.

- **Registry.** An insert-only `curators` table holds `CuratorRecord{curator_id, display_name,
  created_at}`. The handle matches `^[a-z0-9][a-z0-9-]{1,31}$`. Records are created with the
  `add-curator` CLI subcommand.
- **Launch token.** `serve --curator-id X` refuses an unregistered X. It prints a single-use login
  token to stderr: 32 random bytes, 10-minute lifetime, entered through a POST form only, and held
  in memory as a SHA-256. Five failed attempts invalidate it.
- **Session.** The token is exchanged for an in-memory session with a 30-minute idle and 8-hour
  absolute limit.
  - Cookie `fi3_review_session`: `HttpOnly`, `SameSite=Strict`, `Path=/review`, host-only, without
    `Secure` (it is loopback HTTP).
  - A restart ends every session. The reviewer ID always comes from the session.
- **CSRF.** Each POST must pass two checks.
  - Its `Origin` must be one of the configured loopback origins; a missing or `null` Origin is
    refused.
  - It must carry a per-session synchronizer token in a hidden field, compared in constant time.
    The token is never a cookie.
- **Headers:**
  - `Content-Security-Policy: default-src 'none'; style-src 'self'; img-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'`;
  - `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
    `Cache-Control: no-store`.

## 5. Review context

`ReviewService.context(proposal_id)` is built on every view and again inside every decision.

### 5.1 Contents

- **Rows.**
  - The current row is `Model.model_validate(seed_row).model_dump(mode="json")`, read from the
    seed YAML.
  - The proposed row and, when edited, the edited row are shown alongside it.
  - Field diffs use dotted paths, matching FI2's flattening.
- **Evidence.**
  - Each span is shown with 240 escaped characters on either side, its PDF page, and the
    snapshot's `raw_sha256` and `normalized_sha256`.
  - The span's freshly re-run `verify_evidence_span` result is shown with its message.
  - Bidi and zero-width characters (U+200B–U+200F, U+202A–U+202E, U+2066–U+2069, U+FEFF), and C0
    controls other than tab and newline, appear as visible `⟦U+XXXX⟧` markers.
  - There is no rendered HTML view. Raw text is shown escaped, at most 256 KiB, and never for PDFs.
- **Lineage:** source policy → watch target → snapshot(s) with attempts → supersession chain (at
  most 50 steps), plus the target's latest snapshot ID.
- **Computed findings**, never written back to the immutable proposal:

| Code | Severity | Condition |
|---|---|---|
| `stored_blocking_finding` | blocking | The proposal has a stored `blocking` finding |
| `unsupported_target_table` | blocking | The table is outside `cards`, `reward_rules`, `offers`, `point_valuations` (D4) |
| `current_row_missing` | blocking | The target ID is absent or duplicated in the seeds |
| `unbound_base_row` | blocking | `proposal.current_row_hash is None` (S6) |
| `current_row_changed` | blocking | The canonical hash of the current row ≠ `proposal.current_row_hash` |
| `evidence_integrity_failed` | blocking | A span fails `verify_evidence_span`, or a lineage snapshot is missing; the verifier's message is kept |
| `evidence_superseded` | blocking | The target's latest snapshot differs from the lineage snapshot and has a different `normalized_sha256` |
| `multi_snapshot_lineage` | blocking for **edit** | `len(lineage_ids) != 1`; FI2 always emits one |
| `pdf_verification_unavailable` | blocking | The snapshot is a PDF and `pdfplumber` is not importable by the server's interpreter (§5.2) |
| `manual_capture` | warning | The watch target is `manual_capture`; check for personal data |
| `attribution_required` | warning | The source policy requires attribution |

Approve and edit are refused while any blocking finding exists. Reject and reverify are always
allowed, so that a broken proposal can still be closed.

### 5.2 Bounded PDF verification

These facts are measured on `main`, not designed by FI3:
- PDF span verification starts one child process per span. It is **synchronous**: the calling
  thread blocks until the child replies or the deadline kills it.
- Defaults are `DEFAULT_TIMEOUT_SECONDS = 30.0` and `DEFAULT_MAX_CONCURRENT = 2` across the
  process.
- A timeout, a missing `pdfplumber`, a crash, or an unreadable PDF all become
  `EvidenceVerificationError("PDF evidence could not be verified")`. An out-of-range page and a
  missing quote have their own messages.
- The optional `ingestion-local` extra (`pdfplumber>=0.11,<1`) is **not installed** in the
  project environment. PR #20 exercised the runner only with a synthetic `pdfplumber` double; the
  real library has never run.

FI3 consumes this without building a second validator:
1. **Runner.** `serve` wraps the app in `use_runner(PdfProcessRunner(default_timeout_seconds=10.0))`
   (a settled default; see §11). One PDF span therefore blocks a request thread for at most about
   10 s. FastAPI runs the
   synchronous handlers in its thread pool, so the event loop is not blocked.
2. **Per-request memo.** Within one context build, an identical `(snapshot_id, page_number,
   quote)` is verified once. Nothing is cached across requests or decisions.
3. **Availability.** At start-up, `importlib.util.find_spec("pdfplumber")` determines whether PDF
   verification can work. If not, PDF proposals show the blocking `pdf_verification_unavailable`
   finding, instead of an opaque timeout-style failure.
4. **Fail closed.** A PDF span that fails verification blocks approve/edit, and the bundle builder
   refuses the entry. Text and HTML proposals are unaffected.

## 6. Decisions

### 6.1 Request

`DecisionRequest{proposal_id, action ∈ approve|edit|reject|reverify, reason (1–1000),
expected_version, client_event_id, curator_confidence, edits}`

- The server generates `client_event_id` when it renders the form; re-submitting the same form
  replays the same request.
- `curator_confidence` is required for approve and edit (0.00–1.00, two decimals), and forbidden
  otherwise.
- **Fingerprint.** FI0's `_fingerprint_request` gains `curator_confidence` only when it is not
  `None`, so every existing fingerprint is unchanged. Edits are JSON-native and sorted by
  `field_path`.

### 6.2 Semantics

Every outcome is terminal (fixes S2).

| Action | Precondition | Effect, in one `BEGIN IMMEDIATE` transaction |
|---|---|---|
| approve | Status `pending`; no blocking finding; no edits | Decision `approved` with attestation; proposal `approved`, version + 1; audit `decision` |
| edit | As approve, plus at least one valid edit; edited row ≠ proposed row ≠ current row | Decision `edited` with typed edits and attestation |
| reject | Status `pending` | Decision `rejected` |
| reverify | Status `pending` | Decision `reverify`, plus `ReverifyTask(task_id="reverify:{proposal_id}", target_id=<lineage snapshot's watch target>, priority="normal", prior_evidence_ids=lineage_ids, due_at=now)` in the **same** transaction (fixes S5). A new snapshot then yields a new proposal. |

`edited` means "approved with edits", spec 05's status.

### 6.3 Edits are revalidated by FI2's own validator

`CuratorFieldEdit{field_path, action ∈ set|revert, proposed_raw_value, quote, occurrence,
snapshot_id, page_number}`

- **`revert`** restores the current value; no evidence is needed.
- **`set`** requires `snapshot_id` to be the proposal's single lineage snapshot.
  - The server finds `quote` in that snapshot's `canonical_markdown` (`occurrence`, counted from
    1, is required if the quote is ambiguous) and derives the offsets.
  - It builds an `EvidenceSpan(verification="exact")`, with `page_number` if and only if the
    snapshot is a PDF.
- Only one FI3-specific rule applies: `field_path` may not be `id` or start with `provenance`,
  because activation owns provenance.
- **Revalidation.** FI3 builds an `ExtractionResponse`-shaped dict (the edited row, the surviving
  FI2 fields, the `set` edits, and `extractor_confidence=0.0`). It then calls
  `validate_extraction(..., current_row=<seed row>, current_row_hash=proposal.current_row_hash,
  snapshot=<lineage snapshot>, manual_capture=<page kind is manual_capture>)`.
  - That single call applies parsing, the quote-support check, schema validation, and the sanity
    rules, as on `main`.
  - A `ProposalValidationError`, or any blocking finding in the result, refuses the edit with
    `invalid_edit` and the validator's message.
  - FI3 adds no separate value-in-quote rule or type rule; the first revision's D10 is resolved by
    `_quote_supports_value` on `main`.

### 6.4 Attestation, concurrency, replay

`ReviewAttestation{proposal_payload_sha256, current_row_sha256, resulting_row_sha256 | None,
evidence: (EvidenceDigest{snapshot_id, raw_sha256, normalized_sha256}, ...),
computed_finding_codes}`

The attestation is stored as an optional, additive field on `ReviewDecision`.
- **Check order** inside `BEGIN IMMEDIATE`: idempotent replay → version CAS → terminal status →
  edit/status shape → the existing blocking/lineage checks → re-hash of the stored proposal
  payload against the attestation. A mismatch raises `StaleVersionError`.
- **Concurrent reviewers:** exactly one wins; the other gets HTTP 409 and a link to the fresh
  state.
- **Replay after restart:** the same `client_event_id` and fingerprint return the original
  decision with no new audit event. A different fingerprint raises `IdempotencyConflictError`.
  An old form fails CSRF after a restart.
- **IDs:** `uuid4` default IDs (S3) and bounded audit retry (S4).
- **Seed-file race.** A seed edit made between the check and the write is not locked; the bundle
  rechecks the row hash.

### 6.5 Failed operations roll back

- A decision, its audit event, and any reverify task commit together or not at all.
- A bundle blob is written before its SQLite row. A failed row insert leaves only an unreferenced
  content-addressed blob, and a retry is idempotent.

## 7. Activation bundle and dry-run

### 7.1 The bundle never authorizes activation

`ActivationPlanner.build(proposal_ids | None, curator_id, client_event_id)` re-verifies each
selected approved or edited decision from scratch:
- the attestation is present;
- the proposal payload hash matches;
- every evidence span verifies;
- for edits, the recomputed edited row hashes to `resulting_row_sha256`;
- the current seed row hash equals both `proposal.current_row_hash` and the attestation's;
- the table is supported;
- the target is unique among the selected proposals.

Failures become `RefusedEntry{proposal_id, code, message}`. Two approved proposals for one target
refuse **both**. A decision written directly through `decide_proposal` with no attestation is
refused (S1).

| Field | Content |
|---|---|
| `schema_version` | `"tripwise.financial-activation-bundle/v1"` |
| `activation_authorized` | Always `false` in v1. FI3 approvals are review decisions, not authorization to apply. |
| `unresolved_decisions` | `["D1", "D2"]` while those decisions are open |
| `seed_files` | Sorted `{filename: sha256}` for each consulted seed file |
| `entries` | Sorted by `(target_table, target_id)` |
| `refused` | Sorted by `proposal_id` |
| `dry_run_consistent` | `refused == ()`. This is internal consistency only, not readiness to apply. |

Each entry holds:
- `base_row_sha256`;
- `new_row` and `new_row_sha256`;
- `field_changes`;
- `evidenced_fields` and `unevidenced_fields`;
- `proposal_id` and `proposal_payload_sha256`;
- `decision_id`, `decision_status`, `reviewer_id`, `decided_at`;
- the `evidence` digests;
- `source_url`, `source_type`, `attribution_required`;
- `provenance_candidate`;
- `blocked_by`.

**Provenance is not silently resolved.**
- `new_row.provenance` is the **current row's provenance, unchanged**: FI3 never upgrades trust
  in `new_row`.
- `provenance_candidate` records what spec 05 would write: `source_type`, `verified_by`
  (the reviewer), `last_verified` (the UTC date of `decided_at`), `source_url` (the attempt's
  final URL, or the watch target's canonical URL), and `confidence` (the curator's).
  `needs_verification` is `null`, because D1 must decide it.
  - Card and offer pages map to `official_page`; T&C PDFs map to `tnc_pdf`.
- **Manual captures:** the candidate's `source_type` is `manual_curation`, and the entry carries
  `blocked_by: ["D2"]`.
- **Every entry** carries `blocked_by: ["D1"]` while D1 is open, listing the fields that
  row-level provenance would cover without quoted evidence.

**Determinism.**
- The bundle bytes are `json.dumps(model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
  ensure_ascii=False).encode()`.
- The bundle ID is the SHA-256 of those bytes.
- No wall-clock value appears inside the hashed body; `created_at` and `created_by` live in the
  audit event only.
- **Persistence:** the blob goes into `ContentAddressedStore`, plus an insert-only
  `activation_bundles` row keyed by the bundle SHA-256.

### 7.2 Dry-run

`ActivationPlanner.dry_run(bundle_sha256)`:
- **Integrity first.** It verifies the stored blob's hash, then re-reads the seeds.
- **Per-entry status:** `would_update`, `stale` (the row hash or seed file hash changed),
  `row_missing`, or `invalid_row` (`Model.model_validate` fails).
- **In-memory overlay.** It overlays the new rows onto in-memory copies of the four supported
  tables, calls `KnowledgeBase.from_models(...)`, and checks the `card_id` / `card_ids`
  references.
- **No writes.** It reports `seed_files_unchanged`, never opens `core.db.DB_PATH`, never calls
  `seed_database` or `load_kb`, and writes no file.
- Goldens embed their own `kb:` blocks, so seed content cannot move a golden value. FI3 still
  proves seed, golden, and KB-DB bytes are unchanged after the full workflow.

## 8. Requirement → acceptance test map

Test names are from the plan.

| Requirement | Mechanism | Acceptance test(s) |
|---|---|---|
| Durable, auditable decisions | One transaction per decision + audit + task | `test_decision_rolls_back_when_audit_fails`, `test_reverify_task_commits_atomically_with_decision` |
| Terminal decisions, typed errors (S2) | `status == pending` only | `test_edited_and_reverify_are_terminal` |
| Restart-safe IDs (S3, S4) | uuid4; bounded retry | `test_ids_are_unique_across_reopen`, `test_audit_retry_is_bounded` |
| Idempotency and replay after restart | Fingerprint in SQLite | `test_replay_after_restart_returns_original_decision`, `test_resubmitted_form_replays_original_decision` |
| Concurrent reviewers | CAS + in-transaction attestation hash | `test_two_connection_race_has_exactly_one_winner`, `test_stale_form_after_other_reviewer_gets_409` |
| Edits cannot bypass validation (S1) | FI2 `validate_extraction` | `test_edit_goes_through_fi2_validation`, `test_unsupported_edit_is_refused_by_fi2`, `test_raw_store_decision_without_attestation_is_refused` |
| Stale approvals fail (S6) | Computed findings; bundle recheck | `test_unbound_base_row_blocks_approve`, `test_seed_change_after_proposal_is_current_row_changed`, `test_seed_edit_after_bundle_reports_stale` |
| Evidence tampering | Re-verify on view, decision, and bundle; payload hash | `test_tampered_blob_is_evidence_integrity_failed`, `test_proposal_payload_tamper_is_refused` |
| Bounded PDF verification | Runner tuning; per-request memo; availability finding | `test_pdf_span_verifies_through_runner_double`, `test_hung_pdf_span_blocks_within_deadline`, `test_pdf_without_pdfplumber_is_blocked_explicitly` |
| Manual provenance; D1/D2 unresolved | `provenance_candidate`; `blocked_by`; unchanged `new_row.provenance` | `test_bundle_does_not_resolve_provenance_decisions`, `test_manual_capture_entry_is_blocked_by_d2` |
| Determinism | Canonical bytes | `test_bundle_is_byte_deterministic_across_restart_and_clock` |
| No KB mutation | AST + byte hashes | `test_dry_run_never_writes`, `test_end_to_end_operator_workflow_mutates_nothing` |
| Untrusted HTML/script | Escaping via `h()`; CSP; no script | `test_hostile_content_is_escaped`, `test_bidi_and_zero_width_are_visualized` |
| Path traversal | IDs as exact lookups; digest-only reads | `test_ids_are_exact_lookups_not_paths`, `test_relative_path_is_never_used` |
| Local only; CSRF | Bind/Host/Origin/token guards | `test_dns_rebinding_host_is_rejected`, `test_post_requires_loopback_origin_and_csrf`, `test_non_loopback_bind_is_refused` |
| Product isolation | No `/review` route; deploy untouched | `test_product_api_has_no_review_surface`, `test_deploy_files_never_reference_the_review_server` |

## 9. Privacy

- Curator records hold a handle and a display name only. They are operator audit records outside
  spec 17's export/delete scope. FI3 has no delete, because deletion would break the audit trail.
- Manual captures show a warning to check for personal data.
- Error pages show typed codes only. No request bodies or snapshot text are logged, the access
  log is off, the login token never appears in a URL, and bundles never enter Git.

## 10. Non-scope

FI3 does not:
- apply bundles to seeds or the KB, or add any apply command;
- add Firecrawl, scheduling, or a staleness sweeper;
- promote evidence-graph claims;
- add metrics dashboards or discovery-candidate UI;
- support insert or delete operations;
- add a rendered HTML snapshot view, JavaScript, or a frontend change;
- change OpenAPI, accounts, deployment, or dependencies;
- install `pdfplumber`.

## 11. Remaining decisions

| ID | Question | FI3 behavior while open | Needed before |
|---|---|---|---|
| D1 | Spec 05 provenance is row-level and evidence is field-level. May an approval clear `needs_verification` for fields it never quoted? | Unresolved. `new_row.provenance` is unchanged; `provenance_candidate.needs_verification` is `null`; each entry lists `unevidenced_fields` and `blocked_by: ["D1"]`. | Any apply step (FI5) |
| D2 | May a manual capture become `official_page`/`tnc_pdf` once a curator confirms the primary URL? | No; the candidate stays `manual_curation` with `blocked_by: ["D2"]`. | FI5 |
| D3 | Is "local shell access plus a one-time token" an acceptable curator identity strength? | Yes, for the student profile | Human acknowledgement |
| D4 | Supported tables | `cards`, `reward_rules`, `offers`, `point_valuations`. Transfer tables are refused (fictional graph); FX is refused (no `id`, owned by G2). | Human, if FX or transfer facts are wanted |

Settled defaults, not open questions:
- The operator app is outside the product contract (logged in `DEVIATIONS.md`).
- There is no rendered snapshot view, no approval expiry, and no audit hash chain.
- The cookie has no `Secure` flag on loopback.
- The PDF timeout in the review server is 10 s.

The first revision's D10 is closed by `main`.

## 12. Re-check only if `main` advances

The plan's Task 0 compares current `main` with `6f0859b` for these paths only:
- `backend/ingestion/storage.py` and `migrations.py`
- `backend/ingestion/validation.py`
- `backend/ingestion/evidence.py` and `pdf_isolation.py`
- `backend/ingestion/parsing.py`
- `backend/ingestion/extraction.py`
- `backend/ingestion/contracts.py`

If none changed, implementation proceeds unchanged.

## 13. References

- [Spec 05](../../specs/05_ingestion_pipeline_phase2.md), [spec 06](../../specs/06_implementation_protocol.md),
  [spec 12](../../specs/12_integration_contract.md), [spec 17](../../specs/17_accounts_and_persistence.md)
- The development workflow guide, `docs/DEVELOPMENT_WORKFLOW.md`. It exists in the primary checkout
  and is not on this branch.
- [Robust financial ingestion plan](../plans/2026-10-07-robust-financial-ingestion.md)
- Reports on `main`: `reports/fi2_extraction_validation.md`,
  `reports/fi1_pdf_process_isolation.md`, `reports/fi2_parser_pdf_hardening.md`
