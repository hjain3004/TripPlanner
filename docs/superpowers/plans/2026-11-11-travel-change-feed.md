# Travel Change Feed: discovery, verification and personal impact

**Status:** proposed. Nothing in this plan is implemented.
**Date:** 2026-11-11
**Reviewed against:** `origin/main` `a9efea0` and the unmerged `codex/firecrawl-ingestion` `b7a0057`.
**Extends:** `docs/superpowers/plans/2026-10-07-robust-financial-ingestion.md`. That plan covers
watching known issuer pages. This one adds finding out what changed in travel rewards, and
telling each traveler what it means for their wallet and trips.

## Corrections (2026-11-12, Opus, design role)

These correct the plan's orchestration and source assumptions. They approve nothing.

- **Phase 0 item 1:** merge, not rebase, because `codex/firecrawl-ingestion` is published.
- **Section 5:** request-time `backend/feed/` and `api/feed.py` also never import `backend/ingestion/`.
- **Section 7:** the four model roles (Triage, Extractor, Corroborator, Writer) are **proposed runtime model roles, not approved** until the owner confirms them (runtime design P6). If approved, they use the same budgeted client, ledger, caps and process-wide model limiter as stream A.
- **Section 8:**
  - The Points Guy's terms have now been read (Kiro, PR #41). The recommendation is no automation, manual lead only.
  - KrisFlyer and Air India could not be retrieved and are do-not-use until the owner reads their terms. See `reports/change_feed_source_permissions.md`.
- **Phase 0 item 6 and Phase 4 item 1:**
  - Programme and transfer rows have no review/apply path yet (rollout spec P-2/P-3).
  - Applying goes to the owner's private seeds directory, not to repository seeds, until the owner decides on display permission (rollout spec §1).
- **Private captures** and snapshots stay in private storage. They are never committed automatically.

## 1. Decision in one paragraph

Build a daily feed of travel-rewards changes (transfer bonuses, welcome offers, earn and cap
changes, devaluations, award sales) sourced from the primary pages of issuers and loyalty
programmes. Blogs and newsletters are leads only: a title and a link, confirmed at the primary
source before anything is published as fact. Every event carries a verbatim quote and a source
link. Events run in two lanes. The news lane publishes quickly with a verification label. The
facts lane routes anything the optimizer would do money arithmetic on through the existing human
review queue. The part no newsletter can copy is the last step: each event is matched against a
traveler's wallet and saved trips, the optimizer is re-run, and the traveler sees the computed
difference.

## 2. Assumptions to confirm

| Assumption | Why it matters |
|---|---|
| This is still a non-commercial portfolio project | The bank terms already reviewed are "personal, non-commercial". A public or commercial launch means redoing the Phase 0 permission review. |
| USD 50 of Claude API credit and USD 150 of AWS credit, both for the deployed site only | Sets production model routing and hosting in section 9. Development and testing make no paid call: they use scripted or recorded clients, or the existing free-tier provider. |
| The old `CLAUDE.md` is retired | This plan keeps two of its rules on engineering merit: an LLM never computes a money value, and nothing unreviewed enters the knowledge base the optimizer reads. Overrule either explicitly if you disagree. |
| You are the only reviewer | The facts lane must stay small enough for one person. The news lane must not wait on you. |

## 3. What the traveler and operator get at the end

- **Feed (anyone):** "What changed this week" for the corridor. Each item has a type, the
  programmes involved, the dates, a source link, when it was first seen, and a label:
  `lead only`, `confirmed at source`, or `reviewed`.
- **For you (signed in):** the same events filtered and ranked by the cards and points in the
  wallet and by saved trips. Each one shows the computed effect, for example "transferring
  instead of paying cash changes your Singapore plan by this much", with the before and after
  payment strategy.
- **Trip banner:** "1 change affects this trip" on a saved trip, linking to the comparison.
- **Operator:** a nightly run that needs no attention, a review queue for facts, and a
  `retract` command for a wrong event.

## 4. Current state, verified in code

