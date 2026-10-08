# Robust Financial Ingestion — Existing-Code Audit and Implementation Plan

**Status:** design ready for review; no ingestion implementation has started  
**Date verified:** 2026-10-07  
**Authority:** supplements, but does not replace, `docs/specs/05_ingestion_pipeline_phase2.md`; specs 01, 05, 06, 09, and 16 remain binding  
**Scope:** offline ingestion of slowly changing card, reward-rule, valuation, offer, and transfer/reference facts; never request-time travel inventory

## 1. Decision in one paragraph

Build one offline, human-reviewed ingestion pipeline behind a small provider interface. Crawl4AI
v0.9.4 is the zero-cost default fetcher. Firecrawl v2.11.0 is an explicitly budgeted escalation
and verification layer for hard JavaScript pages, complex PDFs, selective structured extraction,
and low-frequency change monitors. Both engines must emit the same local snapshot contract; all
later stages—normalization, diffing, evidence extraction, deterministic validation, review, and
activation—are provider-independent. A blocked, login-walled, CAPTCHA-protected, or automation-
prohibited page becomes `manual_only`; the system does not bypass the control. No crawler or LLM
writes a financial fact to the knowledge base. A named human approves every activation.

This is an extension of spec 05, not a competing ingestion architecture.

## 2. What is already implemented

### 2.1 Audit method

The audit covered `main`, every local branch, and every fetched remote branch. It inspected Git
history and all repository references to ingestion, Firecrawl, Crawl4AI, review queues, snapshots,
and proposals. It then read the actual implementations under `core/`, `gateway/evidence/`,
`gateway/reference/`, `gateway/catalog/`, the Gondola and Tripadvisor adapters, and the LLM
record/replay harness.

The following targeted regression run verifies the reusable foundation rather than relying on file
names or old reports:

```text
173 passed in 0.87s
```

The run covered evidence contracts/store/freshness/resolution/budgets, reference importers,
catalog determinism/quarantine, Gondola's persistent call budget, and LLM recording/replay.

### 2.2 Honest status

The financial ingestion pipeline is **not operationally implemented**. Every spec-05 stage is
absent from production code:

| Spec-05 component | Status in repo | Decision |
|---|---|---|
| Financial discovery-source registry | Not implemented | Build under `backend/ingestion/` |
| Financial `DiscoveryCandidate` contract | Not implemented | Build the spec-05 type; do not reuse the POI type |
| Financial watchlist | Not implemented | Build typed YAML loader and validator |
| Crawl4AI fetcher | Not implemented; dependency absent | Build behind a fetch-provider protocol |
| Firecrawl integration | Not implemented; dependency absent | Build optional adapter after the common protocol |
| Raw HTML/markdown/PDF snapshot store | Not implemented | Build content-addressed storage plus manifest |
| Normalized diff engine | Not implemented | Build locally and deterministically |
| Financial `ChangeProposal` extractor | Not implemented | Build with exact field evidence spans |
| Deterministic financial validator | Not implemented | Build from spec-01 model validation plus policy rules |
| Review queue and curator UI | Not implemented | Build separate SQLite store and local FastAPI UI |
| Approved-fact activation path | Not implemented | Build only after review/audit history is complete |
| Staleness sweeper and re-verification tasks | Not implemented | Build after activation path |
| Ingestion metrics | Not implemented | Build from queue/run events; no separate analytics service |

`backend/ingestion/__init__.py` is the only tracked file in the ingestion package on every audited
branch. There is therefore no hidden branch to merge and no abandoned implementation to revive.

The ignored `.firecrawl/` directory contains four prior competitive-research captures, including
AwardFares and Wanderlog material. These are useful research artifacts, but they are not an SDK
integration, source registry, scheduler, snapshot system, monitor, or ingestion path. Preserve them;
do not count them as implemented pipeline work.

### 2.3 Real foundations to reuse

