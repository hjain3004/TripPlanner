# FI3 — Human Review and Activation Dry-Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a named local curator an audited way to approve, edit, reject, or re-verify FI2
draft proposals, and compile approvals into deterministic activation bundles that are only
dry-run. Nothing writes the KB.

**Architecture:** New flat modules in `backend/ingestion/`:
- `review_rows`: read-only seed rows;
- `review_types` and `review`: the review service;
- `activation`: bundles and the dry-run;
- `review_html` and `review_app`: escaped server HTML on a loopback-only FastAPI app;
- `review_server`: the CLI.

They sit on top of a hardened FI0 store (schema 3). The product app `api.main:app`, the
`contract/openapi.json` contract, `frontend/`, and `deploy/` are untouched.

**Tech stack:** Python 3.11+, Pydantic 2, FastAPI/Starlette, and uvicorn (all existing), plus the
stdlib `sqlite3`, `html`, `secrets`, `hmac`, `hashlib`, `urllib.parse`, and `uuid`. Tests use
pytest and httpx `TestClient` (existing dev extra). **No new dependencies.**

**Spec:** [FI3 design](../specs/2026-10-26-fi3-review-activation-dry-run-design.md). Read it with
[spec 05](../../specs/05_ingestion_pipeline_phase2.md),
[spec 06](../../specs/06_implementation_protocol.md), and the
[robust ingestion plan §§9–13](2026-10-07-robust-financial-ingestion.md).

**Base:** provisional against `c925d98077dd94a1f24d7c312243bfcee78f2d3c` (FI2). Run Task 0 against
Luna's integration commit before writing any code.

## Global Constraints

- No write to `backend/core/seeds/`, `backend/evals/golden/`, `core.db.DB_PATH`,
  `contract/openapi.json`, `frontend/`, `deploy/`, `docs/specs/`, `AGENTS.md`, or `CLAUDE.md`.
- No new dependency in `backend/pyproject.toml`; no Jinja2; no `python-multipart`. Forms are
  parsed with `urllib.parse.parse_qs` over a body capped at 64 KiB.
- No network, LLM, crawler, or provider call anywhere in FI3 code or tests; tests block
  `socket.socket.connect` (FI0 pattern).
- `api/`, `core/`, and `agents/` must not import `ingestion` (existing FI0 AST test). New FI3
  modules are flat files in `backend/ingestion/`, so the existing non-recursive boundary glob
  covers them.
- Server binds only to `127.0.0.1` or `::1`; refuses `TRIPWISE_ENV=production`; the data dir must
  be outside the Git work tree.
- The review store's `id_factory` is collision-free (`uuid.uuid4().hex`) wherever it is not
  injected by a test.
- Money stays integer minor units, basis points, and micro-major (Tier F). FI3 never computes a
  financial value; edits are parsed only by `ingestion.parsing.parse_field_value` through
  `ingestion.validation.validate_extraction`.
- Supported tables: `cards`, `reward_rules`, `offers`, `point_valuations` (design D4).
- Behavior changes and refactors are separate commits; `make gate` stays green between tasks.
- Every commit message ends with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A proposal with `current_row_hash=None`**, which every FI2 test proposal has. The curator
   expects "cannot approve: base row unknown", not a silent approval. The test goes in Task 3
   (`test_unbound_base_row_blocks_approve`).
2. **Quotes containing bidi overrides or zero-width characters** that make text look different
   from its bytes. The curator expects visible `⟦U+202E⟧` markers. The test goes in Task 6
   (`test_bidi_and_zero_width_are_visualized`).
3. **Two approved proposals for the same card** in one bundle. Both should be refused, not
   last-writer-wins. The test goes in Task 5 (`test_conflicting_targets_refuse_both`).
4. **Double-click or back-button resubmission** of a decision form. The curator expects the
   original decision, with no second decision and no error page. The test goes in Task 7
   (`test_resubmitted_form_replays_original_decision`).
5. **A hand edit to a seed YAML** between approval and dry-run. The entry should report `stale`,
   never `would_update`. The test goes in Task 5 (`test_seed_edit_after_bundle_reports_stale`).

---

## File Structure

| Path | Responsibility | Task |
|---|---|---|
| `backend/ingestion/contracts.py` (modify) | Add `EvidenceDigest`, `ReviewAttestation`, `CuratorRecord`; add optional `curator_confidence` and `attestation` to `ReviewDecision` | 1 |
| `backend/ingestion/migrations.py` (modify) | `SCHEMA_VERSION = 3` | 1 |
| `backend/ingestion/storage.py` (modify) | Schema 3 tables; decision hardening; curator, watch-target, policy, and proposal reads; bundle records | 1, 5 |
| `backend/ingestion/review_rows.py` (create) | `SUPPORTED_TABLES`, `canonical_row_hash`, `flatten_row`, `SeedRowSource` (read-only) | 2 |
| `backend/ingestion/review_types.py` (create) | Review DTOs and finding codes | 3 |
| `backend/ingestion/review.py` (create) | `ReviewService`: context, computed findings, edits, decisions | 3, 4 |
| `backend/ingestion/activation.py` (create) | Bundle models, `canonical_bundle_bytes`, `ActivationPlanner.build/dry_run` | 5 |
| `backend/ingestion/review_html.py` (create) | `h()` escaping and the page renderers | 6 |
| `backend/ingestion/review_app.py` (create) | `ReviewAppConfig`, `SessionRegistry`, `create_review_app`, `ROUTES` | 7 |
| `backend/ingestion/review_server.py` (create) | CLI: `add-curator`, `serve`; bind, production, and data-dir guards | 8 |
| `backend/evals/fi3_fixtures.py` (create) | Builds temporary seeds, a real FI2 proposal, and a review runtime | 2 |
| `backend/evals/test_fi3_storage.py` | Task 1 | 1 |
| `backend/evals/test_fi3_review_rows.py` | Task 2 | 2 |
| `backend/evals/test_fi3_review_service.py` | Tasks 3–4 | 3, 4 |
| `backend/evals/test_fi3_activation.py` | Task 5 | 5 |
| `backend/evals/test_fi3_review_html.py` | Task 6 | 6 |
| `backend/evals/test_fi3_review_app.py` | Task 7 | 7 |
| `backend/evals/test_fi3_review_server.py` | Task 8 | 8 |
| `backend/evals/test_fi3_acceptance.py` | Task 9 | 9 |
| `backend/evals/fixtures/fi3_review_openapi.json` (create) | Operator-app schema snapshot | 9 |
| `reports/fi3_review_activation_dry_run.md`, `DEVIATIONS.md` (append) | Milestone report and deviations | 9 |

