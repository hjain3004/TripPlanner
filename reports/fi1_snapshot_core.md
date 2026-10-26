# FI1 — Snapshot Core and Crawl4AI

Status: **offline development complete; live activation pending**

Branch: `codex/fi1-snapshot-core`  
Worktree: `/Users/himanshu_jain/.codex/worktrees/fi1-snapshot-core/TripPlanner`

## Scope delivered

- Content-addressed, integrity-checked immutable blobs and snapshot manifests with raw/normalized hashes, supersession, fetch-attempt audit records, and deterministic unified diffs.
- Typed fetch protocol and failures for manual uploads and an optional, dynamically imported Crawl4AI v0.9.4 adapter.
- Canonical URL, source-policy, exact page-class, robots, redirect-chain, public-host/DNS, content-type, page, timeout, and domain-delay checks.
- Manual HTML/text/Markdown/CSV capture and optional `pdfplumber` PDF normalization, all using the same artifact/snapshot boundary.
- Offline synthetic success, hostile-content, robots, SSRF/DNS, redirect, oversize, replay, immutable-conflict, PDF, delay, and evidence-contract fixtures.

No authoritative specification, seed value, financial golden, Kernel graph, OpenAPI document, frontend source, provider, model, credential, or live activation path was changed.

## Verification evidence

- Baseline before FI1 edits: `2203 passed, 1 skipped, 3 warnings`.
- `make seed PY=.venv/bin/python`: passed; seeded 42 rows.
- Focused FI0 + FI1 regressions: `33 passed`; FI1-only: `17 passed`.
- Full backend suite on the exact final committed tree: `2220 passed, 1 skipped, 3 warnings`.
- Strict mypy: all existing source packages `185` files clean; `ingestion/` `11` files clean.
- Ruff: required zero-tolerance scopes clean; existing `core/` + `api/` debt remained `8`, below the gate ceiling of `12`.
- Frozen checks: `GOLDENS_OK`, `CONTRACT_OK`, `BRIEFS_IDENTICAL`.
- Final `make gate`: passed on the exact committed clean tree; it reported `2220 passed, 1 skipped, 3 warnings`, mypy clean (`185 + 11` source files), Ruff clean in required scopes, 8 legacy core/api findings under the ceiling of 12, and `TREE_CLEAN`.
- Frontend/OpenAPI/browser checks were not applicable: FI1 changes no frontend or public contract.

## Independent review

An independent read-only whole-branch review was performed against the exact implementation commits. It found no Critical findings. Important findings were fixed test-first across the implementation commits: missing page-class enforcement, missing robots fail-closed behavior, redirect-chain wiring, resolver fail-closed construction, same-instance delay races, PDF routing/media labeling, manual/PDF timeout surfaces, changed-raw lineage, robots wildcard/end-anchor handling, and contradictory evidence-kind/page-class requests.

The reviewer confirmed the final focused suite (`17 passed`) and strict Ruff/mypy checks. The final narrow review of the last media-type fix confirmed that defect is resolved; the four remaining Important items are documented offline/live-activation limitations below, not hidden or waived failures.

## Limitations and safety disposition

- No live Crawl4AI browser was run and the optional `ingestion-local` extra was not installed. No provider/model call, credential, OAuth, spending, crawl, or external network activation occurred.
- The verified Crawl4AI interface does not expose a response-byte cap. FI1 rejects oversized material before persistence and before canonicalization, but cannot prevent the SDK from materializing an oversized result. Live activation requires a transport-level bound or an explicitly reviewed SDK mechanism.
- DNS is checked with an injected resolver before dispatch and revalidated after the result; Crawl4AI's later connection-time hostname resolution is not IP-pinned. Live activation therefore remains disabled pending a connection-pinning transport boundary.
- Domain delay is concurrency-safe within one backend instance but is not a durable cross-process ledger. A scheduler/worker deployment must provide a persistent reservation boundary before activation.
- PDF work is page- and byte-bounded, and the caller timeout returns a typed timeout; Python worker-thread cancellation cannot terminate a parser already executing after `wait_for` returns. A process isolation boundary is required for hostile live PDFs.
- Exact replay attempts remain durable in `fetch_attempts` and audit history; immutable snapshot manifests are not mutated to append duplicate attempts. Changed raw material receives a distinct snapshot identity even when normalized text is unchanged.

These limitations are deliberately fail-closed and do not waive the FI1 offline gate. FI2 extraction, activation, Firecrawl, scheduling, acquisition, and frontend work remain out of scope.

## Deviations

- `FetchResult.normalized_artifact` was added additively so the normalized derivative has a distinct immutable content-addressed reference; the existing FI0 fetch and audit contracts remain compatible.
- Crawl4AI and `pdfplumber` remain optional under the `ingestion-local` extra and are imported only at execution time. The verified official Crawl4AI interfaces used are `AsyncWebCrawler`, `BrowserConfig`, `CrawlerRunConfig`, `CacheMode.BYPASS`, `check_robots_txt`, `max_retries=0`, and `page_timeout`; no undocumented fallback/proxy behavior was used.