| Existing implementation | What is reusable | What is not reusable as-is |
|---|---|---|
| `core.models.Provenance` and financial Pydantic models | Final approved row schemas and trust fields | Draft/proposal state; source evidence spans |
| `core.db.KnowledgeBase` and seed loader | Read current rows during extraction and validate final model shapes | It is read-oriented and reseeds by dropping/rebuilding tables; it is not an approval/write API |
| `gateway.evidence` | Runs, sources, artifacts, field identities, lineage edges, supersession, freshness, invariant checks, SQLite persistence | Price-specific contradiction thresholds and automatic resolution are not financial-rule review logic |
| `gateway.reference.SourceProvenance` | Source owner, URL, terms, licence, content hash, release, retrieval date, warnings | A web snapshot needs timestamp, HTTP/fetch metadata, raw and normalized hashes, and engine attempt history |
| FX and airport reference importers | Fetch/parse/build separation, byte bounds, deterministic sorting, typed failures, fixture tests | Their source schemas and one-shot fetch commands |
| `gateway.catalog` | Pinned manifests, checksum quarantine, sanitization, deterministic quality reports, atomic activation pattern | POI-specific identity, categories, merge rules, archive assumptions |
| Gondola/Tripadvisor adapters | Disabled-by-default live mode, injected clock/transports, typed errors, call ledger, bounded retry, circuit breaker, fixture envelopes, fail-soft fallback | Per-plan travel budgets, MCP tool policies, provider-specific normalization |
| `agents.RecordingLLMClient` / `ReplayLLMClient` | Offline extractor regression corpus and prompt-change invalidation | Existing four runtime LLM call sites; ingestion must remain an offline fifth workflow, not join the request pipeline |
| Existing account/auth code | Session, CSRF, optimistic-concurrency, and audit patterns | There is no curator role; ordinary product users must never receive approval authority |

### 2.4 Similar names that must not be mistaken for reuse

`backend/agents/discovery/contracts.py::DiscoveryCandidate` represents an LLM-mentioned **place**
in itinerary discovery. It contains `mentioned_name`, `resolved_place_id`, and a place-verification
state. Spec 05's financial `DiscoveryCandidate` contains issuer/product guesses, an aggregator lead,
an issuer URL to verify, corridor, and curator decision fields. They share a name but not a domain or
trust model. The financial type belongs in `ingestion.contracts`; importing the POI type would be a
bug.

Likewise, G2's FX/airport work is reference-data ingestion, explicitly not financial pipeline
integration. It contributes implementation patterns and contracts, not a partially complete
spec-05 pipeline.

## 3. Current data truth and the correct pilot

The four seeded cards have real product names but placeholder values:

- HDFC Infinia Metal
- Axis Atlas
- SBI Cashback
- ICICI Emeralde Private Metal

Their cards, reward rules, point valuations, and sample offers all remain `UNVERIFIED` with
`needs_verification=true`. The transfer programs and transfer graph are deliberately fictional
Kernel-MVP demonstration data (`LionMiles`, `SkyOrchid`, `GrandStay`, and `Voyager Prime`).

Therefore the first live ingestion pilot verifies the four real card products and their direct
card/reward rules. It does **not** activate transfer bonuses or award-chart facts against the
fictional graph. Real transfer programs become a separate, human-reviewed migration after the card
pilot proves the pipeline.

## 4. Binding boundaries

1. The pipeline runs offline by manual command or scheduler. `/plan`, `/plan/recompute`, and other
   request-time paths never crawl.
2. Financial values come only from first-party issuer, network, merchant-offer, or loyalty-program
   evidence. Aggregators and competitors produce leads, never facts.
3. Every proposed field has one or more exact evidence spans. Unsupported fields stay null or keep
   their current value; the extractor never fills a gap from memory.
4. LLMs extract typed candidates but never calculate money, points, ratios, discounts, caps, or
   derived value. Deterministic Python parses and validates those values.
5. No proposal is activated without a named human decision and a durable audit record.
6. Robots, source terms, rate limits, and login/access controls are obeyed. No CAPTCHA solving,
   residential/stealth proxy rotation, credential reuse, browser-fingerprint spoofing, or block
   circumvention is permitted.
7. Positive external spend fails closed. Firecrawl is optional and disabled unless a key, a no-
   overage account posture, and a local credit budget are all present.
8. Raw evidence is immutable. New evidence supersedes old evidence; it never rewrites history.

## 5. Source policy and launch registry

### 5.1 Fact sources for the India pilot

The initial source registry should contain only curator-approved URLs from these official domains
and page classes:

| Product/domain | Allowed evidence | Initial facts |
|---|---|---|
| HDFC Bank / official SmartBuy properties | Product page, fees/MITC/KFS PDF, official reward and campaign terms | Infinia fee, forex markup, base/portal earn, caps, exclusions, validity |
| Axis Bank / official EDGE Rewards and Travel EDGE properties | Atlas product page, fees/MITC, official reward/transfer terms | Atlas fee, markup, earn, caps, redemption/transfer conditions |
| SBI Card | Cashback product page, MITC/fees, official cashback/reward terms | Fee, markup, cashback/earn rules, caps, exclusions |
| ICICI Bank | Emeralde Private Metal product page, MITC/fees, official reward terms | Fee, markup, earn/redemption rules, caps, exclusions |
| Visa and Mastercard | Official network offer terms | Network-scoped offers only |
| Agoda, Klook, MakeMyTrip, and similar merchants | Official campaign terms linked from an issuer/network offer | Merchant eligibility, dates, code, min spend, cap, usage limits |
| Official airline/hotel loyalty programs | Program terms and transfer-partner pages | Deferred until the fictional transfer graph is replaced |

The registry stores exact URLs only after a curator records owner, terms URL, robots result, date
reviewed, automation permission, retention/attribution constraints, and any stated rate limit.
Domain membership alone never authorizes a new path.

### 5.2 Discovery-only sources

For the India corridor, CardExpert and Paisabazaar are the first discovery leads. PolicyBazaar UAE
and YallaCompare are deferred to the UAE corridor; NerdWallet and The Points Guy are deferred to the
US corridor. If a source's terms prohibit automation or remain ambiguous, it is `manual_only`.

A discovery lead may carry only the issuer URL a curator chooses to verify. Its numerical claims,
affiliate URL, rankings, valuations, and marketing language cannot flow into extraction input or a
KB proposal.

### 5.3 Competitive-product research, not data ingestion

PointsYeah, point.me, AwardFares, Seats.aero, Roame, AwardTool, MaxMyPoint, NerdWallet, The Points
Guy, and Wanderlog are product/UX references. Useful patterns include flexible-date grids, strong
filters, result confidence/freshness, alerts, saved searches, comparison explanations, itinerary
workspaces, and explicit verification links. Their proprietary availability, rankings, editorial
valuations, and logged-in content are not a source for the financial KB.

### 5.4 Permanently excluded targets

- Live booking inventory pages, checkout paths, or payment flows
- Logged-in bank, loyalty, cardholder, or award-search accounts
- Google Flights or other consumer booking UI as a data dependency
- Pages disallowed by recorded source terms or robots policy
- CAPTCHA-protected content and any target requiring access-control bypass
- Affiliate/referral links and sponsored ranking signals

## 6. One pipeline, three acquisition backends

```text
source policy + watch target
        |
        v
preflight (terms, robots, allowlist, due date, budget)
        |
        v
Crawl4AI default ----failure classification----> Firecrawl escalation
        |                                           |
        +-------------------+-----------------------+
                            v
                 canonical SnapshotBundle
                  raw + normalized + hashes
                            |
                deterministic normalized diff
                            |
                  typed field-level extraction
                            |
                validation + evidence-span check
                            |
               SQLite review queue + local UI
                            |
             human approve/edit/reject/reverify
                            |
            deterministic activation bundle/apply
                            |
                       approved KB row
```

`ManualUploadBackend` is the third backend. A curator can upload HTML, PDF, or text from a source
that cannot be fetched automatically. It enters the same snapshot/diff/extract/review path and is
clearly labeled `manual_capture`; it does not receive `official_page`/`tnc_pdf` provenance until
the curator confirms the primary-source URL and approves the proposal.

### 6.1 Common fetch protocol

```python
class FetchBackend(Protocol):
    async def fetch(self, request: FetchRequest) -> FetchResult: ...
```

`FetchRequest` includes the canonical URL, source-policy id, requested evidence kind, byte/page/time
limits, expected selectors, locale, forced-freshness flag, and an injected run id. `FetchResult`
includes raw bytes or HTML, rendered HTML when applicable, cleaned markdown, outbound links,
screenshots only when requested, HTTP/final URL metadata, engine/version, timings, and a typed
failure. It never contains a proposed financial row.

Fallback happens in the orchestrator, not inside a crawler's opaque fallback callback. Every
attempt, failure, cost reservation, and selected result remains visible in the run ledger.

## 7. Crawl4AI: default path