All test commands run from `backend/` with the trusted virtualenv:
`.venv/bin/pytest -q <file>`.

---

### Task 0: Recheck the FI2 interfaces at the integration commit (no code)

**Files:** none. Record the results in `DEVIATIONS.md` only if something differs.

- [ ] **Step 1:** Create the FI3 implementation worktree from Luna's integration commit (or
  `c925d98` if the human says so). Confirm it contains the six FI2 commits.
- [ ] **Step 2:** For each row of the design §12 table, compare the signature and behavior with
  this plan. Specifically confirm:
  - `verify_evidence_span(span, *, snapshot, artifacts)` raises `EvidenceVerificationError`;
  - `validate_extraction` keyword arguments are unchanged;
  - `ingestion.migrations.SCHEMA_VERSION == 2`;
  - `review_decisions.proposal_id` is still `UNIQUE`;
  - `FinancialExtractor` still emits `lineage_ids=(snapshot_id,)`;
  - `ingestion.validation._row_hash` is still `json.dumps(row, sort_keys=True,
    separators=(",", ":"), default=str)` → SHA-256.
- [ ] **Step 3:** Run `make seed PY=.venv/bin/python`, then `make gate`. Expected: GATE PASSED.
  Record the baseline pass count; FI2 reported 2231 passed, 1 skipped.
- [ ] **Step 4:** If an interface changed, update the affected task's Interfaces block in this
  plan in a docs-only commit before Task 1. If the schema version is already 3, renumber FI3's
  migration to the next free version.

---

### Task 1: Schema 3 and decision hardening

**Files:**
- Modify: `backend/ingestion/contracts.py` (after `ReviewDecisionStatus`, around line 297)
- Modify: `backend/ingestion/migrations.py`
- Modify: `backend/ingestion/storage.py` (`_SCHEMA` lines 47–84, `_next_id` 104, `_audit` 174–201,
  `_fingerprint_request` 125–144, `_decide_proposal` 424–528)
- Test: `backend/evals/test_fi3_storage.py` (reuses `policy`, `target`, `snapshot`, `proposal`,
  and `NOW` from `evals/test_fi0_ingestion.py`)

**Interfaces:**
- Produces in `ingestion.contracts`:
  - `EvidenceDigest(BaseModel, frozen)`: `snapshot_id: str`, `raw_sha256: str (SHA256)`,
    `normalized_sha256: str (SHA256)`.
  - `ReviewAttestation(BaseModel, frozen)`: `proposal_payload_sha256: str (SHA256)`,
    `current_row_sha256: str (SHA256)`, `resulting_row_sha256: str | None (SHA256)`,
    `evidence: tuple[EvidenceDigest, ...] (min_length=1)`,
    `computed_finding_codes: tuple[str, ...] = ()`.
  - `CuratorRecord(BaseModel, frozen)`:
    `curator_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,31}$")`,
    `display_name: str (1..80)`, `created_at: AwareDatetime`.
  - `ReviewDecision`, added fields: `curator_confidence: float | None = Field(None, ge=0, le=1)`
    and `attestation: ReviewAttestation | None = None`.
- Produces in `ingestion.storage`:
  - `class InvalidDecisionError(IngestionStoreError)`
  - `proposal_payload_sha256(payload_json: str) -> str`: SHA-256 of the stored payload text.
  - `FinancialIngestionStore.decide_proposal(proposal_id, *, reviewer_id, status, reason,
    expected_version, client_event_id, edits=None, curator_confidence: float | None = None,
    attestation: ReviewAttestation | None = None, reverify_task: ReverifyTask | None = None)
    -> ReviewDecision`
  - `put_curator(record: CuratorRecord) -> CuratorRecord` (insert-only; identical replay OK;
    a conflict raises `ConflictingWriteError`)
  - `get_curator(curator_id: str) -> CuratorRecord | None`
  - `get_watch_target(target_id: str) -> WatchTarget | None`
  - `get_source_policy(policy_id: str) -> SourcePolicyRecord | None`
  - `list_proposals(*, status: ProposalStatus | None = None) -> list[ChangeProposal]`, ordered
    by `(created_at, id)`
  - `get_reverify_task(task_id: str) -> ReverifyTask | None`
- Schema 3 DDL adds:
  - `curators(id TEXT PRIMARY KEY, payload TEXT NOT NULL)`
  - `activation_bundles(id TEXT PRIMARY KEY, client_event_id TEXT NOT NULL UNIQUE,
    request_fingerprint TEXT NOT NULL, payload TEXT NOT NULL)`
  The bundle methods arrive in Task 5.

- [ ] **Step 1: Write the failing tests**

```python
def test_edited_and_reverify_are_terminal(tmp_path): ...
    # decide EDITED (with attestation + non-empty edits) then APPROVED at version 2
    # -> pytest.raises(AlreadyDecidedError); same for REVERIFY. No sqlite3.IntegrityError escapes.

def test_edit_shape_is_structural(tmp_path):
    # APPROVED with edits={"fields": [...]} -> InvalidDecisionError
    # EDITED with edits=None -> InvalidDecisionError
    # REVERIFY without reverify_task -> InvalidDecisionError; APPROVED with reverify_task -> InvalidDecisionError
    # the FI0 idempotency variant (REJECTED + edits, reused client_event_id) still raises IdempotencyConflictError

def test_attestation_hash_mismatch_is_stale(tmp_path):
    # attestation.proposal_payload_sha256 = "0"*64 -> StaleVersionError; proposal version still 1

def test_reverify_task_commits_atomically_with_decision(tmp_path, monkeypatch):
    # happy path: decision + task + 2 audit events (decision, reverify_task) exist
    # failure: monkeypatch store._audit to raise on event_type == "reverify_task" created
    #   -> no review_decisions row, proposal status "pending" version 1, get_reverify_task(...) is None

def test_decision_rolls_back_when_audit_fails(tmp_path, monkeypatch):
    # _audit raises on "decision" -> no decision row, version 1, list_audit_events has no "decision"

def test_ids_are_unique_across_reopen(tmp_path):
    # store A decides p1; store B (new instance, default id_factory) decides p2..p6
    # all decision ids distinct and none equals any audit event_id

def test_audit_retry_is_bounded(tmp_path):
    # id_factory=lambda: "fixed" with an existing audit row "fixed" -> IngestionStoreError, returns within 1s

def test_confidence_fingerprint_is_additive(tmp_path):
    # _fingerprint_request(...) with curator_confidence=None equals the FI0 value for the same args;
    # replay with a different curator_confidence -> IdempotencyConflictError

def test_schema_3_migrates_a_schema_2_database(tmp_path):
    # build a v2 db via the c925d98 DDL, open with the new store -> PRAGMA user_version == 3,
    # curators/activation_bundles exist, existing proposals and decisions read back unchanged

def test_two_connection_race_has_exactly_one_winner(tmp_path):
    # FI0 barrier pattern with attestation-bearing APPROVED vs REJECTED -> exactly one decision row
```

