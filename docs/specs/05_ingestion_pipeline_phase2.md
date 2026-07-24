# 05 — Phase 2: Offline Ingestion Pipeline (Crawl4AI + Human Review)

**Do not build during the Kernel MVP.** Kernel data is hand-curated/sample data. This spec exists so the knowledge base schema and provenance model are ingestion-ready from day one. It governs slowly changing financial/reference facts; it does not fetch live flight, hotel, or award inventory, which belongs exclusively to the target Data Gateway (09/16).

## Design principle

Crawling financial data fails *silently* (mis-extracted caps/exclusions), not just loudly (blocks). Therefore the pipeline's job is to produce **draft change proposals for a human**, never direct writes to the knowledge base. This is a Human-in-the-Loop pattern applied to ingestion: writing a fact into the KB is the "significant action" that requires approval. No application runtime layer crawls; this whole pipeline is an offline batch job (manual trigger or cron). Profile-eligible runtime APIs/MCPs are external evidence services, not this ingestion crawler, and are governed separately by 09/16.

## Pipeline

```
watchlist.yaml ─▶ [Fetcher: Crawl4AI, polite] ─▶ raw snapshot store
snapshot ─▶ [Differ: normalized-markdown diff vs last snapshot] ─▶ changed? ─▶ no: stop
changed ─▶ [Extractor: LLM → typed draft (01 schemas), temperature 0]
draft ─▶ [Validator: schema + sanity rules] ─▶ [Review queue (SQLite + tiny web UI)]
human approves/edits/rejects ─▶ approved rows written to KB with provenance:
    source_type=official_page|tnc_pdf, verified_by=<curator>, needs_verification=false,
    last_verified=<today>, source_url, confidence=<curator-set>
```

Components:

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
