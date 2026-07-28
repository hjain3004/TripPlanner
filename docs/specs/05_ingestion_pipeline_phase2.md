# 05 — Phase 2: Offline Ingestion Pipeline (Crawl4AI + Human Review)

**Do not build during the Kernel MVP.** Kernel data is hand-curated/sample data. This spec exists so the knowledge base schema and provenance model are ingestion-ready from day one. It governs slowly changing financial/reference facts; it does not fetch live flight, hotel, or award inventory, which belongs exclusively to the target Data Gateway (09/16).

## Design principle

Crawling financial data fails *silently* (mis-extracted caps/exclusions), not just loudly (blocks). Therefore the pipeline's job is to produce **draft change proposals for a human**, never direct writes to the knowledge base. This is a Human-in-the-Loop pattern applied to ingestion: writing a fact into the KB is the "significant action" that requires approval. No application runtime layer crawls; this whole pipeline is an offline batch job (manual trigger or cron). Profile-eligible runtime APIs/MCPs are external evidence services, not this ingestion crawler, and are governed separately by 09/16.

## Stage 0 — Discovery (how you learn a card or offer exists)

The pipeline below monitors pages you already know about. It has no answer to the prior question: *how do you learn that a card or an offer exists at all?* Left unsolved, the watchlist is hand-curated and the knowledge base only ever knows what one person happened to read.

Discovery closes that gap **without touching the provenance model**. Aggregators (NerdWallet, The Points Guy, CardExpert, Paisabazaar, PolicyBazaar, YallaCompare) are read as *leads*, never as sources. A lead says "this card exists" or "this offer looks live, go check." Every value that reaches the KB is still extracted from the issuer's own page or T&C PDF, so `source_url` always points at a primary source.

### The invariant

**An aggregator claim can never become a stored fact.** Not "is validated against" — *cannot*. This is enforced structurally, not by a rule:

```python
class DiscoveryCandidate(BaseModel):
    """A lead. Deliberately has NO Provenance block."""
    id: str
    found_at: date
    hint_url: str                    # the aggregator page the lead came from
    hint_source: str                 # "cardexpert" | "nerdwallet" | ...
    corridor: Literal["IN", "AE", "US"]
    kind: Literal["card", "offer", "welcome_bonus"]
    issuer_guess: str
    product_guess: str
    claim_summary: str               # what the aggregator asserts, verbatim
    issuer_url_to_verify: str | None # the primary page a curator must go read
    status: Literal["pending", "promoted", "rejected", "duplicate"]
    decided_by: str | None
    decided_at: date | None
```

`DiscoveryCandidate` has no `Provenance` and no `source_type`. **Do not** add an `aggregator_hint` member to `Provenance.source_type` (01 §1) — that would make every KB row *able* to carry a hint provenance and would reduce the invariant to a runtime check on a type that permits the bad state. A candidate is a different kind of thing from a fact, so it gets a different type. The only path from candidate to KB is: a curator promotes it to a **watchlist entry**, the normal pipeline fetches the *issuer* page, the extractor quotes that page, and a human approves the result. Three human-gated steps, and the aggregator's numbers are never among the inputs to any of them.

Tests to write on day one of Phase 2: assert `"provenance" not in DiscoveryCandidate.model_fields`; assert no code path constructs a KB row from any `DiscoveryCandidate` field other than `issuer_url_to_verify`.

### Seed aggregators per corridor

| Corridor | Sources | Notes |
|---|---|---|
| India (`IN`) | CardExpert, Paisabazaar | CardExpert is enthusiast-written and fast on new launches; Paisabazaar is comparison-shopping, lags, but is broad. |
| UAE (`AE`) | YallaCompare, PolicyBazaar UAE | Both are brokers — treat coverage as commercially skewed, never as complete. |
| US (`US`) | NerdWallet, The Points Guy | Both monetize via card referral. Assume the *set* of cards covered is biased; assume the *existence* claim is reliable. |

Every one of these earns referral revenue on card applications. That is precisely why they are leads and not sources: their incentive is to tell you a card exists (reliable) and to characterize it favorably (not reliable).

### Terms-of-service gate

Aggregator terms are materially more restrictive than issuer T&C pages, which are published for consumers to read. Before a source is added to the discovery list, a human records on the entry: the ToS URL, the date read, whether automated access is permitted, and any rate limit the terms state. A source whose terms prohibit automated access is `manual_only` — a curator reads it and files candidates by hand; the rest of the stage is identical. No source is added without this record.

All Fetcher constraints below apply unchanged to discovery: robots.txt, ≥ 10s per-domain delay, honest user agent, no login-walled scraping, no proxy rotation.