- [ ] **Step 2:** Run `.venv/bin/pytest -q evals/test_fi3_storage.py`. Expected: FAIL (missing
  names). Also run `evals/test_fi0_ingestion.py` and expect PASS (baseline unchanged).
- [ ] **Step 3: Implement.**
  - **Terminal status.** Replace the check `row[0] not in {"pending","edited","reverify"}` with
    `row[0] != "pending"`.
  - **Order inside `BEGIN IMMEDIATE`.** Run the checks as: replay → CAS → terminal → edit/status
    shape → blocking findings (existing) → lineage (existing) → attestation hash → inserts.
  - **IDs.** `_next_id` returns `f"evt-{uuid.uuid4().hex}"`. Bound the `_audit` retry to 3
    attempts, then raise `IngestionStoreError`.
  - **Fingerprint.** `_fingerprint_request` adds `"curator_confidence"` only when it is not
    `None`.
  - **Reverify task.** Insert it in the same connection (factor the body of
    `put_reverify_task` into `_insert_reverify_task(connection, task, client_event_id)`), using
    the decision's `client_event_id + ":task"` as its event ID.
  - **Migration.** `migrate()` gains `if version < 3:`. Its DDL is idempotent `CREATE TABLE IF
    NOT EXISTS`, already in `_SCHEMA`.
- [ ] **Step 4:** Run `.venv/bin/pytest -q evals/test_fi3_storage.py evals/test_fi0_ingestion.py
  evals/test_fi1_snapshot_core.py evals/test_fi2_extraction.py`. Expected: all PASS.
- [ ] **Step 5:** Run `.venv/bin/mypy --strict ingestion/ && .venv/bin/ruff check ingestion/
  evals/test_fi3_storage.py`. Expected: clean.
- [ ] **Step 6: Commit.** `fix(fi3): harden review decisions for terminal state, attestation, and atomic reverify`

---

### Task 2: Read-only seed rows and canonical hashing

**Files:**
- Create: `backend/ingestion/review_rows.py`
- Create: `backend/evals/fi3_fixtures.py`
- Test: `backend/evals/test_fi3_review_rows.py`

**Interfaces:**
- Produces in `ingestion.review_rows`:
  - `SUPPORTED_TABLES: Mapping[str, tuple[str, type[BaseModel]]]` = `{"cards": ("cards.yaml",
    Card), "reward_rules": ("reward_rules.yaml", RewardRule), "offers": ("offers.yaml", Offer),
    "point_valuations": ("point_valuations.yaml", PointValuation)}`
  - `class SeedRowError(ValueError)`, with `code: str` set to one of `"unsupported_target_table"`,
    `"current_row_missing"`, or `"duplicate_row_id"`
  - `canonical_row_hash(row: Mapping[str, Any]) -> str`: the same bytes as
    `ingestion.validation._row_hash`
  - `flatten_row(row: Mapping[str, Any]) -> dict[str, Any]`: dotted paths, the same semantics as
    `validation._flatten`
  - `class SeedRowSource`:
    - `__init__(self, seeds_dir: Path)`
    - `current_row(table: str, target_id: str) -> dict[str, Any]`, as
      `Model.model_validate(raw).model_dump(mode="json")`; raises `SeedRowError`
    - `table_rows(table: str) -> list[dict[str, Any]]`
    - `seed_file_sha256(table: str) -> str`
- Produces in `evals.fi3_fixtures`:
  - `write_seeds(dir: Path, *, cards: list[dict] | None = None) -> Path`: copies the four
    supported real seed files into `dir`, optionally replacing `cards.yaml` rows
  - `infinia_row() -> dict[str, Any]`
  - `build_runtime(tmp_path: Path, *, snapshot_text: str = "Annual fee is INR 12,500.",
    media_type: str = "text/html", page_kind: str = "card_page", current_row_hash: str | None
    = "auto") -> Fi3Runtime`, which creates the policy, watch target, and snapshot. It creates the
    proposal through the real `validate_extraction` and stores it.
  - `Fi3Runtime` dataclass: `store`, `artifacts`, `rows`, `seeds_dir`, `snapshot`,
    `proposal`, `now`

- [ ] **Step 1: Write the failing tests**

```python
def test_canonical_row_hash_matches_fi2_private_hash():
    row = SeedRowSource(write_seeds(tmp)).current_row("cards", "hdfc-infinia")
    assert canonical_row_hash(row) == validation._row_hash(row)

def test_current_row_is_model_normalized_json():  # dates are ISO strings, provenance present, id matches

def test_unsupported_tables_and_missing_or_duplicate_ids_raise_typed_codes():
    # "fx_rates" -> code "unsupported_target_table"; "transfer_edges" -> same
    # unknown id -> "current_row_missing"; duplicated id in cards.yaml -> "duplicate_row_id"

def test_seed_source_never_writes(tmp_path):
    # sha256 of every file in seeds_dir before == after reading all tables
```

- [ ] **Step 2:** Run `.venv/bin/pytest -q evals/test_fi3_review_rows.py`. Expected: FAIL.
- [ ] **Step 3: Implement.** Use `yaml.safe_load` and the model classes. Read with
  `Path.read_bytes()`, and hash the same bytes. Do not import `core.db.seed_database`,
  `load_kb`, or `DB_PATH`.
- [ ] **Step 4:** Run the tests. Expected: PASS. Run mypy and ruff as in Task 1.
- [ ] **Step 5: Commit.** `feat(fi3): add read-only seed row source and canonical row hash`

---

### Task 3: Review context and computed findings

**Files:**
- Create: `backend/ingestion/review_types.py`
- Create: `backend/ingestion/review.py`
- Test: `backend/evals/test_fi3_review_service.py`

