# Sol: change-feed and concurrency design handoff

**Status:** design delivered; implementation and runtime acceptance are not claimed.
**Date:** 2026-11-11.
**Branch:** `codex/sol-feed-concurrency-design`.
**Base:** `a9efea09325a7446e9fa38c10d3d7d6bb0a1ecc0`, confirmed by a successful origin fetch.
**Firecrawl input:** `b7a0057737aca9d55334bb1e24a11c41ccb5c61f`, read without changing its worktree.

## Decisions now available to builders

- [Change feed](../docs/superpowers/specs/2026-11-11-change-feed-design.md): typed event terms,
  semantic identity/corrections, exact evidence, immutable history and CAS lifecycle, v6 after
  Firecrawl v5, public read isolation, bounded changed blocks and resumable role processing.
- [Concurrency](../docs/superpowers/specs/2026-11-11-concurrency-design.md): bounded admission,
  replay when full, atomic confirmed-session/job start, restart semantics, leased single-flight
  catalog loading, interactive/proxy limits, retention and acceptance targets.

The feed keeps source-confirmed news separate from owner-approved KB facts. It explicitly reports
unsupported financial targets instead of assuming a validator is also a review/apply implementation.
The concurrency proposal preserves the existing single-process durable-job behavior and avoids
loading another catalog while the sole resident one is pinned. Neither note claims measured live
capacity or a deployed service.

## Code evidence that shaped the decisions

| Observation | Inspected source |
|---|---|
| Request packages may not import ingestion | `backend/evals/test_fi0_ingestion.py:test_package_boundaries_and_fi0_are_offline_only` |
| Main ingestion schema is v4; Firecrawl input is v5 | `backend/ingestion/migrations.py` at the respective SHAs |
| Immutable snapshot diff has no changed-block API | `backend/ingestion/diff.py:SnapshotDiff`, `diff_text` |
| Extractor commits proposals independently | `backend/ingestion/extraction.py:FinancialExtractor.extract` |
| Review/apply row source supports four entity tables | `backend/ingestion/review_rows.py:SUPPORTED_TABLES` |
| FI2 validator accepts additional transfer/FX models | `backend/ingestion/validation.py:TARGET_MODELS` |
| A queued owned job is considered live through registered handles | `backend/api/job_manager.py:JobManager.start_job`, `get_job` |
| Session save and confirmed-job creation are separate commits | `backend/api/conversation.py:confirm_session` |
| Re-run start has event fingerprint and transactional replay | `backend/api/saved_trips.py:start_rerun`, `backend/accounts/store.py:start_planning_job` |
| All three plan paths create individual worker threads | `backend/api/main.py:plan`, `confirmed_planning.py:start_confirmed_job`, `saved_trips.py:_dispatch_rerun` |
| Global catalog cache lacks locking; adapters keep a strong reference | `backend/gateway/places/adapters/snapshot.py:SnapshotPlaceAdapter._load` |
| Retrieval repeatedly scans and sorts candidates | `backend/agents/retrieval.py:get_catalog_poi`, `retrieve_candidates` |
| Proxy already overwrites forwarding headers; traces contain artifact hashes | `deploy/nginx/default.conf`, `backend/agents/trace.py` |

Read the supplied November 11 plans and load-test scripts from the primary checkout without
copying or editing them. Their Linux benchmark is reported evidence, not a run performed here.
The driver assumes a successful start response; the implementation handoff explicitly requires
classifying expected overload rather than treating a missing `job_id` as a transport failure.

Read-only inspection of the ignored primary catalog sidecars/file sizes found Singapore 28,540
places/about 19 MB and New York 56,172/about 38 MB. Streaming byte-marker counts for their claim
fields were 85,620 and 168,516. This informed finite parsing ceilings; it is not a parser validation,
memory benchmark, data verification or capacity result. No full catalogs were copied or loaded.

## Verification performed

- Documentation references and existing symbol assertions: checked with a small standard-library
  script; design-only signatures/acceptance commands are explicitly labeled as future deliverables.
- `git diff --check`: passed before commit.
- Changed paths: this report, the two design notes and appended `DEVIATIONS.md` only.
- Authoritative specs, application/test/deployment code, seeds, goldens, contract and frontend:
  unchanged by this task.
- No application suite or `make gate` was run for this documentation-only change. No application
  success is inferred from documentation checks.

## Handoff and remaining dependencies

Argon can use the C design after the Firecrawl reconciliation base is available, then hand its
feature SHA to Flash for storage; Luna follows the completed reader. D waits for stream A's actual
budgeted-client interface and the published owner decision for the new runtime roles. Sonnet's B
implementation waits for the completed A handoff so dispatch/input changes have one owner.

The runtime-LLM design is not yet present on this base. B depends on its completed interfaces;
the note deliberately adds no speculative runtime factory or new provider API. The owner must
approve source-display permissions and financial facts separately. No live allowance is requested
or consumed by this design task.

Sol's later corroboration design needs D; deployment checklist needs A/B/D and the private/public
access decision. Those queued tasks are not claimed complete. The proposed demo module names in
the notes are implementation deliverables, not existing commands executed in this session.

No paid/free-tier model call, source fetch, Firecrawl credit, credential creation, provider
activation, provisioning or financial approval/application occurred. The primary checkout and
other worktrees were not edited. Required implementation gates and exact-commit independent
reviews belong to the completed implementation branches.
