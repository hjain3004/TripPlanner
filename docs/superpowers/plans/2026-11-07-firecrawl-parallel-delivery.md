# Firecrawl Parallel Delivery Implementation Plan

> **For agentic workers:** Use the four owner assignments below. Each owner implements their track natively; one independent reviewer examines the completed integrated change. Do not create another agent hierarchy or per-subtask review/gate loop.

**Goal:** An operator fetches approved issuer HTML/PDF documents through Firecrawl, obtains immutable evidence and validated pending proposals, inspects them in the existing review queue, and refreshes the same bounded watchlist without duplicate calls or proposals.

**Architecture:** Extend the existing `FetchBackend` → `SnapshotService` → `FinancialExtractor` → review workflow. A small SQLite control layer reserves usage and domain dispatches durably; an operator command runs bounded acquisitions and due refreshes. Existing human approvals, bundles, scratch apply and rollback remain the only fact-activation path.

**Tech Stack:** Existing Python backend, SQLite, application-owned Firecrawl transport, existing extraction client interface and operator CLI. Do not add a service, queue framework, frontend, self-hosted Firecrawl installation or runtime provider discovery.

**Spec:** `docs/specs/05_ingestion_pipeline_phase2.md`, relevant boundaries in specs 06/09/16, and `docs/superpowers/plans/2026-10-07-robust-financial-ingestion.md`. The owner's 2026-11-07 direction makes Firecrawl the preferred acquisition backend; Crawl4AI remains optional.

## Global Constraints

- Financial values are parsed/validated by existing deterministic code. LLMs quote raw notation; they never calculate rewards, taxes, ratios or conversions.
- Curators approve financial facts. This implementation never impersonates a curator, confirms source origin automatically, clears verification on its own or writes repository seeds.
- Source policies and robots checks remain required. Public visibility and Firecrawl access do not authorize an issuer source.
- External spend stays USD 0 out of pocket. Credentials, account setup, billable options and live calls require existing explicit permission or a bounded human approval.
- No credential/secret, raw private capture or real unapproved financial fixture enters Git. Normal checks never call a live provider.
- Frozen arithmetic, goldens, authoritative specs, accounts, planning APIs and frontend stay unchanged.
- Existing manual capture, review, bundle, scratch apply and rollback behavior must remain usable.
- Keep failure handling truthful. A returned document can still be an upstream error/login/challenge page; HTTP success from Firecrawl is not proof of issuer content.
- Approximately 2.9 GiB was free at planning time. Reuse existing tools/environments without modifying another owner's installation. No blanket cache/worktree deletion or duplicated frontend dependencies.

## Starting State and Baseline

- Existing `codex/firecrawl-ingestion` worktree is clean at `00d9cf0`, based on the financial-readiness work. It contains no Firecrawl implementation yet.
- The last inspected `origin/main` is `a9efea0`. Fetch and use the current accepted main at execution time. Do not reset the older task branch or overwrite this plan; preserve any newly appeared changes and merge/reconcile normally.
- `FetchBackend.fetch(FetchRequest) -> FetchResult` already exists in `ingestion/fetch.py`.
- Snapshot capture, diffing, artifact storage, exact evidence validation, curator review, controlled scratch apply and rollback exist.
- `config_loaders.py` currently rejects every Firecrawl target. The coordinator owns replacing that blanket rejection with explicit eligibility checks.
- Firecrawl CLI `1.19.29` is installed locally. This is not a Python SDK installation or application integration. Inspect current supported SDK/REST behavior before choosing the narrow transport; do not install another CLI.
- Source packet: `~/tripwise-ingestion-data/issuer-evidence-packet-20261106/cfg/sonnet_handoff.json`. Its issuer values and policies are drafts. Verify actual captures/permissions and do not copy its financial claims into approved data.

## Definition of Done