**Interfaces:**
- Consumes: Task 1 store methods; Task 2 `SeedRowSource`, `canonical_row_hash`, `flatten_row`.
- Produces in `ingestion.review_types`:
  - `class FindingCode(StrEnum)`: `STORED_BLOCKING_FINDING`, `UNSUPPORTED_TARGET_TABLE`,
    `CURRENT_ROW_MISSING`, `UNBOUND_BASE_ROW`, `CURRENT_ROW_CHANGED`,
    `EVIDENCE_INTEGRITY_FAILED`, `EVIDENCE_SUPERSEDED`, `MULTI_SNAPSHOT_LINEAGE`,
    `MANUAL_CAPTURE`, `ATTRIBUTION_REQUIRED`, `UNKNOWN_CURATOR`, `UNSUPPORTED_EDIT_TYPE`,
    `INVALID_EDIT`, `NO_EFFECTIVE_EDIT`. Values are the lowercase design names.
  - `ComputedFinding(code: FindingCode, severity: Literal["warning","blocking"], message: str,
    field_path: str | None = None)`
  - `FieldDiff(field_path: str, current: Any, proposed: Any, edited: Any | None, changed: bool,
    evidence: tuple[EvidenceSpan, ...])`
  - `EvidenceContext(span: EvidenceSpan, before: str, after: str, verified: bool,
    failure: str | None)`
  - `LineageView(source_policy: SourcePolicyRecord, watch_target: WatchTarget,
    snapshots: tuple[SnapshotBundle, ...], supersession_chain: tuple[str, ...],
    latest_snapshot_id: str | None)`
  - `ReviewContext(proposal: ChangeProposal, current_row: dict[str, Any] | None,
    current_row_sha256: str | None, field_diffs: tuple[FieldDiff, ...],
    evidence: tuple[EvidenceContext, ...], lineage: LineageView | None,
    computed_findings: tuple[ComputedFinding, ...], decisions: tuple[ReviewDecision, ...],
    audit_events: tuple[dict[str, str], ...])`, with properties `blocking_for_approval: bool`
    and `blocking_for_edit: bool`
  - `class ReviewRefusedError(ValueError)` with `findings: tuple[ComputedFinding, ...]`
- Produces in `ingestion.review`: `class ReviewService`:
  - `__init__(self, *, store, artifacts, rows: SeedRowSource, now: Callable[[], datetime],
    evidence_verifier: Callable[..., None] = verify_evidence_span)`
  - `list_queue(self, status: ProposalStatus | None = ProposalStatus.PENDING) -> list[ChangeProposal]`
  - `context(self, proposal_id: str) -> ReviewContext`; raises `KeyError` for an unknown ID
  - Constants: `CONTEXT_CHARS = 240` and `SUPERSESSION_LIMIT = 50`

- [ ] **Step 1: Write the failing tests**

```python
def test_context_shows_rows_diffs_evidence_hashes_and_lineage(tmp_path):
    rt = build_runtime(tmp_path)
    ctx = ReviewService(...).context(rt.proposal.proposal_id)
    assert [d.field_path for d in ctx.field_diffs if d.changed] == ["annual_fee_minor"]
    assert ctx.evidence[0].verified and ctx.evidence[0].span.snapshot_hash == rt.snapshot.normalized_sha256
    assert ctx.lineage.watch_target.target_id == rt.snapshot.target_id
    assert ctx.lineage.source_policy.policy_id == "issuer-hdfc"
    assert not ctx.blocking_for_approval

def test_unbound_base_row_blocks_approve(tmp_path):          # build_runtime(current_row_hash=None)
    assert FindingCode.UNBOUND_BASE_ROW in codes(ctx) and ctx.blocking_for_approval

def test_seed_change_after_proposal_is_current_row_changed(tmp_path)  # rewrite cards.yaml annual fee
def test_tampered_blob_is_evidence_integrity_failed(tmp_path)         # overwrite blob bytes on disk
def test_newer_different_snapshot_is_evidence_superseded(tmp_path)    # put a second snapshot for target
def test_unsupported_table_and_missing_row_are_blocking(tmp_path)
def test_stored_blocking_finding_is_surfaced(tmp_path)               # proposal with non_positive_rate
def test_manual_capture_and_attribution_are_warnings_only(tmp_path)
def test_relative_path_is_never_used(tmp_path):
    # rewrite the snapshot manifest's raw_artifact.relative_path to "../../etc/passwd" via direct SQL
    # on a fresh DB -> context still verifies by digest; no file outside artifacts root is opened
    # (monkeypatch Path.read_bytes to record paths; assert each is under artifacts.root or rt.seeds_dir)
def test_unknown_proposal_raises_key_error(tmp_path)
```

- [ ] **Step 2:** Run `.venv/bin/pytest -q evals/test_fi3_review_service.py`. Expected: FAIL.
- [ ] **Step 3: Implement** `context()`. It uses `store.get_proposal`, `get_snapshot`,
  `get_watch_target`, `get_source_policy`, `latest_snapshot`, `list_decisions`, and
  `list_audit_events(entity_id=...)`, then calls `evidence_verifier` per span.
  - Catch only `EvidenceVerificationError`, `ArtifactIntegrityError`, and `FileNotFoundError`;
    each becomes `evidence_integrity_failed`.
  - The supersession walk stops at `SUPERSESSION_LIMIT` or on a repeated ID.
- [ ] **Step 4:** Run the tests. Expected: PASS. Run mypy and ruff.
- [ ] **Step 5: Commit.** `feat(fi3): build review context with re-verified evidence and computed findings`

---

### Task 4: Decisions and validated edits

**Files:**
- Modify: `backend/ingestion/review_types.py`, `backend/ingestion/review.py`
- Test: `backend/evals/test_fi3_review_service.py` (append)

**Interfaces:**
- Consumes: Task 1 `decide_proposal(...)` and `ReviewAttestation`; Task 3 `context()`.
- Produces in `ingestion.review_types`:
  - `CuratorFieldEdit(BaseModel, frozen, extra="forbid")`:
    - fields: `field_path: str (1..200)`, `action: Literal["set","revert"]`,
      `proposed_raw_value: str | None (≤200)`, `quote: str | None (≤2000)`,
      `occurrence: int | None (ge=1)`, `snapshot_id: str | None`,
      `page_number: int | None (ge=1)`;
    - validator: `set` requires the raw value, quote, and snapshot ID; `revert` forbids all
      five optional fields.
  - `DecisionRequest(BaseModel, extra="forbid")`:
    - fields: `proposal_id`, `action: Literal["approve","edit","reject","reverify"]`,
      `reason: str (1..1000)`, `expected_version: int (ge=1)`,
      `client_event_id: str = Field(pattern=r"^[A-Za-z0-9_-]{16,64}$")`,
      `curator_confidence: float | None`, `edits: tuple[CuratorFieldEdit, ...] = ()`;
    - validators: confidence is required iff the action is approve or edit, within [0,1], and
      `round(x, 2) == x`; edits are non-empty iff the action is edit; field paths are unique.