Pin Crawl4AI v0.9.4, the current security release verified on 2026-10-07. Prefer the in-process
Python library rather than exposing its Docker API; this project does not need a multi-tenant crawl
server, and the library path keeps the attack surface and operations smaller.

Install crawler tooling as optional backend extras rather than enlarging the Kernel runtime:
`ingestion-local` owns Crawl4AI and `pdfplumber`; `ingestion-firecrawl` owns the official Python
`firecrawl-py` SDK. Register `ingestion` as a package only when FI0 begins. Normal backend install,
tests, and `/plan` must not import either crawler SDK.

Use:

- browser-rendered HTML plus raw HTML and clean/fit markdown;
- robots checking before dispatch and Crawl4AI's own robots enforcement as defense in depth;
- cache modes chosen explicitly: replay/cache in tests, forced fresh for scheduled verification;
- selector waits, load-state waits, bounded full-page scan, and public click actions for cookie
  consent or collapsed T&C sections;
- locale/timezone controls only to request the intended public regional page;
- session reuse only within one public-domain run, never to persist authentication;
- pruning with issuer-specific preservation rules for tables, footnotes, exclusions, dates, and
  short disclosure elements;
- byte, page, redirect, wall-clock, and per-domain concurrency limits;
- one request at a time per domain and at least the spec-05 ten-second delay.

Do not enable proxy rotation, stealth proxy modes, authenticated profiles, arbitrary request-supplied
JavaScript, or browser fingerprint spoofing. Crawl4AI's `fallback_fetch_function` stays unused; the
pipeline orchestrator owns escalation and auditability.

## 8. Firecrawl: full capability, selectively applied

Firecrawl's latest stable open-source release verified for this plan is v2.11.0. A v2.12 release
document exists only as a draft pull request and is not treated as released behavior. The
integration must use v2 APIs; `/extract` and `/deep-research` were deprecated in v2.10.

| Firecrawl capability | Use in this pipeline | Guardrail |
|---|---|---|
| `map` | Curator-assisted discovery of product, fees, MITC, and terms URLs on an already approved official domain | Bootstrap only; mapped URLs are candidates, not automatically authorized |
| `search` with domain filters | Find an official page when the exact URL is unknown; competitor research | Official-domain result still requires source-policy approval; never turns snippets into facts |
| `scrape` | Fallback/cross-check for JS-heavy public pages; return markdown, HTML, links, and selective screenshot | Force fresh when verifying; stop on login/CAPTCHA/denial |
| `deterministicJson` | Second extraction surface for a small set of stable, high-value pages | Cross-check only; no direct proposal or KB write; schema and prompt version recorded |
| `highlights` | Retrieve exact relevant sentences/table rows to accelerate evidence-span location | Quotes are verified against the stored snapshot before review |
| `monitor` | Weekly monitoring of a very small set of high-change/high-value official pages | Goal-based alerts plus mixed field JSON and git-style text diffs; webhook is a trigger, not trusted evidence |
| `parse` | Escalation for PDFs whose tables/reading order defeat local `pdfplumber` extraction | Store original PDF hash and compare parsed text to page images/manual review |
| `interact` | Public clicks, pagination, accordions, or click-to-reveal terms after ordinary scrape fails | No login, form submission carrying personal data, CAPTCHA, or access-control bypass; strict step/time cap |
| `crawl` / batch scrape | Narrow, path-allowlisted issuer/loyalty documentation sections | Hard page cap; never crawl an entire bank or competitor domain |
| Webhooks | Notify the local job of monitor completion | Authenticated callback secret/signature when the deployed endpoint supports it; otherwise poll; always use idempotency, replay protection, and bounded payloads |
| PII redaction | Optional defense for a non-evidentiary derivative if an unexpected public page contains personal data | Off for the canonical evidence fetch because redaction would break exact-quote fidelity; no user/account data is ever intentionally sent |
| Lockdown/index-only mode | Optional competitor/discovery research where freshness is not evidence-critical | Never used to claim a current financial fact |

Firecrawl Agent and question-answer formats are off by default. They duplicate the pipeline's typed
extractor while adding cost and a less transparent reasoning surface. A later experiment may use
Agent to propose discovery URLs, but its output remains a discovery candidate and cannot provide
financial evidence.

### 8.1 Firecrawl cost posture