| Piece | Where | State |
|---|---|---|
| Source policy record (terms read, robots, delay, attribution) | `ingestion/contracts.py` `SourcePolicyRecord` | Built. Reuse unchanged. |
| Preflight (robots, public host, redirect checks) | `ingestion/preflight.py` | Built. Reuse. |
| Fetch backends: manual upload, Crawl4AI | `ingestion/fetch.py` | Built. Crawl4AI has never fetched a live page. |
| Firecrawl backend, durable acquisition control, `acquire`, `refresh-due` | `codex/firecrawl-ingestion` only | Built on an unmerged branch. One live scrape (Axis Atlas). |
| Snapshot store and diff | `ingestion/snapshots.py`, `ingestion/diff.py` | Built. Diff returns a changed flag and one unified diff, not separate hunks. |
| Field extractor with quotes and offsets | `ingestion/extraction.py` `FinancialExtractor` | Built. The live-model mode has not run on a real page; the branch demo used `SCRIPTED_REPLAY` and `CURATOR_AUTHORED`. |
| Review queue, decisions, bundle, dry-run, apply, rollback | `ingestion/review_server.py`, `activation.py`, `applier.py` | Built. Apply has only run against scratch seeds. |
| Lead type and CLI | `DiscoveryCandidate`, `add-lead`, `promote-lead` | Built as storage and manual entry. Nothing produces leads automatically. Kinds are limited to card, offer, welcome bonus. |
| Change event (a dated, typed thing that happened) | none | Missing. |
| Loyalty programmes and transfer partners | `core/seeds/loyalty_programs.yaml`, `transfer_edges.yaml` | Three invented programmes and four edges, all unverified. Real rows are a prerequisite. |
| Matching events to wallets and trips | none | Missing. `AccountStore.wallet_entries`, `trips`, `latest_revision` give the inputs. |
| Feed API and UI | none | Missing. |
| Scheduler | none | Missing. `refresh-due` is the command a timer would call. |
| Claude client | none | Missing. `agents/llm.py` speaks OpenAI-style chat completions only. |

## 5. Architecture

```text
 SOURCES                                    LANES                         TRAVELER
 ───────                                    ─────                         ────────
 Tier 1 primary pages ─┐
 (issuers, programmes) │   Scout        Triage       Extract        ┌─ news lane ──► Feed
                       ├─► fetch+diff ─► relevant? ─► typed event ──┤   publish with label
 Tier 2 official news ─┤   (no LLM)     (Haiku)      + quotes       │
 feeds                 │                             + validators   └─ facts lane ─► ChangeProposal
                       │                                  ▲              ► human review ► KB
 Tier 3 leads ─────────┘                                  │
 (title + link only) ──► Corroborate: find and quote ─────┘
                         the primary source (agent,
                         bounded, allowlist only)

 Published event ─► Match (wallet, trips; no LLM) ─► Impact (optimizer re-run on a what-if
                    overlay; no LLM) ─► Writer (Haiku; numbers copied, never computed) ─► For you
```

Where it runs: one process on one instance, started by a timer. Offline code stays in
`backend/ingestion/`. Request-time code goes in a new `backend/feed/` package and `api/feed.py`,
which read the events store and never fetch. [corrected] They import nothing from `backend/ingestion/`.

## 6. Data model

New file `ingestion/events.py`. All amounts are integer minor units or basis points, as in the kernel.

**`ChangeEvent`**

| Field | Notes |
|---|---|
| `event_id` | Stable hash of type, subjects and effective window, so a re-detection is the same event. |
| `event_type` | `transfer_bonus`, `welcome_offer`, `earn_rate_change`, `cap_change`, `fee_change`, `devaluation`, `award_sale`, `partner_added`, `partner_removed`, `lounge_change`, `programme_policy`. Phase 1 ships the first three. |
| `subjects` | Issuer, card and programme ids. Each must resolve to a knowledge-base id or be marked `unmapped`. Unmapped events can be published but cannot be matched. |
| `terms` | A typed block per event type. For `transfer_bonus`: from and to programme, `bonus_bp`, minimum transfer, cap. |
| `effective_from`, `effective_to` | Dates. `effective_to` drives expiry. |
| `evidence[]` | `source_policy_id`, URL, snapshot SHA-256, verbatim quote, character offsets. At least one item. |
| `verification` | `lead_only`, `primary_confirmed`, `human_approved`. |
| `status` | `draft`, `published`, `retracted`, `expired`. |
| `cluster_id`, `supersedes` | Deduplication and corrections. |
| `first_seen_at`, `last_confirmed_at` | For freshness and for measuring detection time. |
| `linked_proposal_ids` | The `ChangeProposal` rows this event produced in the facts lane. |