- Produces in `ingestion.review`:
  - `ReviewService.apply_edits(self, ctx: ReviewContext, edits: tuple[CuratorFieldEdit, ...])
    -> tuple[dict[str, Any], ChangeProposal]`. It returns the edited row and the revalidated
    proposal, and raises `ReviewRefusedError`.
  - `ReviewService.decide(self, request: DecisionRequest, *, curator_id: str) -> ReviewDecision`
  - `ReviewService.edits_payload(edits) -> dict[str, Any]`, which returns
    `{"fields": [e.model_dump(mode="json") sorted by field_path]}`. Task 5 uses it to
    recompute the edited row.

- [ ] **Step 1: Write the failing tests**

```python
def test_approve_records_attestation_and_named_reviewer(tmp_path):
    d = svc.decide(req("approve", confidence=0.9), curator_id="alice")
    assert d.reviewer_id == "alice" and d.status is ReviewDecisionStatus.APPROVED
    assert d.attestation.current_row_sha256 == canonical_row_hash(infinia_row())
    assert d.attestation.evidence[0].normalized_sha256 == rt.snapshot.normalized_sha256

def test_unknown_curator_is_refused(tmp_path)               # ReviewRefusedError(UNKNOWN_CURATOR), no decision row
def test_blocking_findings_refuse_approve_and_edit_but_allow_reject_and_reverify(tmp_path)
def test_edit_requires_exact_quote_and_raw_inside_quote(tmp_path):
    # set annual_fee_minor raw "INR 13,000" with quote "Annual fee is INR 12,500." -> INVALID_EDIT
    # quote not in snapshot -> INVALID_EDIT; ambiguous quote without occurrence -> INVALID_EDIT
def test_edit_goes_through_fi2_validation(tmp_path):
    # snapshot "Annual fee is INR 12,500. Joining fee INR 12,000." ; set annual_fee_minor raw "INR 12,000"
    # quote "Joining fee INR 12,000." -> decision EDITED; resulting_row_sha256 == canonical_row_hash(edited)
    # and edited["annual_fee_minor"] == 1200000 (parsed by parse_field_value, not by FI3)
def test_edit_cannot_touch_id_provenance_or_untyped_fields(tmp_path)  # id, provenance.confidence, base_earn (dict) -> refused
def test_edit_introducing_blocking_sanity_is_refused(tmp_path)         # reward rule earn.points "0" -> refused
def test_revert_all_or_no_effective_edit_is_refused(tmp_path)
def test_reverify_creates_task_for_watch_target_atomically(tmp_path):
    t = store.get_reverify_task(f"reverify:{rt.proposal.proposal_id}")
    assert t.target_id == rt.snapshot.target_id and t.prior_evidence_ids == rt.proposal.lineage_ids
def test_replay_after_restart_returns_original_decision(tmp_path):
    # decide; build a new store + service on the same paths; decide(same request) == original;
    # audit "decision" events for proposal == 1; changed reason -> IdempotencyConflictError
def test_concurrent_reviewers_one_wins(tmp_path)   # two services, barrier, approve vs reject
def test_manual_capture_cannot_edit_provenance(tmp_path)
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - **`apply_edits`:**
    - refuse if `MULTI_SNAPSHOT_LINEAGE`;
    - for each `set`, find the quote occurrences in `snapshot.canonical_markdown`, derive the
      offsets, and build `EvidenceSpan(verification="exact", artifact_kind=<"pdf" if the raw
      media type is PDF else "html">, page_number=...)`;
    - require `unicodedata.normalize("NFKC", raw) in unicodedata.normalize("NFKC", quote)`;
    - compute `parse_field_value(path, raw, expected=<current value>)` only to type-check it,
      which must be `int` (not `bool`), `str`, or `date`;
    - build the edited row (dates as ISO strings) and the response dict (surviving FI2 fields
      plus the edits);
    - call `validate_extraction`, mapping `ProposalValidationError` to `INVALID_EDIT`, and refuse
      if the result has a blocking finding.
  - **`decide`:**
    - check the curator exists, then build the context and refuse approve/edit when blocked;
    - compute the attestation with `proposal_payload_sha256` over the stored JSON
      (`store.get_proposal(...).model_dump_json()`), and the resulting row for approve/edit;
    - build the `ReverifyTask` for reverify, then call `store.decide_proposal(...)`.
- [ ] **Step 4:** Run `evals/test_fi3_*.py` and the FI0–FI2 tests. Expected: PASS. Run mypy and
  ruff.
- [ ] **Step 5: Commit.** `feat(fi3): validated curator decisions and edits through FI2 validation`

---

### Task 5: Activation bundles and dry-run

**Files:**
- Create: `backend/ingestion/activation.py`
- Modify: `backend/ingestion/storage.py` (bundle record methods)
- Test: `backend/evals/test_fi3_activation.py`

**Interfaces:**
- Consumes: Task 4 `ReviewService.context/apply_edits/edits_payload`; Task 2 `SeedRowSource`;
  `ContentAddressedStore.put/read`.
- Produces in `ingestion.activation`:
  - `BUNDLE_SCHEMA = "tripwise.financial-activation-bundle/v1"`
  - `FieldChange(field_path: str, old: Any, new: Any)`
  - `ActivationEntry`: fields as listed in design §7.1, with `source_type: Literal[
    "official_page","tnc_pdf","manual_curation"]`
  - `RefusedEntry(proposal_id: str, code: str, message: str)`
  - `ActivationBundle(schema_version: Literal[BUNDLE_SCHEMA], seed_files: dict[str, str],
    entries: tuple[ActivationEntry, ...], refused: tuple[RefusedEntry, ...], applicable: bool)`
  - `canonical_bundle_bytes(bundle: ActivationBundle) -> bytes`
  - `ActivationBundleRecord(bundle_sha256: str, artifact: ImmutableArtifactRef,
    proposal_ids: tuple[str, ...])`
  - `DryRunEntry(target_table: str, target_id: str, status: Literal["would_update","stale",
    "row_missing","invalid_row"], field_changes: tuple[FieldChange, ...])`
  - `DryRunReport(bundle_sha256: str, entries: tuple[DryRunEntry, ...], kb_constructs: bool,
    reference_errors: tuple[str, ...], seed_files_unchanged: bool, applicable: bool)`
  - `class ActivationPlanner`:
    - `__init__(self, *, store, artifacts, rows: SeedRowSource, service: ReviewService)`
    - `build(self, *, proposal_ids: tuple[str, ...] | None, curator_id: str,
      client_event_id: str) -> tuple[ActivationBundleRecord, ActivationBundle]`
    - `dry_run(self, bundle_sha256: str) -> DryRunReport`
- Produces in `ingestion.storage`:
  - `put_activation_bundle(record_json: str, *, bundle_sha256: str, client_event_id: str,
    request_fingerprint: str, created_by: str) -> str`, which returns the stored payload.
    An existing ID returns the stored payload; a reused event with a different fingerprint
    raises `IdempotencyConflictError`.
  - `get_activation_bundle(bundle_sha256: str) -> str | None`

- [ ] **Step 1: Write the failing tests**

```python
def test_bundle_is_byte_deterministic_across_restart_and_clock(tmp_path):
    # approve; build with now=T1 -> bytes1; reopen everything with now=T2; build -> bytes2
    assert bytes1 == bytes2 and record1.bundle_sha256 == hashlib.sha256(bytes1).hexdigest()