The pricing page effective 2026-09-04 states: free accounts receive 1,000 monthly credits without a
credit card; basic scrape/crawl/map costs one credit per page; search costs two per ten results;
Interact costs two per browser minute; JSON/Question/Highlights add four per page; deterministic
monitor extraction costs seven per page per check. These rates are external configuration, not
hardcoded assumptions.

The adapter is disabled unless all are true:

1. `FIRECRAWL_API_KEY` is available from an ignored environment file or secret store;
2. the account has no billable overage path or payment method;
3. the local persistent credit ledger can reserve the estimated credits before dispatch;
4. the run, monthly, endpoint, page, and browser-minute ceilings remain below configured limits.

Initial ceilings: 50 credits per manual run, 800 recorded credits per calendar month, at most eight
weekly monitored pages, and at least 200 credits reserved for diagnostics. The ledger reserves
before dispatch and conservatively settles ambiguous/timeout outcomes as spent. A pricing-version
check or manually reviewed rate table must be updated before enabling a newly priced feature.

This plan does not require a paid Firecrawl account. Paid credentials, attached billing, or a
self-hosted Firecrawl deployment require separate human approval.

## 9. Snapshot and lineage model

### 9.1 New ingestion contracts

- `SourcePolicyRecord`: source owner/domain, terms and robots evidence, allowed page classes,
  automation/manual status, delay/rate limits, retention/attribution rules, review date and reviewer.
- `DiscoveryCandidate`: the exact spec-05 financial lead contract, with no `Provenance` field.
- `WatchTarget`: canonical URL, source-policy id, target fact ids, page kind, frequency, hints,
  preferred backend, and `manual_only` state.
- `FetchAttempt`: backend/version, start/end, final URL, response/block classification, retry index,
  credit reservation/settlement, and bounded diagnostic.
- `SnapshotBundle`: immutable raw artifact references, raw/normalized hashes, canonical markdown,
  extraction engine metadata, and ordered fetch attempts.
- `EvidenceSpan`: snapshot id/hash, exact quote, normalized character offsets and, for PDFs, page
  number; field path; verification result.
- `FieldProposal`: field path, old value, proposed raw value, deterministically parsed value, and
  evidence spans.
- `ChangeProposal`: target table/id, current row hash, proposed typed row, field proposals, change
  summary, extractor/prompt versions, validation findings, and lineage ids.
- `ReviewDecision`: reviewer, status, edits, reason, proposal version, timestamp, and optimistic
  concurrency version.
- `ReverifyTask`: target row, due reason, priority, and prior evidence/proposal linkage.

### 9.2 Reuse of the evidence graph

Reuse `gateway.evidence.Run`, `Source`, `Artifact`, `Evaluation`, lineage edges, freshness transitions,
and `SqliteEvidenceStore`. Represent extracted draft fields as `REFERENCE_FACT` claims using
`ReferenceFactIdentity(namespace="financial_draft", entity_id, field)`, always with
`status=VERIFY_REQUIRED` and `needs_verification=true`. A row-level `ChangeProposal` is an artifact
derived from those field claims and its snapshot artifacts.

Do not use the existing price contradiction detector for reward rules. Financial contradictions
are schema-aware comparisons surfaced as validator findings for a human. Do not use automatic
evidence resolution to select a financial truth.

### 9.3 Storage

- Content-addressed raw artifacts on disk, outside Git; sha256 names and immutable writes.
- Preserve spec 05's logical `snapshots/{url_hash}/{date}/` organization with a small manifest at
  that location pointing to content-addressed blobs; this keeps human recovery simple without
  duplicating identical bodies.
- `ingestion.sqlite` for source policy, watch targets, attempts, manifests, queue, decisions,
  schedules, budgets, and metrics.
- Existing evidence-store tables for cross-run lineage.
- Recorded, sanitized fixture subsets in Git for deterministic tests; no full copyrighted page
  dumps, secrets, cookies, or personal data.
- Retention policies enforced by artifact class; audit decisions and hashes outlive removable raw
  bodies.

## 10. Diff, extraction, and validation

1. Canonicalize URLs and reject redirects outside the approved domain set, private/link-local IPs,
   non-HTTP schemes, oversized responses, and unexpected content types.
2. Preserve the raw artifact first. Normalize a separate derivative: Unicode, whitespace, stable
   table structure, tracking parameters, repeated chrome, and explicitly configured volatile
   regions.
