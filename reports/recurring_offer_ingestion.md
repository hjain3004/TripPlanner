# Recurring welcome-offer ingestion

Branch `codex/recurring-offer-ingestion`. Nothing here approves a financial fact, writes a repository
seed or catalog, or spends a Firecrawl credit. **No live Firecrawl request has been made for this work**
(recorded allowance: 67 of 500 used before this branch; this branch has used 0).

## What an operator can do now

All commands are `python -m ingestion.review_server <command>` from `backend/`.

1. **Name the welcome-offer pages** in a YAML file (what the operator, not the page, says):

   ```yaml
   targets:
     watch-atlas-offers:            # an existing, policy-approved Firecrawl watch target
       card_id: axis-atlas          # a seeded card
       source_url: https://…        # the offers page
       points_currency_id: …        # optional: LoyaltyProgram id for a points bonus
   ```

2. **Collect** (`acquire`, `refresh-due`, or the scheduled `recurring-run`) with
   `--welcome-targets targets.yaml --published-welcome-catalog <dir> --per-request-credits 5 …`.
   For those targets the scrape requests Firecrawl's v2 `json` format next to `rawHtml`
   (5 credits reserved: 1 page + 4 extraction, per the billing page), keeps the provider's structured
   result in the provider-envelope artifact, and turns it into **unverified draft proposals**
   (`insert` for a new offer, `update` for a changed published one). Firecrawl runs the model; no model
   client exists here and `llm_calls` is 0.
3. **Review** in the existing queue (`review-queue`, `inspect`, `decision`). Quotes and offsets are
   shown as for every other fact.
4. **Publish** an approved proposal: `init-welcome-catalog --catalog-dir D` once, then
   `publish-welcome --catalog-dir D --proposal-id P`. History: `welcome-history`. Undo:
   `rollback-welcome --publication-id …`.
5. **Serve**: set `TRIPWISE_WELCOME_OFFERS_PATH=D/card_acquisition_offers.yaml`. The API reloads the file
   whenever its mtime/size changes (no restart); an invalid edit keeps the last good catalog and sets
   `welcome.catalog.last_reload_error`. Unset, the shipped empty catalog is used.
6. **Credits**: `--lifetime-credits N --opening-credits-used M` record a lifetime allowance once in the
   database; later flags cannot loosen it; `credit-status`; raised only by `raise-lifetime-cap`.
7. **Incomplete extractions** are listed by `incomplete-drafts` (what is missing and why each field was
   rejected) instead of becoming padded rows.
8. **Schedule**: `recurring-run … --slot 2026-11-28T09` is one bounded `refresh-due` pass under a file
   lock (exit 75 if another is running), keyed by slot so a repeated slot replays and spends nothing,
   with `recurring/last_run.json` and `history.jsonl`. Example cron:
   `0 9 * * * cd backend && .venv/bin/python -m ingestion.review_server recurring-run <same flags>`.

## Demonstrated (execution mode: retained synthetic captures, real SQLite/artifacts/CLI processes)

`evals/test_recurring_cli.py` drives one process per step: initial collection → queue → publication
refused before approval → unchanged page → curator approval → publication → changed terms (blocked by
the lifetime allowance, then allowed after an explicit raise) → update proposal → history → rollback;
plus slot idempotence, lock exclusion, the 5-credit requirement and incomplete drafts.
`evals/test_recurring_welcome_extraction.py` covers initial / replay-after-restart / unchanged /
changed / dropped-quote / unsupported-value / missing-extraction and request-id conflicts.
`evals/test_recurring_welcome_publication.py` proves review, approval, publication, reload, rollback,
and consumption by the **authenticated `/account/wallet/{entry}/welcome-status` route** with no
restart; a synthetic verifier is never served.

The `data.json` blocks in those captures are **authored**. They prove the integration, not what
Firecrawl returns.

## Not verified / limits

- **No live Firecrawl response has been seen for `json` extraction.** The documented shape
  (`data.json`), cost (+4) and timeout (60 s default for `json`) come from the official docs read on
  2026-11-25; cache-hit and failed-extraction billing are not documented. Extraction runs on Firecrawl's
  markdown conversion, so a quote that differs from the retained normalized text is rejected; how often
  that happens on real issuer pages is unknown until one real capture.
- Unchanged pages still cost 5 credits per pass (the extraction is bundled with the fetch). Intervals
  are the lever; a two-step fetch would cost 1 credit unchanged but 6 when changed.
- Currency, the points-currency mapping and exclusions have no quoted evidence, so published rows keep
  `needs_verification=true`; Case-B-only terms stay unknown (`None`).
- Case B treats an offer with unknown Case-B terms as not assessable (reason `NO_APPROVED_OFFER` with an
  explicit message); a precise code needs a contract change.
- No real issuer proposal exists; the shipped catalog is untouched; nothing was approved.
- **Alexandria** (Firecrawl's catalogued provider tools): the docs I read name no card or offer data, no
  per-call pricing, and require a human to accept third-party terms. Not used; no terms accepted.
- No local model or Ollama is needed or used.

## Owner decisions still needed

1. Authorise one live `json` capture: which permitted issuer offers URL, policy and exact request
   (5 credits against the remaining allowance), so the real response shape can be checked.
2. Whether `NO_APPROVED_OFFER` is acceptable for unknown Case-B terms or a new contract code should ship.
3. Curators and the real approvals; whether to commit any real offer to the repository catalog.
4. The schedule interval per target (credit cost per pass is 5).

## Live command (not run)

```
FIRECRAWL_API_KEY=… python -m ingestion.review_server acquire --data-dir D --source-policy P \
  --watch-target W --target-id watch-… --welcome-targets T --live-firecrawl --confirm-no-overage \
  --robots-file R --client-event-id live-… --per-request-credits 5 --per-run-credits 5 \
  --per-month-credits 5 --lifetime-credits 500 --opening-credits-used 67 --timeout-seconds 60
```