def test_bundle_applies_spec05_provenance_and_lists_unevidenced_fields(tmp_path):
    e = bundle.entries[0]
    assert e.new_row["provenance"] == {"source_url": "https://www.hdfcbank.com/cards/infinia",
        "source_type": "official_page", "last_verified": "<decided_at UTC date>", "verified_by": "alice",
        "needs_verification": False, "confidence": 0.9, "notes": None}
    assert "forex_markup_bp" in e.unevidenced_fields and "annual_fee_minor" not in e.unevidenced_fields

def test_manual_capture_entry_stays_manual_and_unverified(tmp_path)
def test_conflicting_targets_refuse_both(tmp_path)          # two approved proposals for hdfc-infinia
def test_raw_store_decision_without_attestation_is_refused(tmp_path)  # store.decide_proposal(EDITED, edits={...}) directly
def test_edited_row_recomputation_mismatch_is_refused(tmp_path)       # direct SQL: alter decision edits payload
def test_proposal_payload_tamper_is_refused(tmp_path)                 # direct SQL: alter proposal payload
def test_tampered_evidence_blob_is_refused(tmp_path)
def test_seed_edit_after_bundle_reports_stale(tmp_path):
    # build; rewrite cards.yaml annual fee; dry_run -> entry.status == "stale", applicable False
def test_dry_run_overlays_in_memory_and_checks_references(tmp_path)    # would_update, kb_constructs True
def test_dry_run_never_writes(tmp_path):
    # hash seeds_dir, backend/evals/golden/**, core.db.DB_PATH (if present) before/after build+dry_run -> equal
def test_bundle_persistence_is_idempotent_and_rolls_back(tmp_path, monkeypatch):
    # same content twice -> same record, one row; reused client_event_id with different selection
    #   -> IdempotencyConflictError
    # monkeypatch the store insert to raise -> no row; retry succeeds; blob reused (same digest)
def test_tampered_bundle_blob_fails_dry_run(tmp_path)                 # overwrite blob -> ArtifactIntegrityError surfaced as typed failure
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `build` follows design §7.1. The provenance mapping:
    `page_kind ∈ {card_page, offer_page} → official_page`, `tnc_pdf → tnc_pdf`,
    `manual_capture → manual_curation` with `needs_verification=True`.
  - `unevidenced_fields` = the row's flattened paths that are not `id`, do not start with
    `provenance.`, and are not covered by a field proposal or edit.
  - The bundle request fingerprint is the SHA-256 of canonical JSON
    `{"proposal_ids": sorted, "curator_id": ...}`.
  - `dry_run` follows design §7.2. Build `KnowledgeBase.from_models(cards=..., reward_rules=...,
    offers=..., point_valuations=...)` from validated models, inside `try`.
- [ ] **Step 4:** Run the FI3 and FI0–FI2 tests. Expected: PASS. Run mypy and ruff.
- [ ] **Step 5: Commit.** `feat(fi3): deterministic activation bundles with in-memory dry-run`

---

### Task 6: Escaped HTML rendering

**Files:**
- Create: `backend/ingestion/review_html.py`
- Test: `backend/evals/test_fi3_review_html.py`

**Interfaces:**
- Consumes: Task 3 `ReviewContext`; Task 5 `ActivationBundle`, `ActivationBundleRecord`,
  `DryRunReport`.
- Produces:
  - `INVISIBLE = frozenset(range(0x200B, 0x2010)) | frozenset(range(0x202A, 0x202F)) |
    frozenset(range(0x2066, 0x206A)) | {0xFEFF}`
  - `h(value: object) -> str`: replaces each `INVISIBLE` code point and each C0 control except
    `\t` and `\n` with `⟦U+XXXX⟧`, then applies `html.escape(..., quote=True)`
  - `page(title: str, body_html: str) -> str`: a full document with a `<link rel="stylesheet">`
    pointing at `/review/static/review.css`, served inline by Task 7
  - `render_login(error_code: str | None) -> str`
  - `render_queue(proposals: Sequence[ChangeProposal]) -> str`
  - `render_proposal(ctx: ReviewContext, *, csrf_token: str, client_event_id: str) -> str`
  - `render_raw_text(snapshot_id: str, text: str) -> str`
  - `render_bundle(record, bundle, report: DryRunReport | None, *, csrf_token: str,
    client_event_id: str) -> str`
  - `render_error(status: int, code: str) -> str`

- [ ] **Step 1: Write the failing tests**