3. Diff normalized markdown and structured snapshots. No material change updates `last_checked`
   without calling the extractor.
4. On change, run one temperature-zero typed extraction against the current KB row, the current
   snapshot, and the diff. Store through `RecordingLLMClient`; tests use `ReplayLLMClient` only.
5. Verify each evidence quote is an exact substring of the immutable snapshot and that its field
   path is unique enough for review. A missing/mismatched quote invalidates that field.
6. Deterministically parse decimals, percentages, money, points, dates, ratios, caps, and exclusions
   into spec-01 integer representations. Never ask the LLM to convert them.
7. Run Pydantic schema validation and policy checks. Findings annotate; structural impossibilities
   block approval. Cross-source disagreement is retained and shown side by side.
8. Review UI shows current row, proposed row, field diff, exact quote in context, source URL/hash,
   raw/rendered view, validator findings, prior decisions, and approve/edit/reject/reverify actions.
9. Approval creates a versioned activation bundle. A deterministic apply step checks the current
   row hash again, refuses stale approvals, writes atomically, and records the resulting row hash and
   provenance. It never silently overwrites a concurrently changed row.

The first implementation should export a reviewable activation bundle before it mutates seed/KB
state. Direct application is enabled only after round-trip, rollback, and golden-drift tests prove
the write boundary. This accounts for the current `seed_database()` behavior, which drops and
rebuilds tables and is not an approval-safe mutation API.

## 11. Failure handling

Every watch target finishes in one explicit state: `unchanged`, `proposal_pending`, `manual_only`,
`policy_blocked`, `robots_blocked`, `authentication_required`, `captcha_detected`, `rate_limited`,
`timeout`, `invalid_response`, `budget_exhausted`, or `unexpected_failure`.

- Retry only timeouts, connection resets, and eligible 5xx responses, at most once per backend with
  deterministic jitter derived from run id.
- Never retry 401, 403, 404, 409, 422, or 429 as if more traffic will help.
- Open a per-domain/backend circuit after three consecutive transient failures; require cooldown or
  manual reset.
- A source failure never aborts unrelated domains. The run report contains successes, partials,
  unresolved targets, and the exact stop reason.
- If both automated backends fail, preserve diagnostics and create a manual capture task.
- If extraction fails but the snapshot is valid, retain the snapshot and allow extractor replay
  without refetching.
- If activation fails, the approved proposal remains pending-apply; no partial KB write is allowed.

## 12. Security tests from day one

- SSRF: private, loopback, link-local, metadata, DNS rebinding, redirect-chain, IPv6 transition
  forms, and malicious proxy/final URLs.
- Archive/PDF: path traversal, decompression bombs, page/byte bounds, malformed cross-references,
  embedded files/scripts, and parser timeouts.
- Web content: prompt injection, Unicode/whitespace evasion, hidden text, hostile HTML, unexpected
  forms, and misleading button labels.
- Webhooks: bad callback authentication, replay, duplicate delivery, oversized body, and
  out-of-order events.
- Source trust: aggregator number cannot populate any proposal field; only the approved issuer URL
  can cross discovery into the watchlist.
- Human gate: no repository function can construct/activate a KB row without a durable approved
  `ReviewDecision`; stale proposal versions fail closed.
- Secrets: API keys, cookies, authorization headers, raw provider errors, and credentials never
  enter fixtures, logs, snapshots, reports, or Git.
- Network isolation: all normal tests run against recorded fixtures with socket access blocked.

## 13. Implementation sequence and gates

### FI0 — Contracts, policy, and audit storage

Build typed source policy, watchlist, financial discovery, fetch/snapshot/proposal/review contracts,
SQLite migrations, and boundary tests. Reuse the evidence graph; do not write a second lineage
system.

**Gate:** every contract round-trips; financial `DiscoveryCandidate` structurally lacks
`provenance`; no aggregator value can reach a field proposal; migrations and concurrent queue
updates are deterministic.

### FI1 — Snapshot core and Crawl4AI

Build content-addressed storage, preflight policy/robots checks, the common fetch protocol,
Crawl4AI adapter, manual upload, canonicalization, and diffing.

**Gate:** fixture repeatability is byte-identical; raw evidence is immutable; unchanged pages cause
zero extractor calls; blocked/login/CAPTCHA fixtures become manual tasks; no proxy or access-control
bypass exists in configuration.