1. A real permitted HTML acquisition reaches stored snapshot, extraction and pending review through the real operator entry point; execution mode is labelled.
2. A permitted issuer PDF follows a bounded, page-aware path with its original PDF bytes retained when claiming PDF page evidence. Otherwise the output is explicitly a text derivative, not a substitute for original PDF evidence.
3. The operator can refresh a bounded approved watchlist and inspect `changed`, `unchanged`, `blocked`, `failed` or `needs_reconciliation` results.
4. Unchanged content makes no extraction call and creates no duplicate proposal. Changed content creates new evidence/lineage while old captures and decisions survive.
5. A real process restart preserves completed outcomes, usage reservations and pending work; interrupted/ambiguous dispatch does not silently reissue a paid request.
6. Existing curator approval, dry-run and scratch apply/rollback still work. Repository seeds and goldens remain unchanged.
7. Integrated exact committed-tree gate and applicable CI pass. A missing live permission is reported as pending live acceptance, not called a complete live milestone.

## Dependency Graph

```text
Coordinator: inspect current main + settle minimal shared interfaces + prepare executable live request
                  │
       ┌──────────┼─────────────┬────────────────┐
       ▼          ▼             ▼                ▼
 A transport   B workflow    C durable control  D source/extraction/pilot
       │          │             │                │
       └──────────┴─────────────┴────────────────┘
                  ▼
        First real HTML → pending review
                  ▼
        PDF + bounded due-refresh + restart recovery
                  ▼
        One integrated review, final gate and PR
```

The interfaces are the only short serial setup. The first live document must not wait for a finished scheduler, dashboard or a large fixture corpus. No calendar-time promise is made before account/source permission and the first response are checked.

## Shared Interface Agreement

Coordinator records a minimal executable interface commit before owners branch. Reuse existing models; introduce only the small missing control/result types. Do not implement placeholder production success.

- **A:** `FirecrawlBackend(...).fetch(request: FetchRequest) -> FetchResult` is async and implements the existing fetch protocol. Transport is injected and has exactly one basic scrape dispatch operation, bounded by timeout/response size. The transport models its actual observed/documented wire fields; do not guess SDK signatures.
- **C:** `AcquisitionControl.claim(request: FetchRequest, *, policy_hash: str, estimated_credits: int, now: datetime) -> AcquisitionClaim` atomically returns either dispatch permission, a previously stored `FetchResult`, or a typed blocked/pending/conflict outcome.
- **C:** `AcquisitionControl.complete(request_id: str, *, result: FetchResult, charged_credits: int | None, now: datetime) -> None` records terminal or uncertain completion. Unknown charges retain their reservation. A owns invoking this at the provider boundary; B must not independently reserve again.
- **C:** `AcquisitionControl.due_targets(targets: Sequence[WatchTarget], *, now: datetime, limit: int) -> list[str]` returns bounded stable-order target IDs. Existing watch intervals and source policy are inputs, not new financial freshness rules.
- **B:** `AcquisitionService.run_target(target_id: str, *, client_event_id: str, extractor_client: LLMClient) -> AcquisitionOutcome` is the public orchestration seam. `AcquisitionOutcome` identifies request/attempt/snapshot/proposal IDs, state and safe diagnostic; it contains no secrets or copied full page text.
- **D:** `build_financial_extraction_client(config) -> LLMClient` uses the existing client boundary. Modes are explicit: already-authorized real client, local client, scripted replay or curator-authored extraction. No hidden model retry or second extraction engine.
- Same id/different request, policy or mode is a typed conflict. C records a canonical fingerprint. IDs/fingerprints also bind freshness intent so an explicit refresh is not confused with replay.
- Boundary names can change once during setup if existing code provides a better equivalent. After parallel work begins, coordinate interface changes explicitly; do not silently fork definitions.

## Owner A — Firecrawl Acquisition Transport

**Suggested model:** Sonnet or another strong backend implementer.

**Files:** Create `backend/ingestion/firecrawl_backend.py`, `backend/ingestion/firecrawl_transport.py`; focused `backend/evals/test_firecrawl_backend.py`. Own shared wire types only after interface agreement. Do not edit the CLI, storage/migrations, extraction validator or global reports.