```python
HOSTILE = '<script>alert(1)</script>"><img src=x onerror=alert(2)></textarea>javascript:alert(3)'

def test_hostile_snapshot_summary_and_reason_are_escaped():
    # build ctx with HOSTILE in snapshot text, change_summary, decision reason, policy name
    html = render_proposal(ctx, csrf_token="t", client_event_id="e" * 24)
    assert "<script" not in html.lower() and "<img" not in html.lower()
    assert "&lt;script&gt;" in html and "&lt;img src=x onerror=alert(2)&gt;" in html

def test_bidi_and_zero_width_are_visualized():
    assert h("fee‮005") == "fee⟦U+202E⟧005" and h("a​b") == "a⟦U+200B⟧b"

def test_no_page_contains_any_script_tag_or_inline_handler()   # every renderer, fixed inputs
def test_links_only_for_http_urls_with_noreferrer()           # source_url rendered as <a rel="noopener noreferrer">
def test_forms_carry_csrf_client_event_and_expected_version()
def test_blocked_context_disables_approve_and_edit_controls()
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3: Implement.** Use pure string building where every dynamic value passes through
  `h()`. There is no other interpolation helper. Evidence is shown as
  `h(before) + "<mark>" + h(quote) + "</mark>" + h(after)`.
- [ ] **Step 4:** Run. Expected: PASS. Run mypy and ruff.
- [ ] **Step 5: Commit.** `feat(fi3): escaped server-rendered review pages`

---

### Task 7: Loopback review app — sessions, CSRF, and routes

**Files:**
- Create: `backend/ingestion/review_app.py`
- Test: `backend/evals/test_fi3_review_app.py` (Starlette `TestClient` with
  `base_url="http://127.0.0.1:8765"`)

**Interfaces:**
- Consumes: Tasks 3–6.
- Produces:
  - `ReviewAppConfig(dataclass, frozen)`: `port: int`, `max_body_bytes: int = 65536`,
    `session_idle: timedelta = 30 min`, `session_absolute: timedelta = 8 h`,
    `login_ttl: timedelta = 10 min`, `max_login_failures: int = 5`, with properties
    `allowed_hosts` (`127.0.0.1:{p}`, `localhost:{p}`, `[::1]:{p}`) and `allowed_origins`
    (`http://` + each).
  - `SessionRegistry`:
    - `__init__(self, *, now: Callable[[], datetime])`
    - `issue_login_token(self, curator_id: str) -> str`
    - `exchange(self, token: str) -> tuple[str, str] | None`, returning
      `(session_token, csrf_token)`
    - `resolve(self, session_token: str) -> Session | None`
    - `revoke(self, session_token: str) -> None`
  - `Session(dataclass)`: `curator_id`, `csrf_token`, `created_at`, `last_seen`.
  - `ROUTES: frozenset[tuple[str, str]]`:
    `{("GET","/review/login"), ("POST","/review/login"), ("POST","/review/logout"),
    ("GET","/review/proposals"), ("GET","/review/proposal"), ("POST","/review/decision"),
    ("GET","/review/snapshot/raw"), ("POST","/review/bundles"), ("GET","/review/bundle"),
    ("GET","/review/bundle/download"), ("GET","/review/static/review.css")}`.
    Identifiers travel as `?id=` or as form fields, never as path segments.
  - `create_review_app(*, service: ReviewService, planner: ActivationPlanner, sessions:
    SessionRegistry, config: ReviewAppConfig) -> FastAPI`, created with
    `docs_url=None, redoc_url=None, openapi_url=None`.
  - Status mapping:

| Condition | Response |
|---|---|
| Bad Host | 400 |
| Missing or wrong Origin, or CSRF failure | 403 |
| No session | 303 to `/review/login` on GET; 401 on POST |
| Body over the limit | 413 |
| Not found | 404 |
| `StaleVersionError`, `AlreadyDecidedError`, or `IdempotencyConflictError` | 409 |
| `ReviewRefusedError` or a validation error | 422 |

    Every response carries the design §4 headers.

- [ ] **Step 1: Write the failing tests**

```python
def test_route_table_is_exactly_the_allowlist(app):
    assert {(m, r.path) for r in app.routes for m in r.methods - {"HEAD"}} == ROUTES

def test_dns_rebinding_host_is_rejected(client)              # Host: evil.example -> 400
def test_post_requires_loopback_origin_and_csrf(client)       # missing Origin / Origin null / wrong token -> 403, no decision
def test_login_token_is_single_use_post_only_and_bounded(client)  # GET with ?token= ignored; 6th failure locks
def test_reviewer_comes_from_session_not_body(client)        # body reviewer_id=mallory ignored or 422; decision.reviewer_id == alice
def test_resubmitted_form_replays_original_decision(client)  # same form twice -> both 303/200 to same decision; one decision row
def test_stale_form_after_other_reviewer_gets_409(client)
def test_old_form_after_restart_is_rejected(tmp_path)        # new SessionRegistry -> 401/403, no second decision
def test_security_headers_on_every_response(client)          # CSP exact string, nosniff, DENY, no-referrer, no-store
def test_ids_are_exact_lookups_not_paths(client)             # ?id=../../etc/passwd -> 404; ?id=%00 -> 404
def test_raw_view_is_escaped_text_and_never_pdf(client)
def test_oversized_body_is_413_before_parsing(client)
def test_bundle_download_is_attachment_json(client)          # Content-Disposition: attachment; application/json
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - The Host check, security headers, and body limit are pure ASGI middleware.
  - Forms are parsed with `parse_qs(body.decode("utf-8"), strict_parsing=True,
    max_num_fields=200, keep_blank_values=True)`.
  - Edits come from repeated, indexed form fields (`edit-N-field_path`, ...) and are validated
    into `CuratorFieldEdit`.
  - The cookie is set with
    `set_cookie("fi3_review_session", token, httponly=True, samesite="strict", path="/review")`.
  - Form `client_event_id` values come from `secrets.token_urlsafe(18)` at render time.
- [ ] **Step 4:** Run. Expected: PASS. Run mypy and ruff.
- [ ] **Step 5: Commit.** `feat(fi3): loopback review app with curator sessions and CSRF`

---

### Task 8: Server CLI and local-only guards

**Files:**
- Create: `backend/ingestion/review_server.py`
- Test: `backend/evals/test_fi3_review_server.py`

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces:
  - `class LocalOnlyError(RuntimeError)`
  - `resolve_bind_host(host: str) -> str`: maps `localhost` to `127.0.0.1`, accepts
    `127.0.0.1` and `::1`, and raises `LocalOnlyError` for anything else
  - `assert_local_profile(env: Mapping[str, str]) -> None`: raises if
    `TRIPWISE_ENV == "production"`
  - `resolve_data_dir(arg: str | None, *, env: Mapping[str, str], repo_root: Path) -> Path`:
    uses `--data-dir`, else `TRIPWISE_DATA_DIR/ingestion`. Missing → `LocalOnlyError`; inside
    `repo_root` → `LocalOnlyError`.
  - `build_runtime(data_dir: Path, seeds_dir: Path, *, now: Callable[[], datetime]) ->
    tuple[FinancialIngestionStore, ReviewService, ActivationPlanner]`. Store path:
    `data_dir/"ingestion.sqlite"`; artifacts: `data_dir/"artifacts"`;
    `id_factory=lambda: uuid.uuid4().hex`.
  - `main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int`:
    - subcommand `add-curator --data-dir --curator-id --display-name`;
    - subcommand `serve --data-dir --seeds-dir (default core.db.SEEDS_DIR) --curator-id
      --port 8765 --host 127.0.0.1`;
    - `serve` prints `FI3 review login token: <token>` to **stderr** once, then runs
      `uvicorn.Server(uvicorn.Config(app, host, port, access_log=False, server_header=False,
      proxy_headers=False, log_level="warning")).run()`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.5", "example.com"])
def test_non_loopback_bind_is_refused(host): ...
def test_production_profile_is_refused(): ...
def test_data_dir_inside_repo_is_refused(tmp_path): ...       # repo_root=tmp_path, data_dir=tmp_path/"x"
def test_serve_refuses_unregistered_curator(tmp_path, capsys)
def test_serve_configures_uvicorn_without_access_log_or_proxy_headers(tmp_path, monkeypatch, capsys):
    # monkeypatch uvicorn.Server.run to capture self.config; assert host == "127.0.0.1",
    # access_log is False, proxy_headers is False; token printed only to stderr, absent from stdout
def test_add_curator_is_idempotent_and_validates_handle(tmp_path)  # "Alice@x" -> exit 2
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3: Implement** with `argparse`. Bind guard before production guard before data-dir
  guard; there is no network activity before `serve` starts uvicorn.
- [ ] **Step 4:** Run. Expected: PASS. Run mypy and ruff.
- [ ] **Step 5: Commit.** `feat(fi3): local-only review server CLI`

---

### Task 9: Boundaries, end-to-end acceptance, schema snapshot, and closure

**Files:**
- Create: `backend/evals/test_fi3_acceptance.py`, `backend/evals/fixtures/fi3_review_openapi.json`
- Create: `reports/fi3_review_activation_dry_run.md`; append to `DEVIATIONS.md`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the failing tests**

```python
def test_product_api_has_no_review_surface():
    from api.main import app
    assert not [p for p in app.openapi()["paths"] if p.startswith("/review")]

