# FI3 — Human Review and Activation Dry-Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:executing-plans (one implementation
> owner). Steps use checkbox (`- [ ]`) syntax. Write each test before its code.

**Goal:** a named local curator can review real stored FI2 proposals, make durable,
validated decisions, and export a deterministic activation dry-run. Nothing is applied to the KB.

**Architecture:** flat modules in `backend/ingestion/` over the existing FI0–FI2 store, validator,
evidence verifier, and PDF runner.
- **Checkpoint A (Tasks 1–6)** delivers the workflow through an operator CLI, with no HTTP
  surface.
- **Checkpoint B (Tasks 7–9)** adds the loopback-only browser UI on the same service.

**Tech stack:** existing FastAPI/Starlette, uvicorn, Pydantic, and PyYAML, plus the stdlib.
**No new dependencies.**

**Spec:** [FI3 design](../specs/2026-10-26-fi3-review-activation-dry-run-design.md) (revision of
2026-10-29), with [spec 05](../../specs/05_ingestion_pipeline_phase2.md) and
[spec 06](../../specs/06_implementation_protocol.md).

**Reference revision:** `main` at `6f0859b146f69d0a6f55e3a3c9ac1146353f455e` (PR #20). Branch the
implementation from current `main`; this planning branch is documentation only.

## Global constraints

- No write to `backend/core/seeds/`, `backend/evals/golden/`, `core.db.DB_PATH`,
  `contract/openapi.json`, `frontend/`, `deploy/`, `docs/specs/`, `AGENTS.md`, or `CLAUDE.md`.
- No new dependency, no Jinja2, no `python-multipart`. Forms are parsed with
  `urllib.parse.parse_qs` over a body capped at 64 KiB.
- No network, LLM, crawler, or provider call. Tests block `socket.socket.connect` (FI0 pattern).
  `pdfplumber` is not installed; PDF tests use `backend/ingestion/fixtures/pdf_double` through
  `PdfProcessRunner(search_paths=[...])` and `use_runner`.
- New modules are flat files in `backend/ingestion/`, so the existing FI0 AST boundary test
  covers them. `api/`, `core/`, and `agents/` never import `ingestion`.
- FI3 computes no financial value. Edited values are parsed only by FI2's `validate_extraction`.
- Supported tables: `cards`, `reward_rules`, `offers`, `point_valuations`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Verification cadence

- **Per task:** run that task's new tests plus the FI0–FI2 ingestion tests it can affect.
  `mypy --strict ingestion/` and `ruff check ingestion/ <new test files>` run before each commit.
- **Checkpoint A (end of Task 6):** run the CLI demonstration, then `make gate` once.
- **Checkpoint B (end of Task 9):** run the browser/HTTP demonstration, then `make gate` once on
  the exact final tree.
- **Review:** one independent review of the completed change, after Checkpoint B (or after A if
  delivery stops there). Not one per task.

## Review focus

Each of these is owned by the task shown.

1. **A `None` base hash.** A proposal with `current_row_hash=None` must not be approvable (Task 3).
2. **Invisible characters in a quote.** Bidi or zero-width characters must be visible to the
   curator (Task 7).
3. **Two approvals for one target** in a bundle refuse both (Task 5).
4. **A browser double-submit** replays the original decision instead of creating a second one
   (Task 8).
5. **A hand edit to a seed** after bundling reports `stale` (Task 5).

---

## File map

| Path | Change | Task |
|---|---|---|
| `backend/ingestion/contracts.py` | Add `EvidenceDigest`, `ReviewAttestation`, `CuratorRecord`; add optional `ReviewDecision.curator_confidence` and `.attestation` | 1 |
| `backend/ingestion/migrations.py` | `SCHEMA_VERSION = 4` (`main` uses 3) | 1 |
| `backend/ingestion/storage.py` | Fixes S2–S5; curator, watch-target, policy, proposal-list, and reverify-task reads; bundle rows | 1, 5 |
| `backend/ingestion/validation.py` | Public alias `canonical_row_hash` for `_row_hash`; no behavior change | 2 |
| `backend/ingestion/review_rows.py` | `SUPPORTED_TABLES`, `SeedRowSource` (read only), `flatten_row` | 2 |
| `backend/ingestion/review_types.py` | Finding codes, DTOs, `CuratorFieldEdit`, `DecisionRequest` | 3, 4 |
| `backend/ingestion/review.py` | `ReviewService`: context, findings, edits, decisions | 3, 4 |
| `backend/ingestion/activation.py` | Bundle models, `canonical_bundle_bytes`, `ActivationPlanner` | 5 |
| `backend/ingestion/review_server.py` | Operator CLI (Task 6), then `serve` (Task 8) | 6, 8 |
| `backend/ingestion/fixtures/fi3_demo/` | Synthetic capture texts and scripted extractor responses for the four seeded cards | 6 |
| `backend/ingestion/review_html.py` | Escaped pages | 7 |
| `backend/ingestion/review_app.py` | Loopback FastAPI app, sessions, CSRF, routes | 8 |
| `backend/evals/fi3_fixtures.py` | Builds a runtime through the real FI2 path with temporary seed copies | 2 |
| `backend/evals/test_fi3_*.py` | One file per task (named below) | 1–9 |
| `reports/fi3_review_activation_dry_run.md`, `DEVIATIONS.md` (append) | Milestone report and implementation deviations | 6, 9 |

---

### Task 0: Confirm the reference

- [ ] Run `git fetch origin`. If `origin/main` ≠ `6f0859b`, run
  `git diff 6f0859b origin/main -- backend/ingestion/`. Update an affected task's Interfaces block
  only if a listed signature changed. If `SCHEMA_VERSION` is no longer 3, take the next free
  version.
- [ ] Create the implementation worktree from `origin/main`, run `make seed PY=.venv/bin/python`,
  and run the FI0–FI2 tests:
  `.venv/bin/pytest -q evals/test_fi0_ingestion.py evals/test_fi1_snapshot_core.py evals/test_fi1_pdf_isolation.py evals/test_fi2_extraction.py`.
  Expected: all pass.

### Task 1: Storage fixes and schema 4

**Files:** `contracts.py` (after `ReviewDecisionStatus`, line 297); `migrations.py`; `storage.py`:
- `_SCHEMA` lines 47–85;
- `_next_id` line 105;
- `_fingerprint_request` line 127;
- `_audit` lines 175–202;
- `_decide_proposal` lines 454+ (status check at line 495);
- `put_reverify_task` line 568.

**Test file:** `backend/evals/test_fi3_storage.py`, reusing the FI0 fixtures `policy`, `target`,
`snapshot`, `proposal`, and `NOW` from `evals/test_fi0_ingestion.py`.

**Interfaces (produces):**
- `EvidenceDigest(frozen)`: `snapshot_id`, `raw_sha256`, `normalized_sha256` (SHA256 pattern).
- `ReviewAttestation(frozen)`: `proposal_payload_sha256`, `current_row_sha256`,
  `resulting_row_sha256: str | None`, `evidence: tuple[EvidenceDigest, ...]` (min 1),
  `computed_finding_codes: tuple[str, ...] = ()`.
- `CuratorRecord(frozen)`: `curator_id` (pattern `^[a-z0-9][a-z0-9-]{1,31}$`),
  `display_name` (1–80), `created_at: AwareDatetime`.
- `ReviewDecision` gains `curator_confidence: float | None = Field(None, ge=0, le=1)` and
  `attestation: ReviewAttestation | None = None`.
- `class InvalidDecisionError(IngestionStoreError)`.
- `proposal_payload_sha256(payload_json: str) -> str`.
- `decide_proposal(...)` gains the keyword arguments `curator_confidence=None`,
  `attestation=None`, and `reverify_task: ReverifyTask | None = None`.
- `put_curator(CuratorRecord) -> CuratorRecord` (insert-only; replay OK; a conflict raises
  `ConflictingWriteError`).
- `get_curator(id)`, `get_watch_target(id)`, `get_source_policy(id)`,
  `list_proposals(*, status=None)` (ordered by `created_at`, `id`), and `get_reverify_task(id)`.
- The schema-4 DDL adds `curators(id PK, payload)` and `activation_bundles(id PK,
  client_event_id UNIQUE, request_fingerprint, payload)`.

**Behavior:**
- Only `pending` proposals are decidable (`AlreadyDecidedError`).
- Check order: replay → CAS → terminal → shape → existing blocking/lineage checks → attestation
  payload hash.
- Shape rules, which raise `InvalidDecisionError`: `EDITED` requires non-empty `edits`; other
  statuses require none; `reverify_task` is required if and only if the status is `REVERIFY`.
- The reverify task is inserted on the same connection, with event ID `client_event_id + ":task"`.
- `_next_id` returns `f"evt-{uuid.uuid4().hex}"`, and `_audit` retries at most 3 times.
- The fingerprint includes `curator_confidence` only when it is not `None`.

- [ ] **Write the tests:**
  - `test_edited_and_reverify_are_terminal`: a second decision raises `AlreadyDecidedError`, not
    `sqlite3.IntegrityError`.
  - `test_edit_shape_is_structural`.
  - `test_attestation_hash_mismatch_is_stale`: the version stays 1.
  - `test_reverify_task_commits_atomically_with_decision`: monkeypatch `_audit` to fail on the
    task event, then assert there is no decision row, the proposal is still `pending` at version
    1, and there is no task.
  - `test_decision_rolls_back_when_audit_fails`.
  - `test_ids_are_unique_across_reopen`: no decision ID equals an audit event ID.
  - `test_audit_retry_is_bounded`: an `IngestionStoreError` within 1 s.
  - `test_confidence_fingerprint_is_additive`: the existing FI0 fingerprint is unchanged.
  - `test_schema_4_migrates_a_schema_3_database`: create the database with `main`'s
    `FinancialIngestionStore`, then reopen it; existing rows are unchanged and
    `user_version == 4`.
  - `test_two_connection_race_has_exactly_one_winner`.
- [ ] **Verify:** run them; they fail. Implement, then rerun with the FI0–FI2 tests. Expected: all
  pass.
- [ ] **Commit:** `fix(fi3): terminal decisions, attestation, atomic reverify, restart-safe ids`

### Task 2: Read-only seed rows and the canonical hash

**Files:** `validation.py` (add `canonical_row_hash = _row_hash`); `review_rows.py`;
`backend/evals/fi3_fixtures.py`; `backend/evals/test_fi3_review_rows.py`.

**Interfaces (produces):**
- `SUPPORTED_TABLES`: `{table: (yaml_name, Model)}` for the four tables.
- `class SeedRowError(ValueError)` with `.code` set to one of `unsupported_target_table`,
  `current_row_missing`, or `duplicate_row_id`.
- `SeedRowSource(seeds_dir)`:
  - `.current_row(table, id) -> dict`, as `model_validate(...).model_dump(mode="json")`;
  - `.table_rows(table)`;
  - `.seed_file_sha256(table)`.
- `flatten_row(row) -> dict[str, Any]`, with dotted paths.
- In `fi3_fixtures`:
  - `write_seeds(dir, *, cards=None) -> Path`, which copies the four real seed files.
  - `build_runtime(tmp_path, *, snapshot_text=..., pdf: bool = False,
    page_kind="card_page", bind_base_row: bool = True) -> Fi3Runtime`. It creates the policy, the
    target, a snapshot through `SnapshotService.capture`, and a proposal through
    `FinancialExtractor` with `ScriptedLLMClient`. The current row comes from `SeedRowSource`, with
    `current_row_hash=canonical_row_hash(row)` or `None`.
  - `Fi3Runtime` fields: `store`, `artifacts`, `rows`, `seeds_dir`, `snapshot`, `proposal`, `now`.

- [ ] **Tests:**
  - `test_canonical_row_hash_is_fi2_hash` (`canonical_row_hash is _row_hash`).
  - `test_current_row_is_model_normalized_json`.
  - `test_unsupported_missing_and_duplicate_rows_have_typed_codes`.
  - `test_seed_source_never_writes`.
- [ ] Implement, run, and commit: `feat(fi3): read-only seed rows and canonical row hash`.

### Task 3: Review context, findings, and bounded PDF verification

**Files:** `review_types.py`, `review.py`, `backend/evals/test_fi3_review_service.py`.

**Interfaces (produces):**
- `FindingCode(StrEnum)`, with the design §5.1 codes plus `UNKNOWN_CURATOR`, `INVALID_EDIT`, and
  `NO_EFFECTIVE_EDIT`.
- `ComputedFinding(code, severity, message, field_path=None)`.
- `FieldDiff(field_path, current, proposed, edited, changed, evidence)`.
- `EvidenceContext(span, before, after, verified, failure)`.
- `LineageView(source_policy, watch_target, snapshots, supersession_chain, latest_snapshot_id)`.
- `ReviewContext(...)`, with `blocking_for_approval` and `blocking_for_edit`.
- `ReviewRefusedError(findings)`.
- `ReviewService(*, store, artifacts, rows, now, pdf_verification_available: bool,
  evidence_verifier=verify_evidence_span)`, with:
  - `.list_queue(status=PENDING)`;
  - `.context(proposal_id)` (raises `KeyError` if unknown).

**Behavior:**
- Evidence failures (`EvidenceVerificationError`, `ArtifactIntegrityError`, `FileNotFoundError`)
  become `evidence_integrity_failed` and keep the message.
- Identical `(snapshot_id, page_number, quote)` spans are verified once per `context()` call.
- With `pdf_verification_available=False`, PDF snapshots get `pdf_verification_unavailable` and
  no child process starts.

- [ ] **Tests:**
  - `test_context_shows_rows_diffs_evidence_hashes_and_lineage`.
  - `test_unbound_base_row_blocks_approve` (`bind_base_row=False`).
  - `test_seed_change_after_proposal_is_current_row_changed`.
  - `test_tampered_blob_is_evidence_integrity_failed`.
  - `test_newer_different_snapshot_is_evidence_superseded`.
  - `test_unsupported_table_and_missing_row_are_blocking`.
  - `test_manual_capture_and_attribution_are_warnings_only`.
  - `test_relative_path_is_never_used`: a tampered `relative_path` still reads by digest, and
    every read stays under the artifacts root or the seeds directory.
  - `test_pdf_span_verifies_through_runner_double`: use
    `use_runner(PdfProcessRunner(search_paths=[pdf_double]))`.
  - `test_hung_pdf_span_blocks_within_deadline`: a `hang-sleep` double with a 0.5 s runner timeout
    yields `evidence_integrity_failed` in under 3 s, and the child is gone.
  - `test_pdf_without_pdfplumber_is_blocked_explicitly`: no child process is spawned.
- [ ] Implement, run, and commit: `feat(fi3): review context with re-verified evidence and bounded PDF checks`.

### Task 4: Decisions and validated edits

**Files:** `review_types.py`, `review.py`, and `test_fi3_review_service.py` (append).

**Interfaces (produces):**
- `CuratorFieldEdit(frozen, extra="forbid")`:
  - fields: `field_path`, `action: set|revert`, `proposed_raw_value`, `quote`, `occurrence`,
    `snapshot_id`, `page_number`;
  - `set` requires the raw value, quote, and snapshot ID; `revert` forbids all of them.
- `DecisionRequest(extra="forbid")`:
  - fields: `proposal_id`, `action`, `reason` (1–1000), `expected_version`,
    `client_event_id` (`^[A-Za-z0-9_-]{16,64}$`), `curator_confidence`, `edits`;
  - confidence is required if and only if the action is approve or edit (two decimals); edits are
    non-empty if and only if the action is edit; field paths are unique.
- `ReviewService.apply_edits(ctx, edits) -> tuple[dict, ChangeProposal]`.
- `ReviewService.edits_payload(edits) -> {"fields": [...sorted]}`.
- `ReviewService.decide(request, *, curator_id) -> ReviewDecision`.

**Behavior:**
- `apply_edits` builds the response dict from the surviving FI2 fields plus the edits, then calls
  `validate_extraction`.
- A `ProposalValidationError`, or a blocking finding in the result, becomes `INVALID_EDIT` with
  the validator's message.
- Paths of `id` or `provenance*` are refused. There is no other FI3 value rule.

- [ ] **Tests:**
  - `test_approve_records_attestation_and_named_reviewer`.
  - `test_unknown_curator_is_refused`.
  - `test_blocking_findings_refuse_approve_and_edit_but_allow_reject_and_reverify`.
  - `test_edit_goes_through_fi2_validation`. The snapshot is
    `"Annual fee is INR 12,500. Joining fee INR 12,000."`, and the edit sets `annual_fee_minor` to
    `"INR 12,000"` quoted from the second sentence. Expect `edited["annual_fee_minor"] ==
    1200000`, and that the attestation's resulting hash equals `canonical_row_hash(edited)`.
  - `test_unsupported_edit_is_refused_by_fi2`. Refusals expected:
    - a raw value the quote does not support (`_quote_supports_value`);
    - a non-ISO date;
    - an oversized number;
    - a list field;
    - a quote absent from the snapshot;
    - an ambiguous quote with no occurrence.
  - `test_edit_cannot_touch_id_or_provenance`.
  - `test_edit_introducing_blocking_sanity_is_refused`: `forex_markup_bp` 600 is refused.
  - `test_revert_all_or_no_effective_edit_is_refused`.
  - `test_reverify_creates_task_for_watch_target_atomically`.
  - `test_replay_after_restart_returns_original_decision`: a new store and service on the same
    files give an equal decision, still one audit `decision` event; a changed reason raises
    `IdempotencyConflictError`.
  - `test_concurrent_reviewers_one_wins`.
- [ ] Implement, run, and commit: `feat(fi3): validated curator decisions and edits`.

### Task 5: Activation bundle and in-memory dry-run

**Files:** `activation.py`, `storage.py` (bundle rows), `backend/evals/test_fi3_activation.py`.

**Interfaces (produces), per design §7:**
- `BUNDLE_SCHEMA = "tripwise.financial-activation-bundle/v1"`.
- `ProvenanceCandidate(source_type, verified_by, last_verified, source_url, confidence,
  needs_verification: None)`.
- `ActivationEntry`, with the fields in design §7.1, including `provenance_candidate`,
  `evidenced_fields`, `unevidenced_fields`, and `blocked_by: tuple[str, ...]`.
- `RefusedEntry(proposal_id, code, message)`.
- `ActivationBundle(schema_version, activation_authorized: Literal[False], unresolved_decisions,
  seed_files, entries, refused, dry_run_consistent)`.
- `canonical_bundle_bytes(bundle) -> bytes`.
- `ActivationBundleRecord(bundle_sha256, artifact, proposal_ids)`.
- `DryRunEntry(target_table, target_id, status, field_changes)`.
- `DryRunReport(bundle_sha256, entries, kb_constructs, reference_errors, seed_files_unchanged)`.
- `ActivationPlanner(*, store, artifacts, rows, service)`, with `.build(*, proposal_ids,
  curator_id, client_event_id)` and `.dry_run(bundle_sha256)`.
- In `storage`: `put_activation_bundle(record_json, *, bundle_sha256, client_event_id,
  request_fingerprint, created_by) -> str` and `get_activation_bundle(bundle_sha256)`.

- [ ] **Tests:**
  - `test_bundle_is_byte_deterministic_across_restart_and_clock`.
  - `test_bundle_does_not_resolve_provenance_decisions`. Expect:
    - `activation_authorized is False`;
    - `new_row["provenance"] == current_row["provenance"]`;
    - `provenance_candidate.needs_verification is None`;
    - `"D1" in entry.blocked_by`;
    - `"forex_markup_bp" in entry.unevidenced_fields`.
  - `test_manual_capture_entry_is_blocked_by_d2`.
  - `test_conflicting_targets_refuse_both`.
  - `test_raw_store_decision_without_attestation_is_refused`.
  - `test_edited_row_recomputation_mismatch_is_refused`.
  - `test_proposal_payload_tamper_is_refused`.
  - `test_tampered_evidence_blob_is_refused`.
  - `test_seed_edit_after_bundle_reports_stale`.
  - `test_dry_run_overlays_in_memory_and_checks_references`.
  - `test_dry_run_never_writes`: hash the seeds directory, `backend/evals/golden/`, and
    `DB_PATH` if present, before and after.
  - `test_bundle_persistence_is_idempotent_and_rolls_back`.
  - `test_tampered_bundle_blob_fails_dry_run`.
- [ ] Implement, run, and commit: `feat(fi3): deterministic activation bundles with in-memory dry-run`.

### Task 6: Operator CLI and Checkpoint A demonstration

**Files:** `review_server.py`, `backend/ingestion/fixtures/fi3_demo/`,
`backend/evals/test_fi3_review_server.py`, and the first draft of
`reports/fi3_review_activation_dry_run.md`.

**Interfaces (produces):**
- `class LocalOnlyError(RuntimeError)`.
- `resolve_data_dir(arg, *, env, repo_root) -> Path`: uses `--data-dir` or
  `TRIPWISE_DATA_DIR/ingestion`, and refuses a missing directory or one inside `repo_root`.
- `assert_local_profile(env)`: refuses `TRIPWISE_ENV=production`.
- `build_runtime(data_dir, seeds_dir, *, now, pdf_verification_available) -> (store, service,
  planner)`, using UUID IDs.
- `main(argv=None, *, env=None) -> int`. Subcommands:

| Subcommand | Arguments | Effect |
|---|---|---|
| `add-curator` | `--curator-id`, `--display-name` | Registers a curator |
| `stage-synthetic-demo` | none | Runs the real FI2 path offline (`ManualUploadBackend` → `SnapshotService` → `FinancialExtractor` with `ScriptedLLMClient` loaded from `fixtures/fi3_demo/`) for `hdfc-infinia`, `axis-atlas`, `sbi-cashback`, and `icici-emeralde` against read-only real seed rows. Prints that the data is synthetic. |
| `list` | `[--status]` | Lists proposals |
| `show` | `--proposal-id` | Shows rows, diffs, evidence, hashes, lineage, findings, and decisions |
| `decide` | `--curator-id --proposal-id --action --reason --expected-version --client-event-id [--confidence] [--edit-json PATH]` | Records a decision |
| `bundle` | `--curator-id [--proposal-id ...] --client-event-id` | Writes a bundle and prints its SHA-256 |
| `dry-run` | `--bundle-sha256 [--out PATH]` | Writes the canonical bundle bytes plus the report JSON to `--out`, which must be outside the repo |

Every command is offline and writes only the data directory and `--out`.

- [ ] **Tests:**
  - `test_data_dir_inside_repo_is_refused`.
  - `test_production_profile_is_refused`.
  - `test_add_curator_validates_handle`.
  - `test_cli_workflow_survives_restart`. In one pytest, through `main([...])` calls:
    1. stage the synthetic demo;
    2. approve one proposal, edit one, reject one, and reverify one;
    3. reopen through new `main` calls and `show` each durable decision;
    4. bundle the approved and edited proposals and dry-run them;
    5. assert the bundle bytes are identical across two `dry-run` exports, both entries are
       `would_update`, `activation_authorized` is false, and the seed and golden hashes are
       unchanged.
- [ ] **Checkpoint A demonstration.** Run the same sequence from a shell against a temporary data
  directory outside the repo. Paste the commands and the abridged output into the report as
  synthetic-fixture evidence.
- [ ] Run `make gate` once. Commit: `feat(fi3): operator review CLI and synthetic demo workflow`.

> **Checkpoint A** is a usable operator workflow without HTTP. Delivery may stop here.

### Task 7: Escaped HTML

**Files:** `review_html.py`, `backend/evals/test_fi3_review_html.py`.

**Interfaces:**
- `h(value) -> str`: shows invisible and C0 characters as `⟦U+XXXX⟧`, then applies
  `html.escape(quote=True)`.
- `page(title, body)`.
- Renderers: `render_login`, `render_queue`, `render_proposal(ctx, *, csrf_token,
  client_event_id)`, `render_raw_text`, `render_bundle`, `render_error`.

- [ ] **Tests:**
  - `test_hostile_content_is_escaped`: `<script>`, `onerror`, and `</textarea>` in the snapshot,
    change summary, reason, and policy name; the output has no `<script` and no `<img`.
  - `test_bidi_and_zero_width_are_visualized` (`h("fee‮005") == "fee⟦U+202E⟧005"`).
  - `test_no_page_contains_script_or_inline_handler`.
  - `test_blocked_context_disables_approve_and_edit`.
- [ ] Implement, run, and commit: `feat(fi3): escaped review pages`.

### Task 8: Loopback review app and `serve`

**Files:** `review_app.py`, `review_server.py` (`serve`), `backend/evals/test_fi3_review_app.py`.

**Interfaces:**
- `ReviewAppConfig(port, max_body_bytes=65536, session_idle=30min, session_absolute=8h,
  login_ttl=10min, max_login_failures=5)`, providing `allowed_hosts` and `allowed_origins`.
- `SessionRegistry(*, now)`: `issue_login_token`, `exchange`, `resolve`, `revoke`.
- `ROUTES`:
  - GET `/review/login`, POST `/review/login`, POST `/review/logout`;
  - GET `/review/proposals`, GET `/review/proposal`, POST `/review/decision`;
  - GET `/review/snapshot/raw`, POST `/review/bundles`;
  - GET `/review/bundle`, GET `/review/bundle/download`;
  - GET `/review/static/review.css`.

  IDs travel only as `?id=` or as form fields.
- `create_review_app(*, service, planner, sessions, config)`, with `docs_url`, `redoc_url`, and
  `openapi_url` set to `None`.
- Status mapping:

| Condition | Response |
|---|---|
| Bad Host | 400 |
| Bad Origin or CSRF | 403 |
| No session | 303 on GET; 401 on POST |
| Body over the limit | 413 |
| Unknown ID | 404 |
| Stale, already-decided, or idempotency conflict | 409 |
| Refused or invalid | 422 |

- `serve --curator-id --port 8765 --host 127.0.0.1`:
  - `resolve_bind_host` accepts only `127.0.0.1`, `::1`, or `localhost`.
  - It computes `pdf_verification_available` with `find_spec("pdfplumber")` and runs inside
    `use_runner(PdfProcessRunner(default_timeout_seconds=10.0))`.
  - It prints the login token to stderr only.
  - It runs `uvicorn.Config(..., access_log=False, server_header=False, proxy_headers=False)`.

- [ ] **Tests:**
  - `test_route_table_is_exactly_the_allowlist`.
  - `test_dns_rebinding_host_is_rejected`.
  - `test_post_requires_loopback_origin_and_csrf`.
  - `test_login_token_is_single_use_post_only_and_bounded`.
  - `test_reviewer_comes_from_session_not_body`.
  - `test_resubmitted_form_replays_original_decision`.
  - `test_stale_form_after_other_reviewer_gets_409`.
  - `test_old_form_after_restart_is_rejected`.
  - `test_security_headers_on_every_response`.
  - `test_ids_are_exact_lookups_not_paths`.
  - `test_raw_view_is_escaped_text_and_never_pdf`.
  - `test_oversized_body_is_413_before_parsing`.
  - `test_non_loopback_bind_is_refused`.
  - `test_serve_configures_uvicorn_without_access_log_or_proxy_headers`: monkeypatch
    `uvicorn.Server.run`; the token is printed to stderr only.
- [ ] Implement, run, and commit: `feat(fi3): loopback review app`.

### Task 9: Boundaries, Checkpoint B demonstration, review, and report

**Files:** `backend/evals/test_fi3_acceptance.py`, the report, and a `DEVIATIONS.md` append.

- [ ] **Tests:**
  - `test_product_api_has_no_review_surface`.
  - `test_deploy_files_never_reference_the_review_server`: covers `deploy/compose*.yaml`,
    `deploy/nginx/default.conf`, and `backend/Dockerfile`.
  - `test_fi3_modules_respect_trust_boundaries`. The AST check over `ingestion/review*.py` and
    `ingestion/activation.py` requires:
    - no import of `accounts`, `api`, `httpx`, `requests`, `socket`, or `subprocess`;
    - no use of `seed_database`, `load_kb`, `DB_PATH`, `relative_path`, `write_text`, or
      `write_bytes`.
  - `test_end_to_end_operator_workflow_mutates_nothing`. With sockets blocked, drive login → view
    → approve → restart (a new app and registry on the same files) → reopen → bundle → dry-run
    through `TestClient`. The seed, golden, contract, and KB-DB hashes are unchanged.
- [ ] **Checkpoint B demonstration.** Start `serve` locally against the Checkpoint A data
  directory and perform one browser decision. Record it in the report as synthetic-fixture
  evidence. If no browser is available, use `curl` with the same headers.
- [ ] Run `make gate` once on the exact final tree.
- [ ] Ask for **one** independent review of the completed branch, and fix the reproduced findings
  test-first.
- [ ] **Finish the report.** Include:
  - what works and through which entry point;
  - the demonstration commands and their execution mode (synthetic fixture with the scripted
    extractor; PDF only through the double);
  - what is unavailable: KB apply, real `pdfplumber`, decisions D1–D4;
  - the gate output.

  Append `DEVIATIONS.md` entries for schema 4, terminal statuses, UUID IDs, and the demo fixtures.
  Commit: `docs(fi3): record review and dry-run delivery`.

## Acceptance (robust ingestion plan §13 FI3 gate)

| Gate clause | Evidence |
|---|---|
| Approve/edit/reject is auditable and idempotent | Tasks 1 and 4; `test_cli_workflow_survives_restart`; `test_resubmitted_form_replays_original_decision` |
| Stale approvals fail | `test_unbound_base_row_blocks_approve`; `test_seed_change_after_proposal_is_current_row_changed`; `test_seed_edit_after_bundle_reports_stale`; `test_two_connection_race_has_exactly_one_winner` |
| Activation dry-run cannot change goldens | `test_dry_run_never_writes`; `test_end_to_end_operator_workflow_mutates_nothing`; `GOLDENS_OK` |
| No automatic KB mutation | No apply command exists; `activation_authorized` is always `false`; AST boundary |
| Workflow demonstrated | Checkpoint A CLI and Checkpoint B browser runs recorded in the report |