**Consumes:** Existing fetch/artifact/preflight contracts; C's injected control interface.
**Produces:** A usable Firecrawl `FetchBackend` and normalized artifact result with bounded errors.

- [ ] Verify current Firecrawl scrape contract against installed tooling and primary documentation. Choose one application transport. An installed CLI is evidence of tooling availability, not a reason to spawn an unconstrained shell or reuse its credential store implicitly.
- [ ] Implement fixed/explicit endpoint policy, secret-safe config, bounded response reading and deadline/cancellation. Ordinary requests use no automatic client retries.
- [ ] Make options explicit: basic document formats, freshness policy, parser behavior and no browser actions. Start with basic proxy mode, with no automatic enhanced-proxy escalation around source restrictions. Firecrawl defaults allow cached results; apply the requested freshness setting and preserve provider cache/acquisition metadata honestly.
- [ ] Start HTML-only. Explicitly turn off unrequested PDF/image parsing so default parsing cannot introduce variable page charges. Stop on unsupported media or scope rather than silently adding paid features.
- [ ] Preflight before reservation/dispatch; reserve via C immediately before dispatch. Reject target error/login/challenge documents, unsupported or unestablished source identity, oversize and malformed results with typed outcomes.
- [ ] Preserve returned source material, provider envelope/acquisition metadata and hashes as distinct evidence where needed. Never claim provider-rendered HTML is an original issuer HTTP body or complete redirect transcript.
- [ ] Add the PDF acquisition route after HTML succeeds: prefer original bytes returned through a documented bounded option plus existing isolated local parsing. Firecrawl's documented parser-disabled PDF/base64 option is a candidate, not an observed-contract proof. Verify actual behavior and response bounds before use. Paid PDF parsing escalation is separately costed and explicitly approved; processed text alone cannot fabricate page evidence.
- [ ] Own all authorized live Firecrawl dispatches for the team. Capture once, keep needed metadata through normalization, share sanitized retained results and request IDs. Other agents do not repeat the request.

## Owner B — Operator Workflow and Integration

**Suggested model:** Luna; also the integration owner.

**Files:** Create `backend/ingestion/acquisition.py`; own necessary changes in `config_loaders.py`, `review_server.py`, `staging.py` and dependency/package/env declarations; focused `backend/evals/test_ingestion_acquisition.py`. Own the shared plan/DEVIATIONS entry and final report. Avoid refactoring existing manual staging.

**Consumes:** A's `FetchBackend`, C's control/due-target query, D's extraction client and source fixtures.
**Produces:** The actual URL-to-review CLI and the integrated branch.

- [ ] Publish the small shared-interface agreement and common base; check that incoming work does not recreate existing storage or parsers.
- [ ] Replace Firecrawl's blanket loader rejection with explicitly enabled account/cost/source eligibility. Manual-only policy remains manual-only. No new implicit source permissions.
- [ ] Add `acquire` and `refresh-due` subcommands to the existing operator CLI, or an equally small dedicated CLI if existing parsing makes that less invasive. Document the exact invocation. Inputs are approved target IDs/config, not an unrestricted URL/endpoint pass-through.
- [ ] Connect fetch → attempt → snapshot → comparison → existing `FinancialExtractor` → pending proposal. Preserve source mode; a real fetch must not be relabelled manual, and a curator-authored extraction must not be labelled LLM-generated.
- [ ] Persist evidence before downstream extraction so parsing/model failure does not require another fetch. Resume from retained results after restart. Reuse insert/update validation rather than calling internal manual-upload flow that hardcodes manual provenance.
- [ ] Implement a bounded serial watchlist pass using C's due-target selection. Skip unchanged content without LLM calls. A changed raw capture with equivalent normalized text preserves evidence/lineage but does not create a duplicate financial proposal.
- [ ] Keep existing `inspect`, `review-queue`, decisions, bundle and scratch apply/rollback connected. Do not add autonomous apply or a public webhook/API.
- [ ] Merge other tracks at their first working checkpoints; run the real workflow promptly. Do not wait until every owner writes a polished report.