def test_deploy_files_never_reference_the_review_server():
    for f in ["deploy/compose.yaml", "deploy/compose.catalogs.yaml", "deploy/nginx/default.conf", "backend/Dockerfile"]:
        assert "review_server" not in text(f) and "ingestion.review" not in text(f)

def test_operator_schema_snapshot_is_deterministic_and_committed():
    # create_review_app(...).openapi() twice -> equal; json.dumps(indent=2, sort_keys=True)+"\n" == fixture bytes

def test_fi3_modules_respect_trust_boundaries():
    # AST over ingestion/review*.py and ingestion/activation.py: no import of accounts, agents, api,
    # gateway.travel, httpx, requests, socket, subprocess; no Name/Attribute in
    # {"seed_database","load_kb","DB_PATH","relative_path","write_text","write_bytes"}

def test_end_to_end_flow_is_offline_and_mutates_nothing(tmp_path, monkeypatch):
    # block socket.connect; hash backend/core/seeds/**, backend/evals/golden/**, contract/openapi.json,
    # and core.db.DB_PATH if it exists
    # through TestClient: login -> view -> approve -> bundle -> dry-run (seeds_dir = real SEEDS_DIR, read-only)
    # assert all hashes unchanged, dry-run applicable, entry status "would_update"
```

- [ ] **Step 2:** Run. Expected: FAIL (snapshot missing).
- [ ] **Step 3:** Generate `fi3_review_openapi.json` from `create_review_app(...).openapi()` with
  `json.dumps(..., indent=2, sort_keys=True) + "\n"`. Review the paths against `ROUTES`, then
  commit it.
- [ ] **Step 4:** Run `make gate`. Expected:
  - `GATE PASSED`;
  - `GOLDENS_OK`, `CONTRACT_OK` (unchanged), `BRIEFS_IDENTICAL`, `TREE_CLEAN`;
  - the pass count is the baseline plus the FI3 tests.
- [ ] **Step 5:** Ask for an independent read-only whole-branch review (security focus: design §8
  table). Fix verified Critical/Important findings test-first in separate commits.
- [ ] **Step 6:** Write `reports/fi3_review_activation_dry_run.md`. Include:
  - the gate output and test counts;
  - the review findings;
  - which open decisions (design §11) remain open;
  - that there was no apply, no KB/seed/golden write, and no network.

  Append `DEVIATIONS.md` entries for:
  - the schema 3 migration;
  - terminal edited/reverify status;
  - UUID IDs;
  - any Task 0 interface delta.
- [ ] **Step 7: Commit.** `docs(fi3): record review and activation dry-run acceptance`

---

## FI3 gate (from the robust ingestion plan §13, made executable)

| Gate clause | Proven by |
|---|---|
| Approve/edit/reject is auditable | Task 1 audit rollback tests; Task 4 attestation tests; e2e audit events |
| ... and idempotent | Task 1 fingerprint tests; Task 4 replay-after-restart; Task 7 resubmission |
| Stale approvals fail | Task 1 CAS/attestation; Task 3 `current_row_changed`/`unbound_base_row`/`evidence_superseded`; Task 5 stale dry-run |
| Activation dry-run cannot change goldens | Task 5 `test_dry_run_never_writes`; Task 9 e2e hashes; `GOLDENS_OK` |
| Still no automatic KB mutation | Task 9 AST boundary; no apply command exists |

## Execution handoff

The recommended executor is **subagent-driven**. Tasks 3–5 depend on each other's interfaces, and
a missed security defect in Tasks 4–7 would weaken the human-approval trust boundary, so a fresh
reviewer per task is worth the cost.

Skills for the executor:
- `superpowers:subagent-driven-development`
- `superpowers:test-driven-development`
- `superpowers:verification-before-completion`
- `superpowers:requesting-code-review`
- `ecc:security-review` (Tasks 6–8)