## Pipeline

```
[Stage 0: Discovery — aggregators, ToS-gated] ─▶ DiscoveryCandidate ─▶ review queue
curator promotes candidate ─▶ watchlist.yaml entry pointing at the ISSUER page
watchlist.yaml ─▶ [Fetcher: Crawl4AI, polite] ─▶ raw snapshot store
snapshot ─▶ [Differ: normalized-markdown diff vs last snapshot] ─▶ changed? ─▶ no: stop
changed ─▶ [Extractor: LLM → typed draft (01 schemas), temperature 0]
draft ─▶ [Validator: schema + sanity rules] ─▶ [Review queue (SQLite + tiny web UI)]
human approves/edits/rejects ─▶ approved rows written to KB with provenance:
    source_type=official_page|tnc_pdf, verified_by=<curator>, needs_verification=false,
    last_verified=<today>, source_url, confidence=<curator-set>
```

Components:

0. **Discovery** — `ingestion/discovery_sources.yaml`: `{name, url, corridor, tos_url, tos_read_on, automated_access_permitted: bool, stated_rate_limit?, manual_only: bool}`. Runs at most weekly; emits `DiscoveryCandidate` rows into the same review queue as change proposals, distinguished by `status`. A promoted candidate becomes a watchlist entry whose `url` is the **issuer** page, never the aggregator page. Duplicate suppression is by `(issuer_guess, product_guess, corridor)` against both existing candidates and existing KB `cards`.
1. **Watchlist** — `ingestion/watchlist.yaml`: `{url, kind: card_page|offer_page|tnc_pdf, target: card_id|offer_scope, css_hint?, check_frequency_days}`. Only pages you have a reason to monitor; tens, not thousands.
2. **Fetcher** — Crawl4AI in fit-markdown mode; obey robots.txt; ≥ 10s per-domain delay; identify honestly via user agent; cache raw HTML + markdown snapshots under `ingestion/snapshots/{url_hash}/{date}/`. PDFs go through the same store (extract text via pdfplumber). If a site blocks or requires login, mark the watchlist entry `manual_only` — a human copies the T&C text into the snapshot store by hand; the rest of the pipeline is identical.
3. **Differ** — strip nav/boilerplate (Crawl4AI's fit output already helps), normalize whitespace, unified diff vs previous snapshot. No change → touch `last_checked`, stop. This makes the LLM step cheap and rare.
4. **Extractor** — one LLM call per changed page: input = markdown + the *current* KB rows for that target + the diff; output = `ChangeProposal{target_table, target_id, proposed_row (01 schema), change_summary, extractor_confidence, quotes: [verbatim source snippets supporting each changed field]}`. The `quotes` field is mandatory — it is what makes human review fast and is the main defense against hallucinated extractions. Extraction that cannot quote support for a field must leave that field null.
5. **Validator (code)** — schema validation plus sanity rules: earn rates within plausible bounds (0.1–30 pts/₹100-equivalent), caps > 0, `valid_to` ≥ today, forex markup 0–500 bp, offer discount ≤ 50% or flagged, currency consistent with issuer country. Violations annotate the proposal, they don't auto-reject.
6. **Review queue** — table `change_proposals{id, status: pending|approved|edited|rejected, payload, quotes, validator_flags, created, decided_by, decided_at}` + a minimal FastAPI page listing pending proposals with side-by-side current-vs-proposed and the supporting quotes. Approve/edit/reject buttons. Keyboard-driven; a curator should clear 20 proposals in 10 minutes.
7. **Staleness sweeper** — nightly job flags KB rows past staleness thresholds (offers 90d, rules 365d) → creates re-verify tasks in the same queue even without page changes.

## Metrics to track from day one of Phase 2

Proposals/week, approval rate, edit rate (approved-with-edits = extractor near-misses — the key quality signal), median review time, staleness distribution of live KB rows. If edit rate > ~30%, improve extractor prompts/quotes before scaling the watchlist.

## Explicit non-goals

No live booking-inventory crawling, proxy rotation, CAPTCHA circumvention, login-walled scraping, high-frequency polling, or autonomous KB writes ever (even at high extractor confidence — the approval step is the product's trust boundary, not a temporary crutch).

Discovery adds three more: **no aggregator value ever reaches the KB** (only the issuer URL a lead points at is carried forward); **no affiliate or referral link is stored, followed, or rendered** — the discovery stage reads aggregators for existence claims and the product never participates in their referral economics; and **no source is crawled before its ToS record exists** on the `discovery_sources.yaml` entry.