### FI2 — Extraction, validation, and replay

Build field evidence spans, typed proposals, deterministic numeric/date parsers, validators, and an
offline recording/replay corpus covering tables, PDFs, exclusions, caps, and conflicting sources.

**Gate:** every changed field has a verified exact quote; no LLM performs arithmetic; malformed or
unsupported values cannot become a valid proposed row; replay tests make zero network calls.

### FI3 — Review and activation dry-run

Build local-only FastAPI review UI, curator identity/CSRF/concurrency protections, decision audit,
activation bundles, and dry-run diffs against current seed/KB rows.

**Gate:** approve/edit/reject is auditable and idempotent; stale approvals fail; activation dry-run
cannot change goldens; there is still no automatic KB mutation.

### FI4 — Firecrawl adapter and monitors

Add hosted Firecrawl behind the same protocol: map/search bootstrap helpers, scrape fallback,
deterministic JSON/highlight cross-checks, PDF parse escalation, bounded public interaction, narrow
crawl/batch, monitors/webhooks, and the persistent credit ledger.

**Gate:** disabled behavior is byte-identical to FI3; one explicitly approved public-page live smoke
succeeds through the real adapter; no secret is written; every request reserves credits first;
budget exhaustion and webhook duplicates fail soft; deprecated endpoints are absent.

### FI5 — Four-card India pilot

Curators approve exact official URLs and run the four card products through snapshot → proposal →
review. Begin with card fees/markup/base earn, then reward rules/caps/exclusions, then official offers.
Keep transfer/award activation out of this milestone.

**Gate:** each approved field has primary-source evidence, named reviewer, current date, immutable
snapshot hash, and no unresolved structural finding. Compare pipeline output against a second human
reading. `make gate` passes, golden values change only in a separately reviewed fact-data commit,
and a rollback restores the prior approved fact pack.

### FI6 — Staleness and operations

Add due scheduling, re-verification tasks, selective weekly Firecrawl monitors, dashboards from local
metrics, recovery commands, and documented operator runbooks.

The default re-verification thresholds remain exactly those in spec 05: offers at 90 days and rules
at 365 days. Changing them is a separate Tier-C decision backed by observed review/failure data.

**Gate:** simulated time advances create the expected offer/rule tasks; missed schedules recover
without duplicate proposals; monthly Firecrawl ceilings are respected; source/domain failure does
not hide healthy results.

## 14. Metrics

Track proposals per week, approval/rejection/edit rates, field-level edit rate, median review time,
fetch success by backend/source, manual-only rate, false-change rate, extractor quote failure rate,
validator finding rate, age distribution of approved facts, monitor meaningful-change precision,
and Firecrawl credits per approved change.

The key quality metric is approved-with-edits at the field level. If it exceeds roughly 30%, stop
adding sources and improve normalization, prompts, schemas, or evidence presentation.

## 15. Explicitly not duplicated or built

- No second evidence graph, fixture transport, provenance model, sanitizer framework, LLM replay
  harness, or generic budget concept.
- No modifications to `docs/specs/` for this plan.
- No provider-specific financial arithmetic.
- No runtime crawler in the product request path.
- No autonomous source discovery/activation.
- No self-hosted Firecrawl stack in the first implementation.
- No paid scraping/proxy service or bypass tooling.
- No activation of real transfer data into the current fictional transfer graph.

## 16. Verified external references

- Firecrawl stable releases: <https://github.com/firecrawl/firecrawl/releases>
- Firecrawl v2 OpenAPI: <https://github.com/firecrawl/firecrawl-docs/blob/main/api-reference/v2-openapi.json>
- Firecrawl pricing, effective 2026-09-04: <https://www.firecrawl.dev/pricing>
- Firecrawl Python source of truth: <https://docs.firecrawl.dev/agent-source-of-truth/python>
- Crawl4AI releases: <https://github.com/unclecode/crawl4ai/releases>
- Crawl4AI v0.9.4 changelog/security notes: <https://github.com/unclecode/crawl4ai/blob/main/CHANGELOG.md>
- Crawl4AI browser/crawler parameters: <https://docs.crawl4ai.com/api/parameters/>

Version, pricing, and endpoint assumptions are rechecked before FI1/FI4 implementation. Documentation
is evidence for planning, not permission to activate a source or spend money.