**`EventImpact`**: `event_id`, `user_id`, `trip_id`, `revision`, hashes of the before and after
optimizer results, `delta_effective_cost_minor`, changed line ids, `overlay_hash`, `basis`
(`if_confirmed` or `reviewed`), `computed_at`.

**`LLMSpendLedger`**: one row per model call with model, tokens in and out, cached tokens, computed
cost, role and run id. Follow the SQLite ledger pattern in `gateway/weather/budget.py`.

**Changes to existing types**

- `PageKind`: add `PROMO_INDEX`, `PARTNER_TABLE`, `PROGRAMME_NEWS`, `FEED`.
- `DiscoveryCandidate.kind`: add the new event types.
- `diff.py`: return a list of changed blocks with a few lines of context each. Triage reads blocks, not pages. This is the largest single saving in tokens.

## 7. The five roles

| Role | LLM? | Model | Does | Bound |
|---|---|---|---|---|
| Scout | No | none | Runs `refresh-due`, polls permitted feeds, emits changed blocks and leads. | Per-domain delay and robots from the source policy. |
| Triage | Yes | Haiku 5.5, Batch API | Per changed block: is this a rewards change, and which type? | One call per block. Unchanged pages cost nothing (already true). |
| Extractor | Yes | Haiku 5.5, escalate to Sonnet 5.5 | Fills the typed `terms` block. Every field needs a verbatim quote. | One call, one escalation. Deterministic checks afterwards: the quote exists at the stated offsets, dates are sane, ids resolve. A failed check drops the field, never guesses it. |
| Corroborator | Yes | Sonnet 5.5 | Given a lead or a single-source event, finds the primary page, fetches it through the existing preflight-gated fetcher, and returns confirmed, contradicted or not found, with a quote. | At most 3 searches and 3 fetches per lead. Search and fetch are restricted to registered primary domains. Not-found leads stay `lead_only` and expire after 7 days. |
| Writer | Yes | Haiku 5.5 | One or two sentences per `EventImpact`. | Numbers are copied from the computed impact. Reuse the groundedness gate and template fallback from `agents/explainer.py`. |

Matching and impact are plain Python with no model call.

- **Match:** an event applies to a user when its card or programme ids intersect the wallet, and
  to a trip when the event window overlaps the booking or travel window.
- **Impact:** build an in-memory knowledge base with the proposed row applied, the way the FI3
  dry-run already does, run `optimize()` on the trip's latest revision, and store the difference.
  Before human approval the result is labelled `if_confirmed`. After approval it is recomputed
  against the real knowledge base and labelled `reviewed`.

**Untrusted input.** Fetched text is data. Roles that read it have no write tools, every output is
schema-validated, and `fixtures/fi2_prompt_injection.txt` becomes a standing test for each role.

**Agent loop.** Reuse the `LoopBudget` and `LoopState` pattern in `agents/discovery/contracts.py`.
Do not add an agent framework.

## 8. Sources

Every source needs a `SourcePolicyRecord` before its first fetch. The names below are candidates
to review, not sources I have checked.

| Tier | What | May supply facts? | Candidates |
|---|---|---|---|
| 1. Primary | Issuer card, offer and partner pages; loyalty programme promotion and partner pages | Yes | The four issuers in `reports/card_bank_source_permissions.md` (HDFC, Axis, SBI Card, ICICI: note ICICI PDFs are manual only). Real programmes on the India to Singapore corridor, starting with Singapore Airlines KrisFlyer and Air India's programme. The seeded programmes (`lionmiles`, `skyorchid`, `grandstay`) are invented placeholders, so this list has to be chosen. |
| 2. Official announcements | Airline and programme newsrooms, publisher-offered feeds | Yes, with a quote | To be found in Phase 0. |
| 3. Leads | Blogs, newsletters, forums | No. Title, link and a one-line summary in your own words. Never page text. | Manual entry through `add-lead` from your own reading. Automated polling only where the publisher offers a feed and its terms allow it. |

Decided exclusions:

- **Daily Drop:** manual leads only. Its terms prohibit crawling, scraping and competing use.
- **The Points Guy:** [corrected] terms read (PR #41): no automation; manual lead only, pending the owner.
- **point.me:** not a news source.

Targets: about 25 watch targets by the end of Phase 1, about 60 by the end of Phase 4.

## 9. Infrastructure and cost

One small ARM instance runs the API, the nightly job and the review server. SQLite stays. Snapshots
live on disk with a nightly copy to object storage, alongside a nightly SQLite backup. Timers are
systemd units calling the CLI. TLS comes from a reverse proxy on the same instance.

Do not add a load balancer, a NAT gateway or a managed database. Any one of them would use the
AWS credit several times faster.

**AWS (my estimate from memory, not looked up; confirm in the AWS pricing calculator)**

| Item | Approx. per month |
|---|---|
| One 2 GB ARM instance | USD 12 |
| 30 GB disk | USD 2 to 3 |
| Public IPv4 address | USD 4 |
| Object storage for snapshots and backups | under USD 1 |
| **Total** | **about USD 19, so roughly 8 months of the USD 150** |

**Claude API, production only (prices from the pricing page on 2026-11-11; volumes are my assumptions)**

Haiku 5.5 is USD 0.10 in and 0.50 out per million tokens. Sonnet 5.5 is USD 2 and 10. Batch is half
price. Web search is USD 10 per 1,000 searches.

| Role | Assumed daily volume | Approx. per day |
|---|---|---|
| Triage | 200 blocks, 1.5k tokens in, 100 out | USD 0.04 |
| Extraction | 20 events, 4k in, 600 out | USD 0.02 |
| Corroboration | 10 leads, 15k in, 1k out, 2 searches each | USD 0.60 |
| Writer | 50 impacts, 1k in, 200 out | USD 0.01 |
| **Total** | | **about USD 0.70, or USD 20 a month** |

Corroboration is nearly all of the cost. Running it on Haiku instead brings the total to about
USD 8 a month. Start on Haiku and move to Sonnet only if measured accuracy requires it.

Controls, all enforced from the ledger before a call is dispatched: a daily cap (default USD 1), a
lifetime cap (default USD 45, leaving a margin on the USD 50), and a per-run cap. A reached cap
stops model calls; fetching and diffing continue and work queues for the next day. Also set a
spend limit in the Claude console.

## 10. Phases

Effort is my estimate in working days for one person using coding agents.

### Phase 0: land and prove what exists (4 to 5 days)

*Result: the existing pipeline has run end to end once with a real model on a real page.*

1. [corrected] Merge current `main` into `codex/firecrawl-ingestion` (no rebase), then merge it into `main`.
2. Add a Claude client behind the existing `LLMClient` protocol, selected by an environment
   variable, with `LLMSpendLedger` and the caps. It is tested against documented response shapes
   and makes no real call until the owner's deployment-day check.
3. Fix `agents/llm.py:236`, where the tools branch discards the schema instruction.
4. Run `FinancialExtractor` with a real model on the retained Axis Atlas capture, using the
   free-tier provider. This is the step that has never been exercised.
5. Extend `reports/card_bank_source_permissions.md` to the Tier 1 and Tier 2 candidates.
6. Add real loyalty-programme and transfer-partner rows for the corridor through the existing
   insert-proposal and review path. The seeds hold three invented programmes, and an event whose
   subjects do not resolve to a knowledge-base id cannot be matched to anyone.

**Done when:** the proposal appears in `review-queue` with quotes that match the snapshot at the
stated offsets, the permission table has a verdict per candidate, and
the corridor's real programmes exist as reviewed rows.

### Phase 1: events from primary pages (7 to 8 days)

*Result: a public feed that updates itself every night for one corridor.*

1. `ingestion/events.py`, the migrations and storage, and the `PageKind` and diff changes.
2. A watchlist of about 25 targets in the existing YAML format.
3. Triage and Extractor for `transfer_bonus`, `welcome_offer` and `earn_rate_change`, with one
   validator per type.
4. Deterministic deduplication by event id.
5. CLI: `python -m ingestion.feed run | list | show | retract`.
6. `GET /feed` (public, paginated, published events only) and a minimal `/feed` page using the
   existing trust chips.
7. A timer on your machine first; the instance comes in Phase 2.

**Done when:** a replay of two real snapshots of one page taken days apart emits the correct
event; an unchanged page makes no model call; and a 7-night unattended run has completed, with
every event hand-graded.

**Decision point:** if those 7 nights produce very few real events across 25 targets, add sources
before building further. An empty feed is the main risk of this plan.

### Phase 2: "For you" (7 to 8 days)

*Result: a signed-in traveler sees which changes affect their wallet and trips, with the computed difference.*

1. `backend/feed/match.py` and `backend/feed/impact.py`.
2. The Writer, with the groundedness gate.
3. `GET /feed/for-me` and the trip banner.
4. Deploy to the instance.

**Depends on:** a sign-in screen and saved-trip UI. Neither exists on `main`. Without them this
phase has no reachable user.

**Done when:** golden tests pass for a synthetic transfer bonus against the demo wallet (expected
delta in minor units) and for an event that touches nothing in the wallet (no impact row); and you
have seen one real event change one of your own saved trips.

### Phase 3: leads and the Corroborator (9 to 10 days)

*Result: a link you paste, or a headline from a permitted feed, is confirmed or rejected at the primary source without you doing the reading.*

1. A feed poller for permitted Tier 2 and Tier 3 feeds, and a "paste a link" form in the review server.
2. The Corroborator loop with its allowlist and budget.
3. Clustering: the deterministic key first, a model call only to break a tie.
4. Verification labels in the feed.

**Done when:** on 20 historical leads you have labelled by hand, the report shows how many were
correctly confirmed, contradicted or not found, and the transport log shows no fetch outside the allowlist.

### Phase 4: close the facts lane and widen (9 to 10 days)

*Result: an approved event changes what the optimizer recommends for everyone.*

1. Link events to `ChangeProposal` rows. On approval, [corrected] the owner applies to the private seeds
   directory (rollout spec; `apply` refuses repository seeds), mark the event `human_approved`, and recompute impacts as `reviewed`.
2. An expiry sweep for events and for rule `valid_to` dates.
3. The remaining event types.
4. About 60 targets and a second corridor.
5. Optional weekly digest by email.

**Done when:** approving one real event changes a stored trip's recommendation, and rolling it back restores the previous one.

### Phase 5: the agentic stretch (open-ended)

- **Source scout:** proposes new watch targets from outbound links in snapshots. A person still approves each source policy.
- **Trip watcher:** a weekly run per saved trip asking whether anything new changes the plan.
- **Ask the feed:** questions answered from the events table with event ids cited. SQLite full-text search is enough; no vector database.
- **Tool interface:** expose events and impact as an MCP tool so a general agent can call them. This is the distribution idea from the moat discussion.

## 11. Evaluation

| Measure | How |
|---|---|
| Extraction precision | Weekly hand-graded sample of published events. |
| Unsupported fields | Should be zero by construction (the quote check). Count any that slip through. |
| Corroboration accuracy | The labelled lead set from Phase 3, re-run on every prompt change. |
| Detection time | `first_seen_at` against the date you first saw it elsewhere, logged by hand. |
| Cost per published event | From the ledger. |
| Impact correctness | Golden tests in minor units. |

Keep every graded event and its snapshots under `backend/evals/feed_corpus/`. This becomes the
corpus of verified hard cases that the moat discussion identified as worth owning.

## 12. Risks

| Risk | Response |
|---|---|
| Primary pages change rarely, or rotate banners constantly | The Phase 1 decision point. Use `css_hint` to watch the terms block, not the page. |
| One reviewer cannot keep up | Cap facts-lane proposals per day. The news lane does not wait. |
| Terms change, or the project goes commercial | `SourcePolicyRecord.terms_read_on` gets a re-read date; a commercial launch redoes Phase 0. |
| A wrong event is published | `retract`, a visible correction through `supersedes`, and impacts recomputed. |
| Scope | Phases 0 to 4 are about 7 to 8 weeks of focused work. They compete with verifying real card data and building sign-in. Phases 0 to 2 are the part that makes the product different; do those first. |

## 13. Not building

- A general web crawler.
- Scraping Daily Drop, The Points Guy or point.me.
- A vector database, a message queue, Postgres or a multi-agent framework.
- Any path where a model writes to the knowledge base or computes a money value.

## 14. First week

1. Answer the assumptions in section 2.
2. Merge the Firecrawl branch.
3. Claude client, ledger and caps.
4. Live extraction on the Axis Atlas capture; record what it got right and wrong.
5. Permission review for the candidate sources.
6. Write `ChangeEvent` and the three Phase 1 `terms` blocks.