## Owner C — Durable Usage, Throttling and Recovery

**Suggested model:** Gemini Argon, Terra or Opus.

**Files:** Create `backend/ingestion/acquisition_control.py`; sole owner of necessary `storage.py`/`migrations.py` changes and control-table migration; focused `backend/evals/test_acquisition_control.py`. B and A must not edit those storage files concurrently.

**Consumes:** Existing request/target/result contracts and reviewed rate/budget configuration.
**Produces:** Atomic request reservation/replay and bounded due refresh across processes.

- [ ] Implement the agreed control interface using existing SQLite transaction/audit patterns. Reuse the ingestion store where practical; no Redis, Celery, distributed service or unnecessary new persistence framework.
- [ ] Reserve per-request/run/month credit allowance and per-domain next dispatch in a transaction before network I/O. Concurrent processes cannot both spend the same slot or violate domain delay.
- [ ] Store fingerprint, request state, owner/lease if needed, timestamps, cost estimate, pricing version, result references and safe terminal reason. The source policy's minimum delay and configured watch interval stay authoritative.
- [ ] A timeout/crash after possible dispatch remains spent/uncertain until reconciliation. Never refund merely because no content reached B. No claim of exactly-once upstream execution without documented provider support.
- [ ] Same request completed → replay stored result without dispatch; same key/different fingerprint → typed conflict; interrupted dispatch → `needs_reconciliation`, never automatic paid retry. Expose a narrow operator status/recovery action with audit, not SQL surgery.
- [ ] Keep completed history and previous artifact references. Limit retries/reservations; no unbounded database retry loop.
- [ ] Demonstrate two actual processes sharing SQLite for budget/domain reservation and a kill/reopen recovery example. These checks address concrete paid-call and loss risks; do not create a mutation-test campaign.

## Owner D — Extraction Binding and Real-Document Acceptance

**Suggested model:** The fourth agent; use a strong model for extraction/evidence work. A weaker Flash agent can prepare source fixtures and commands, with integration review by B.

**Files:** Create `backend/ingestion/extraction_runtime.py`, `backend/evals/demo_firecrawl_ingestion.py`, and focused `backend/evals/test_firecrawl_extraction_flow.py`. Source manifests, captured documents and approval packets remain in a private task data directory. Do not edit parser math, validator rules, transport, storage, CLI dispatch or repository seeds.

**Consumes:** B's public orchestration seam, A's retained response, existing `FinancialExtractor`, issuer source packet and current approved policies.
**Produces:** Configured extraction through the existing client interface and a reproducible real-process operator demonstration, not another readiness report.

- [ ] Check the issuer packet against actual primary captures. Treat inferred fees, spend windows, transfer mappings and caps as draft claims; remove unsupported assumptions from proposed extraction data. Do not approve facts or source terms as the owner.
- [ ] Prepare one HTML and one relevant PDF target with source-policy/robots evidence. Where automation permission is absent, prepare the exact owner decision instead of manufacturing an allowed policy. Controlled-source transport acceptance may proceed separately if authorized, labelled as such.
- [ ] Bind the existing extraction client with an explicit mode and budget. Existing hosted/local credentials and model calls need their applicable authorization. Scripted replay proves integration only; a curator-authored response is labelled curator-authored. No hidden fallback that reports automated extraction success.
- [ ] Create the real operator demonstration: acquire → inspect stored snapshot/evidence → extract → review queue → reopen in another process → rerun same event with no new Firecrawl dispatch → explicit refresh unchanged → changed controlled document produces a new pending proposal.
- [ ] Use a project-controlled changed-document fixture for deterministic refresh/cancellation checks rather than scraping an issuer repeatedly. Retained live capture proves provider compatibility; fixture mutation proves changed-content behavior. State the distinction.
- [ ] Read at least one original PDF through the actual installed parser in the isolated production path when demonstrating PDF evidence. Existing synthetic parser coverage is not proof of actual-document compatibility.
- [ ] Produce a concise human decision packet only for remaining source/financial approvals. Do not withhold the working command until every issuer is catalogued.

