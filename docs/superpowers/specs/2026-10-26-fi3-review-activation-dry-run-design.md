# FI3 — Human Review and Activation Dry-Run: Design

**Status:** design for review. Provisional against FI2 commit
`c925d98077dd94a1f24d7c312243bfcee78f2d3c`. Not implemented.
**Date:** 2026-10-26
**Authority:** implements the FI3 row of
[`2026-10-07-robust-financial-ingestion.md` §13](../plans/2026-10-07-robust-financial-ingestion.md#13-implementation-sequence-and-gates)
under [spec 05](../../specs/05_ingestion_pipeline_phase2.md) and
[spec 06](../../specs/06_implementation_protocol.md). Specs win over this document.
**Implementation plan:** [`2026-10-26-fi3-review-activation-dry-run.md`](../plans/2026-10-26-fi3-review-activation-dry-run.md)

## 1. Decision in one paragraph

FI3 adds a curator-only review surface to the existing `backend/ingestion/` package. It runs as
a **separate, loopback-only FastAPI process** that the product application never imports, mounts,
proxies, or deploys. Curators see the current seed row, the proposed row, any edit, field-level
diffs, and the exact quote in its snapshot context, with hashes and lineage. Every view and every
decision re-verifies the evidence. Decisions (approve, edit, reject, reverify) go through the
existing FI0 compare-and-swap (CAS) transaction, hardened for terminal states, atomic re-verify
tasks, and a recorded **attestation** of what was verified. Edits are re-run through FI2's own
`validate_extraction`, so they cannot skip evidence, deterministic parsing, the schema, or sanity
rules. Approved decisions can be compiled into a **deterministic, versioned activation bundle**.
The bundle re-checks every decision from scratch and is dry-run against the current seed YAML in
memory only. FI3 never writes `backend/core/seeds/`, the KB SQLite database, goldens,
`contract/openapi.json`, or `frontend/`.

## 2. Verified starting point (`c925d98`)

`c925d98` is `origin/main` (`6428b78`) plus six FI2 commits; it is not yet on `origin/main`.

### 2.1 What FI3 reuses as-is

| Existing interface | FI3 use |
|---|---|
| `ingestion.storage.FinancialIngestionStore` (`decide_proposal`, `create_proposal`, `get_proposal`, `get_snapshot`, `latest_snapshot`, `list_decisions`, `list_audit_events`) | Queue, CAS, idempotency, audit |
| `ingestion.validation.validate_extraction(...)` | Re-validates curator edits with the same rules as extraction |
| `ingestion.evidence.verify_evidence_span(span, *, snapshot, artifacts)` | Re-verifies on every view, decision, and bundle |
| `ingestion.parsing.parse_field_value(field_path, raw, *, expected)` | Deterministic parsing of edited values (reached through `validate_extraction`) |
| `ingestion.artifacts.ContentAddressedStore.read/put` | Digest-addressed reads; bundle blobs |
| `ingestion.contracts` (`ChangeProposal`, `ReviewDecision`, `EvidenceSpan`, `SnapshotBundle`, `WatchTarget`, `SourcePolicyRecord`, `ReverifyTask`) | Typed state |
| `core.models` (`Card`, `RewardRule`, `Offer`, `PointValuation`, `Provenance`) and `core.db.SEEDS_DIR` | Current-row truth, read only |
| `core.db.KnowledgeBase.from_models(...)` | In-memory dry-run construction check |

### 2.2 Defects FI3 must close first (reproduced on `c925d98`)

Reproduced with a scratch script against `c925d98` using the FI0 test fixtures:

1. **Edited/reverify decisions cannot be followed up.** `decide_proposal` still allows deciding a
   proposal in `edited` or `reverify` status ([storage.py:465](../../../backend/ingestion/storage.py)).
   But `review_decisions.proposal_id` is `UNIQUE` ([storage.py:71](../../../backend/ingestion/storage.py)).
   A second decision therefore raises a raw `sqlite3.IntegrityError`, not a typed store error.
2. **Edits are stored but never validated.** `decide_proposal(status=EDITED, edits={"annual_fee_minor": 1})`
   succeeds with an arbitrary value, no evidence, and no parse.
3. **Generated IDs are reused across restarts.** The default `_next_id` is a per-process counter
   ([storage.py:104](../../../backend/ingestion/storage.py)). After a reopen, a decision received
   `audit-1`, an ID the previous process had already used for an audit event. An injected
   colliding factory produces a raw `IntegrityError` on `review_decisions.id`. The audit
   retry loop ([storage.py:183](../../../backend/ingestion/storage.py)) is unbounded.
4. **A proposal can carry no base-row hash.** `validate_extraction` skips the stale-row check when
   `current_row_hash is None` ([validation.py:236](../../../backend/ingestion/validation.py)).
   Every FI2 test proposal uses `None`.
5. **No atomic reverify.** `put_reverify_task` opens its own transaction, separate from the decision
   ([storage.py:538](../../../backend/ingestion/storage.py)).
6. **PDF evidence verification parses in-process** with `pdfplumber`
   ([evidence.py:53](../../../backend/ingestion/evidence.py)). This is the open FI1 isolation item
   being fixed on another branch. FI3 must not add a second in-process PDF path.

## 3. Process and contract boundary

```text
  product: api.main:app ──(contract/openapi.json, spec 12)──> frontend/   [unchanged]

  operator (local only):
  python -m ingestion.review_server serve ──> ingestion.review_app (FastAPI, 127.0.0.1)
        │                                       │
        │                                       ├─ ingestion.review    (context, decisions, edits)
        │                                       ├─ ingestion.activation(bundles, dry-run)
        │                                       └─ ingestion.review_html (escaped server HTML)
        └─ FinancialIngestionStore (ingestion.sqlite) + ContentAddressedStore + seeds (read-only)
```

- **Why a separate app.** Spec 05 §6 calls for a "minimal FastAPI page" for curators. Spec 12 §1
  makes `api.main:app`'s schema the only contract for the product frontend. Mounting curator
  routes on the product app would put approval authority on the public surface, force
  operator routes into `contract/openapi.json`/codegen/MSW, and open a path through D1's nginx
  `/api/` proxy. The FI0 boundary test already forbids `api/` from importing `ingestion/`.
- **Not a second public frontend.** The review UI is server-rendered HTML with no JavaScript. It
  is not in `frontend/`, not in `deploy/compose.yaml`, not behind `deploy/nginx/default.conf`,
  and not started by `backend/Dockerfile`. Tests pin all of this.
- **Not silent contract bypass.** The operator app has its own committed schema snapshot
  (`backend/evals/fixtures/fi3_review_openapi.json`). A test enforces it and an exact route
  allowlist. Another test asserts `api.main.app.openapi()` has no `/review` path, so
  `contract/openapi.json` stays byte-identical (`CONTRACT_OK`). If the review UI ever moves into
  `frontend/`, it must follow the spec 12 §8 one-PR rule; that is a new decision, not an FI3
  default. The choice is logged in `DEVIATIONS.md`.
- **Local only.**
  - It binds only to `127.0.0.1` or `::1`; any other host fails at start-up.
  - It refuses to start when `TRIPWISE_ENV=production`.
  - The data directory must be outside the Git work tree.
  - Requests whose `Host` is not a loopback name with the configured port get a 400, which
    blocks DNS rebinding.
  - `docs_url`, `redoc_url`, and `openapi_url` are disabled.
  - uvicorn runs with `access_log=False`, `server_header=False`, and `proxy_headers=False`.

## 4. Curator identity, sessions, and CSRF

No new authentication dependency. FI3 does not use the spec 17 accounts store. Product users
must never receive approval authority, and spec 17 defines no curator role.

- **Registry.** A new `curators` table holds insert-only `CuratorRecord{curator_id, display_name,
  created_at}`. The ID is a handle matching `^[a-z0-9][a-z0-9-]{1,31}$`, not an email. Records
  are created only with `python -m ingestion.review_server add-curator`.
- **Launch token.**
  - `serve --curator-id X` refuses to start if X is unregistered.
  - It prints a single-use login token (32 random bytes, 10-minute TTL) to stderr once.
  - The token is entered through a POST form, never a URL, so it never reaches a log or history.
  - Only its SHA-256 is held in memory; comparison is constant-time; five failures invalidate it.
- **Session.**
  - The token is exchanged for an in-memory session (30-minute idle, 8-hour absolute limit).
  - Cookie `fi3_review_session`: `HttpOnly`, `SameSite=Strict`, `Path=/review`, host-only.
    `Secure` is not set, because the origin is loopback HTTP (see §11, D9).
  - A restart invalidates every session; durable state lives only in SQLite.
- **Who decided.** `reviewer_id` always comes from the session, never from the request body.
- **CSRF.** Every POST must pass two checks.
  - Its `Origin` must be one of the three loopback origins for the port; a missing or `null`
    Origin is rejected.
  - It must carry a per-session synchronizer token in a hidden field, compared in constant time.
  - The CSRF token is never a cookie, so another app on `localhost` cannot plant or read it. A
    cookie planted by another local app maps to no server session and gets a 401.
- **Headers on every response:**
  - `Content-Security-Policy: default-src 'none'; style-src 'self'; img-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'`;
  - `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
    and `Cache-Control: no-store`.
  - Pages contain no `<script>` at all.
- **Accepted trust level:** anyone with this machine's local shell can register and act as a
  curator. This suits a single-operator student project; it is open decision D3.

## 5. What the curator sees (`ReviewContext`)

Built by `ReviewService.context(proposal_id)` on every GET and again inside every decision:

- **Rows.**
  - The current row comes from the seed YAML through `SeedRowSource`, normalized as
    `Model.model_validate(row).model_dump(mode="json")`.
  - The proposed row is `proposal.proposed_row`; the edited row is added when edits are present.
  - Field diffs are flattened dotted paths (the same flattening FI2 uses) with
    current / proposed / edited columns and a `changed` flag.
- **Evidence context.**
  - For each span: escaped text around it (`canonical_markdown[start-240:start]`, the quote,
    `[end:end+240]`).
  - The PDF page number, and the snapshot's `raw_sha256` and `normalized_sha256`.
  - The result of re-running `verify_evidence_span` now.
  - Bidi and zero-width characters (U+200B–U+200F, U+202A–U+202E, U+2066–U+2069, U+FEFF) and
    C0 controls other than tab and newline are shown as visible `⟦U+XXXX⟧` markers.
  - No rendered HTML view; raw bytes appear only as escaped text (≤ 256 KiB, never for PDFs).
- **Lineage:** source policy (owner, terms URL and read date, reviewer, retention, attribution) →
  watch target (canonical URL, page kind, manual-only) → snapshot(s) (captured time, engine,
  attempts, final URL) → the supersession chain (bounded walk, 50 steps). The latest snapshot ID
  for the target is also shown.
- **Findings.** Stored FI2 `validation_findings`, plus computed findings, which are never written
  back to the immutable proposal:

| Code | Severity | Condition |
|---|---|---|
| `stored_blocking_finding` | blocking | Any stored finding with severity `blocking` |
| `unsupported_target_table` | blocking | Table not in `SUPPORTED_TABLES` (see D4) |
| `current_row_missing` | blocking | Target ID absent from seeds, or present more than once |
| `unbound_base_row` | blocking | `proposal.current_row_hash is None` |
| `current_row_changed` | blocking | `canonical_row_hash(current) != proposal.current_row_hash` |
| `evidence_integrity_failed` | blocking | Any span fails `verify_evidence_span`, or a lineage snapshot is missing |
| `evidence_superseded` | blocking | The target's latest snapshot is not the proposal's lineage snapshot and has a different `normalized_sha256` |
| `multi_snapshot_lineage` | blocking for **edit** only | `len(proposal.lineage_ids) != 1`; FI2 always emits exactly one |
| `manual_capture` | warning | The watch target is `manual_capture`; a banner says to check for personal data |
| `attribution_required` | warning | The source policy requires attribution |

Approve and edit are refused when any blocking finding exists. Reject and reverify are always
allowed, because a broken proposal must still be closable.

## 6. Decisions

### 6.1 Request and identity

`DecisionRequest{proposal_id, action ∈ approve|edit|reject|reverify, reason (1–1000 chars),
expected_version, client_event_id, curator_confidence, edits}`

- `client_event_id` is generated by the server when it renders the form (a hidden field of 24
  random URL-safe characters). Re-submitting the same form is an idempotent replay.
- `curator_confidence` is required for approve and edit (0.00–1.00, at most two decimal places)
  and forbidden otherwise.
- The canonical request fingerprint is FI0's `_fingerprint_request`, extended additively.
  `curator_confidence` is included only when not `None`, so every existing FI0 fingerprint is
  unchanged.
- Edits are JSON-native values sorted by `field_path`, so `default=str` never applies.

### 6.2 Semantics

| Action | Precondition | Effect, in one SQLite `BEGIN IMMEDIATE` transaction |
|---|---|---|
| approve | Status `pending`; no blocking finding; no edits | Decision `approved` with attestation; proposal `approved`, version + 1; audit `decision` |
| edit | As approve; plus at least one valid edit; edited row ≠ proposed row ≠ current row | Decision `edited` with typed edits and attestation; proposal `edited` |
| reject | Status `pending` | Decision `rejected`; proposal `rejected` |
| reverify | Status `pending` | Decision `reverify`; `ReverifyTask(task_id="reverify:{proposal_id}", target_id=<lineage snapshot's watch target>, priority="normal", prior_evidence_ids=lineage_ids, due_at=now)` inserted in the **same** transaction; proposal `reverify` |

All four outcomes are **terminal** for that proposal. `edited` means "approved with edits", as in
spec 05's status set and the plan's edit-rate metric. `reverify` sends the target back to
fetching, and a new snapshot produces a new proposal. This matches the existing `UNIQUE`
constraint and turns the raw `IntegrityError` into `AlreadyDecidedError`.

### 6.3 Edits cannot bypass evidence or validation

`CuratorFieldEdit{field_path, action ∈ set|revert, proposed_raw_value, quote, occurrence,
snapshot_id, page_number}`

- **`revert`** restores the current value and needs no evidence.
- **`set`** requires:
  - `snapshot_id` equal to the proposal's single lineage snapshot;
  - `quote` that occurs in that snapshot's `canonical_markdown`. If it occurs more than once,
    `occurrence` (1-based) is required; the server derives the offsets and builds the
    `EvidenceSpan(verification="exact")` itself;
  - `page_number` if and only if the snapshot is a PDF;
  - `proposed_raw_value` (≤ 200 chars) occurring inside the NFKC-normalized quote. This rule is
    stricter than FI2's (see D10).
- Neither `field_path` may be `id` or start with `provenance`; activation owns provenance.
- The parsed value must be an `int` (not `bool`), `str`, or `date`. List, dict, boolean, float,
  and untyped leaves are refused as `unsupported_edit_type`.
- **Revalidation by FI2's own code.**
  1. Build an `ExtractionResponse`-shaped dict: the edited row, the surviving FI2 field
     proposals, and the `set` edits, with `extractor_confidence=0.0`.
  2. Call `validate_extraction(..., current_row=<seed row>, current_row_hash=proposal.current_row_hash,
     snapshot=<lineage snapshot>, manual_capture=<page_kind is manual_capture>)`.
  3. Any `ProposalValidationError`, or any blocking finding in the result, refuses the edit.
- **Defense in depth.** The bundle builder never trusts a stored decision. It recomputes the
  edited row from `decision.edits` and requires the hash to equal
  `attestation.resulting_row_sha256`. A decision written directly through
  `FinancialIngestionStore.decide_proposal` with arbitrary edits and no attestation therefore
  cannot reach a bundle.

### 6.4 Attestation and concurrency

`ReviewAttestation{proposal_payload_sha256, current_row_sha256, resulting_row_sha256 | None,
evidence: (EvidenceDigest{snapshot_id, raw_sha256, normalized_sha256}, ...),
computed_finding_codes}`

- Computed from the context and stored inside the decision payload. It is an additive optional
  `ReviewDecision.attestation` field, like FI1's additive `FetchResult.normalized_artifact`.
- Inside `BEGIN IMMEDIATE`, the store re-hashes the stored proposal payload. A mismatch with
  `attestation.proposal_payload_sha256` raises `StaleVersionError`. This closes the gap between
  the service's checks and the write.
- The order of checks is: idempotent replay first (as FI0 does), then version CAS, then the
  terminal-status check, then the edit/status shape, then the attestation hash.
- Two curators racing on one proposal: exactly one decision wins; the other gets
  `StaleVersionError` or `AlreadyDecidedError`, which becomes an HTTP 409 page with a link to the
  fresh state. A lost SQLite write lock is already mapped to `StaleVersionError`.
- **Replay after restart.** A reused `client_event_id` with the same fingerprint returns the
  original decision from SQLite, with no new audit event; a different fingerprint raises
  `IdempotencyConflictError`. An old browser form fails its CSRF check after a restart, because
  the session no longer exists. Neither path can create a second decision.
- **Seed-file race.** The seed YAML lives outside SQLite, so a seed edit between the check and the
  write is not locked out. It is caught later, because the bundle re-checks the current row hash.

### 6.5 Rollback of failed operations

- Each decision, its audit event, and any reverify task commit together or not at all. Tests
  inject a failure in each step and assert that no decision exists, the version is unchanged, and
  no task exists.
- The bundle blob is written to the content-addressed store before its SQLite row. If the row
  insert fails, the only residue is an unreferenced, content-addressed blob, which is harmless,
  and a retry is idempotent.
- No operation in FI3 writes anywhere other than `ingestion.sqlite` and the artifact store.

## 7. Activation bundles and dry-run

### 7.1 Bundle

`ActivationPlanner.build(proposal_ids | None, curator_id, client_event_id)` selects decided
proposals (approved or edited; all of them when `None`).

For each selected proposal it re-verifies, from scratch:
- the decision status, and that an attestation is present;
- the proposal payload hash;
- every evidence span;
- for edits, the recomputed edited-row hash;
- that the current seed row hash equals both `proposal.current_row_hash` and
  `attestation.current_row_sha256`;
- that the table is supported;
- that the target appears only once among the selected proposals.

Any failure becomes a `RefusedEntry{proposal_id, code, message}`. Two approved proposals for the
same target refuse **both** (`conflicting_entries`).

| Bundle field | Content |
|---|---|
| `schema_version` | `"tripwise.financial-activation-bundle/v1"` |
| `seed_files` | `{filename: sha256}` for each consulted seed file, sorted |
| `entries` | Sorted by `(target_table, target_id)`; each holds `base_row_sha256`, `new_row`, `new_row_sha256`, `field_changes`, `unevidenced_fields`, `proposal_id`, `proposal_payload_sha256`, `decision_id`, `decision_status`, `reviewer_id`, `decided_at`, `evidence` digests, `source_url`, `source_type`, `attribution_required` |
| `refused` | Sorted by `proposal_id` |
| `applicable` | `refused == ()` |

- **Provenance replacement**, from spec 05's pipeline:
  - `source_type` is `official_page` for card or offer pages and `tnc_pdf` for T&C PDFs.
  - `verified_by` is the reviewer ID; `last_verified` is the UTC date of `decided_at`;
    `confidence` is `curator_confidence`.
  - `source_url` is the snapshot attempt's final URL, or else the watch target's canonical URL.
  - `needs_verification` is `false`.
  - **Manual captures** keep `source_type="manual_curation"` and `needs_verification=true`
    (plan §6; D2).
  - Every entry also lists the `unevidenced_fields` that row-level provenance would claim without
    field evidence (D1).
- **Determinism.**
  - The canonical bytes are `json.dumps(bundle.model_dump(mode="json"), sort_keys=True,
    separators=(",", ":"), ensure_ascii=False).encode()`.
  - The bundle ID is the SHA-256 of those bytes.
  - No wall-clock value is inside the hashed body. `created_at` and `created_by` live only in the
    audit event.
  - Equal inputs give byte-identical bundles, across restarts and across clocks.
- **Persistence.** The blob goes into `ContentAddressedStore` (`application/json`), and an
  insert-only `activation_bundles` row is keyed by `bundle_sha256`. The same content with any
  `client_event_id` returns the existing record; a reused `client_event_id` with different
  selection raises `IdempotencyConflictError`.

### 7.2 Dry-run comparison

`ActivationPlanner.dry_run(bundle_sha256)` reloads the stored bundle and verifies its blob hash,
then reads the current seeds.

- Each entry gets one status:
  - `would_update`;
  - `stale` (the current row hash ≠ `base_row_sha256`, or a seed file hash changed);
  - `row_missing`;
  - `invalid_row` (the new row fails `Model.model_validate`).
- It overlays the new rows onto **in-memory copies** of all four supported tables and calls
  `KnowledgeBase.from_models(...)`.
- It checks references: every `reward_rules.card_id`, `point_valuations.card_id`, and
  `offers.card_ids` member must exist.
- It reports `seed_files_unchanged` by hashing each seed file before and after.
- It never opens `core.db.DB_PATH`, never calls `seed_database` or `load_kb`, and writes no file.
- Goldens embed their own `kb:` blocks (for example `backend/evals/golden/cap_fallthrough.yaml`),
  so no seed change can move a golden value. FI3 still proves the golden directory and seed
  bytes are unchanged after a full approve → bundle → dry-run flow.

## 8. Required threat and failure coverage

| Concern | Mechanism | Pinned by (plan task) |
|---|---|---|
| Transactional failure / rollback | Single `BEGIN IMMEDIATE` per decision (decision, audit event, task); blob-then-row bundles | T1, T5 |
| Concurrent reviewers | FI0 CAS + attestation re-hash in the transaction; two-connection barrier test; HTTP 409 | T1, T4, T7 |
| Replay after restart | `client_event_id` + fingerprint in SQLite; UUID IDs; sessions in memory only | T1, T4, T7 |
| Untrusted HTML/script | Escaping only through `h()`; visible bidi/zero-width markers; CSP with no script; plain-text raw view; no rendered HTML | T6, T7 |
| Path traversal | IDs passed as query/form values and looked up exactly in SQLite; artifacts read only by validated digest; `relative_path` never dereferenced (AST check) | T3, T7, T9 |
| Evidence tampering | `verify_evidence_span` on view, decision, and bundle; attestation digests; proposal payload hash; bundle blob hash re-verified | T3, T4, T5 |
| Manual provenance | `manual_capture` warning; no `provenance.*` edits; manual entries stay `manual_curation` with `needs_verification=true` | T4, T5 |
| Privacy | Curator handle only; no request bodies or snapshot text in logs; access log off; token never in a URL; data dir outside the repo; bundles never in Git | T7, T8 |
| Stale approvals | Version CAS; `current_row_changed`; `unbound_base_row`; `evidence_superseded`; bundle-time re-check; dry-run `stale` | T3, T4, T5 |
| Blocking findings | Stored and computed blocking findings refuse approve/edit in the service; storage refuses stored ones | T3, T4 |
| No KB mutation / goldens | AST forbids `seed_database`, `load_kb`, `DB_PATH`, `write_text`, `write_bytes`; byte hashes of seeds, goldens, and KB DB unchanged after the e2e flow | T9 |
| Product isolation | No `/review` in `api.main.app.openapi()`; deploy files never reference the review server | T9 |
| Local only | Bind refusal, production refusal, `Host` and `Origin` allowlists | T7, T8 |

## 9. Privacy and retention

- Curator records hold a handle and a display name only. They are operator audit records, not
  spec 17 user data, so spec 17 export/delete does not apply. Deleting a curator would break the
  audit chain, so FI3 provides no delete (D11).
- Snapshots are public pages, except manual captures, which may contain personal data by accident.
  FI3 adds a visible warning, not automated PII detection.
- Error pages show typed codes, never stack traces or snapshot text. Diagnostics stay within FI0's
  1000-character limit.
- The data directory (`--data-dir` or `TRIPWISE_DATA_DIR`) must resolve outside the repository.

## 10. Explicit non-scope

FI3 does not:
- apply bundles to seeds or the KB, or add any `apply` command;
- add Firecrawl, scheduling, or a staleness sweeper;
- promote evidence-graph claims (they stay `VERIFY_REQUIRED`);
- add metrics dashboards (FI6);
- add discovery-candidate promotion UI (`policy.promote_candidate_to_watch_target` stays CLI/code);
- support insert or delete operations;
- add a rendered HTML snapshot view, JavaScript, or a frontend change;
- change OpenAPI, accounts integration, deployment, or dependencies.

## 11. Open decisions

These are material and unresolved; FI3 ships the stated default.

| ID | Question | FI3 default | Who and when |
|---|---|---|---|
| D1 | Spec 05 provenance is row-level, but evidence is field-level. Should an approval clear `needs_verification` for fields it never quoted? | Spec 05 literal (`false` for official/T&C), and every entry lists `unevidenced_fields`. Nothing is applied in FI3. | Human, **before any apply step (FI5)** |
| D2 | May a manual capture become `official_page`/`tnc_pdf` once a curator confirms the primary URL (plan §6)? | No. It stays `manual_curation` with `needs_verification=true`. | Human, before FI5 |
| D3 | Is "local shell access = curator", with a per-launch token, an acceptable identity strength? | Yes for the student profile; no accounts linkage. | Human acknowledgement |
| D4 | Supported tables | `cards`, `reward_rules`, `offers`, `point_valuations` only. `transfer_*` are refused because the graph is fictional (plan §3); `fx_rates` are refused because they have no `id` and G2 owns FX. | Human, if FX or transfer facts are wanted |
| D5 | Operator surface outside `contract/openapi.json` (separate app, own snapshot) | Separate app, logged in `DEVIATIONS.md`. | Human may require the spec 12 route instead |
| D7 | Should approvals expire before bundling? | No expiry; staleness comes only from hashes. | Revisit at FI6 |
| D10 | Should FI2 extraction also require `proposed_raw_value` to occur inside its quote? | FI3 enforces it for edits only and does not change FI2. | Recheck after Luna's integration |

Smaller defaults chosen without escalation:
- D6: no rendered HTML view.
- D8: no audit hash chain; tampering is detected through content hashes and the attestation.
- D9: no `Secure` cookie flag on loopback HTTP.
- D11: no curator disable or delete; deferred.

## 12. Recheck after Luna's integration lands

The plan's Task 0 re-verifies each of these at the integration commit before any code is written:

| Interface | Why FI3 depends on it |
|---|---|
| `ingestion.evidence.verify_evidence_span` signature and PDF path | Injected as `evidence_verifier`. The PDF fix may move parsing out of process and change its signature or error type. |
| `ingestion.canonical.*`, `ingestion.fetch.ManualUploadBackend` | Test fixtures build snapshots through them |
| `ingestion.parsing.parse_field_value`, `UnresolvedValueError` | Determine which edits parse and what the edit-type rule sees |
| `ingestion.validation.validate_extraction` (kwargs, `ProposalValidationError`, `_row_hash` algorithm, finding codes, `proposal_id` format) | Edit revalidation; the `canonical_row_hash` equivalence test |
| `ingestion.contracts`: `ChangeProposal`, `ReviewDecision`, `EvidenceSpan`, `SnapshotBundle`, `ImmutableArtifactRef` | Additive fields; JSON payload hashing |
| `ingestion.storage.decide_proposal`, `_fingerprint_request`, `_SCHEMA`; `ingestion.migrations.SCHEMA_VERSION` (2 on `c925d98`) | FI3 adds schema 3. A concurrent schema 3 elsewhere must be renumbered. |
| `ingestion.extraction.FinancialExtractor` lineage cardinality (one snapshot) | `multi_snapshot_lineage` rule |
| `Makefile` `gate` ingestion scope; `evals/test_fi0_ingestion.py` boundary glob (non-recursive) | FI3 keeps flat module files so the existing glob covers them |
| `DEVIATIONS.md` tail and the FI2 report | Context for the FI3 entries |

## 13. References

- [Spec 05 — offline ingestion and human review](../../specs/05_ingestion_pipeline_phase2.md)
- [Spec 06 — implementation protocol](../../specs/06_implementation_protocol.md)
- [Spec 12 — integration contract](../../specs/12_integration_contract.md)
- [Spec 17 — accounts and persistence](../../specs/17_accounts_and_persistence.md)
- [Robust financial ingestion plan](../plans/2026-10-07-robust-financial-ingestion.md)
- [FI0 report](../../../reports/fi0_financial_ingestion_foundation.md),
  [FI1 report](../../../reports/fi1_snapshot_core.md),
  [FI2 report](../../../reports/fi2_extraction_validation.md)