## Review Focus

- Price/permission drift: undocumented options or PDF defaults consume more than reserved, or an agent invents source approval.
- Evidence drift: cleaned HTML/Markdown or PDF-derived text is falsely presented as original bytes/page evidence; freshness metadata is restamped during replay.
- Duplicate paid work: crashes, concurrent runners, changing event fingerprints or model failure cause silent remote redispatch.
- False success: a cached/error/login page reaches the validator as current official evidence; scripted extraction is described as a live model.
- History loss: unchanged/changed refresh overwrites evidence, proposals or decisions, or changes active seeds without explicit approval.

## Execution Checkpoints

### Checkpoint 0 — Shared base and explicit live prerequisites

- [ ] B fetches current main and records exact baseline, file ownership and interface commit. All owners use that base in separate worktrees. Preserve the existing clean task branch and prior integration acceptance work.
- [ ] A/D prepare one concrete live invocation, exact URL, allowed options, maximum call/credit allowance and retention. Confirm credentials/account no-overage posture and source authorization. Ask only for missing permissions; planning alone does not authorize live calls or signing terms.
- [ ] Others implement against the injected existing interfaces while permission is pending. No developer automatically marks a source policy reviewed by the owner.

### Checkpoint 1 — HTML reaches review

- [ ] A executes the one authorized request through B's actual operator entry point and retains it in memory through normalization/storage. Do not replace that proof with an isolated SDK snippet or run all gates between authentication and that dependent workflow.
- [ ] B/D run the actual CLI into existing pending review; label extraction mode. C records actual request outcome and conservative credit use.
- [ ] If only scripted extraction ran, call this acquisition+replay acceptance. End-to-end automatic extraction remains pending until the actual configured authorized extractor is exercised.

### Checkpoint 2 — PDF, refresh and restart

- [ ] Complete bounded PDF handling, stable due-target selection, source delay, no-change suppression, changed-document lineage and interrupted-call recovery.
- [ ] Exercise real process restart and concurrent reservation. No need for a public daemon/endpoint; `refresh-due` can later be invoked by an external scheduler.

### Checkpoint 3 — Integration and delivery

- [ ] B integrates normal commits, preserving work and resolving shared DEVIATIONS/config changes. Owners run focused checks for their work; no repeated full gate on every tiny step.
- [ ] One independent whole-change review focuses on actual risks above. Fix reproduced material findings.
- [ ] Run `make seed` and the existing unchanged `make gate` from the proper configured backend environment on the exact committed clean integrated tree. Provision catalogs without committing them. Run meaningful wheel/CLI checks if packaging changed. No frontend/browser campaign when neither API nor UI changed.
- [ ] Record results in `reports/firecrawl_ingestion.md` and the PR acceptance record. Push/open a normal integration PR; merge only if explicitly authorized separately. Source worktrees/branches remain preserved.

## Explicitly Later

Large issuer crawling, general web search, Firecrawl Agent, paid JSON/highlights/Interact escalation, hosted monitors/webhooks, always-on scheduler deployment, approved real-fact replacement and new financial schema semantics are not needed for this delivery. Do not call them implemented. After the baseline works, choose only capabilities needed by a demonstrated source problem.

## Primary Documentation Rechecked 2026-11-07

- Python interface: https://docs.firecrawl.dev/agent-source-of-truth/python
- Scrape request/response/defaults: https://docs.firecrawl.dev/api-reference/endpoint/scrape
- Billing/options: https://docs.firecrawl.dev/billing

Live request schemas and billing must be rechecked at execution. No blanket claim of zero-charge hosted usage can be made from local counters or free-credit marketing alone.
