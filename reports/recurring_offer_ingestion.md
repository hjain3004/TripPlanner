# Recurring welcome-offer ingestion

Branch `codex/recurring-offer-ingestion`. Nothing here approves a financial fact, confirms an origin,
publishes a real offer or writes a repository seed or catalog. Everything real stays pending the
owner. Raw captures, private databases, review packets and logs are outside Git.

## What works

Collect → cheap change check → Firecrawl-hosted JSON extraction only when needed → deterministic
validation → draft proposal or precise incomplete draft → existing review queue → named-curator
approval → controlled publication to an operator catalog → the API reloads it → changed terms become
an update proposal → rollback. A scheduler-compatible wrapper runs the same command repeatedly.

All commands are `python -m ingestion.review_server <command>` from `backend/`.

| Step | Command |
|---|---|
| Name welcome pages (what the operator says) | `--welcome-targets targets.yaml` (`card_id`, `source_url`, optional `default_currency`, `points_currency_id`) |
| Collect | `acquire`, `refresh-due`, or `recurring-run --slot S` |
| Review packet of incomplete drafts | `incomplete-drafts --format md --out <private path>` |
| Re-derive drafts after a rule fix, no request, no credits | `reextract-welcome --target-id T --client-event-id E` |
| Review/approve | existing `review-queue`, `inspect`, `decision` |
| Publish / history / undo | `init-welcome-catalog`, `publish-welcome`, `welcome-history`, `rollback-welcome` |
| Per-source state | `source-status` (`last_checked_at` is the machine's; `last_verified` on a published row is a human's) |
| Credits | `credit-status`, `raise-lifetime-cap` (explicit, attributed); flags `--lifetime-credits --opening-credits-used` |
| Serve | `TRIPWISE_WELCOME_OFFERS_PATH=<catalog>/card_acquisition_offers.yaml` |

### How collection spends credits

1. **Check** (1 credit): a plain page fetch, compared with the *welcome-relevant text* (term-bearing
   lines only, so navigation and footer changes do not count) recorded at the last completed
   extraction. Unchanged → stop. A failed check proves nothing about the offer and changes nothing.
2. **Extract** (5 credits: 1 page + 4 JSON) only for a changed page or one never successfully
   extracted. This second capture is the version the quotes bind to; its own envelope carries
   Firecrawl's JSON. A failed extraction is retried next pass, never read as "offer withdrawn".
3. Both requests are separate durable reservations with the documented cost; real charges are read
   from `metadata.creditsUsed`. Replays spend nothing. A lifetime allowance is recorded once in the
   database and cannot be loosened by later flags.

## Real Firecrawl acceptance (executed, within the existing allowance)

**Sources and access basis.** Two Axis Bank public card pages on `www.axis.bank.in`:
`.../axis-bank-atlas-credit-card` and `.../rewards-credit-card`, under the owner-approved policy
`axis-bank-in-firecrawl-card-page-v1` (automated access permitted, reviewed by the owner on
2026-11-07; retained `robots.txt`: `User-agent: * / Allow: /`). Basic proxy, no actions, no
retries, 31-second spacing between requests to the domain (policy minimum 30), Firecrawl-hosted JSON
extraction only, no separate model.

**What Firecrawl returned.** HTTP 200; `creditsUsed` was 1 for each check and 5 for each JSON
extraction, matching the documented cost. The JSON listed 2 offers (Atlas) and 4 (REWARDS), but with
mistakes the deterministic checks had to stop:

- a bare `30` from "within 30 days" as a rupee minimum spend (it parses as a rupee amount);
- a quote that was only `37`; an annual-fee amount (5,000 rupees) offered as the welcome bonus; both a
  points bonus and a flat amount for one offer; the older cohort's 5,000-mile variant mixed with the
  current 2,500-mile / 37-day rule on the Atlas page;
- non-welcome benefits (annual, milestone, lounge, a Swiggy discount) listed as offers;
- `N/A` placeholders; and a quote with a space the page text lacks ("REWARD Points" vs
  "REWARDPoints").

Each was fixed against the retained responses without another request (`reextract-welcome`, 0
credits), with regressions that use synthetic text of the same shapes.

**Outcome: no complete real draft.** The pages genuinely omit required terms.

- Atlas: a "Welcome Benefit" with a points claim, a start date and a conflicting flat amount; the page
  states no minimum spend (the benefit is "upon first transaction") and no end date. Recorded as an
  incomplete draft ("conflicting bonus", a curator must decide).
- REWARDS: "Welcome benefit": 5,000 points, minimum spend 1,000 rupees, 30 days, each with its verbatim
  quote and offsets. Missing exactly `valid_to` (evergreen, no end date stated) and `bonus_currency_id`
  (the page names "EDGE REWARD Points" but no program in our registry; none was invented).

So there is **no pending real welcome proposal**. The review queue holds one older, unrelated pilot
card proposal. Incomplete drafts persist across processes (each CLI call is a new process) and appear
in `source-status` and the private review packet.

**Private paths (outside Git).** Workspace
`~/tripwise-ingestion-data/recurring-live-acceptance-20261126/`:
`data/` (database and artifacts, a copy of the pilot data so its charge stays in the ledger),
`inputs/`, `retained-responses/` (the five complete responses and their request metadata, mode 0600,
no credential), `live_run_1..3.json`, and the review packet
`review_packet_incomplete_drafts.md`.

**Credits.** Opening usage 67 (owner reconciliation) + 1 completed pilot request found in the pilot
database (counted conservatively, possibly already inside the 67) = 68 before this work. This task:
Atlas check 1 + extraction 5, REWARDS check 1 + extraction 5, and one unchanged real pass (check 1, no
extraction) = **13 of the 20 allocated**. Lifetime used **81 of 500; remaining 419**. `raise-lifetime-cap`
was not used. The 7 unspent allocated credits were deliberately not spent: no remaining permitted page
states every required term, so more calls would not change the outcome.

**Unchanged vs changed (real and recorded).** Real: a second pass over the Atlas page cost 1 credit,
requested no extraction and made no proposal (the relevant text hash matched). Changed terms were
exercised from retained recordings (never a modified issuer response presented as live): a changed term
costs 1 + 5 and yields an update proposal; boilerplate-only changes cost 1 and extract nothing.

## Catalog failure handling

A deleted file after a good load no longer raises: the last good copy keeps being served (offers keep
their own approval dates; nothing is re-stamped as fresh), the failure is logged and exposed by
`catalog_status()` (`serving_last_good_copy`, `last_reload_error`, `failing_since`), and recovery clears
it. With no good copy ever loaded the API answers 503, never data. Expiry and historical-offer rules
still apply to the served copy.

## Case B

An approved offer lacking approval time, delivery time or annual fee is now refused as
`OFFER_TERMS_INCOMPLETE` (`details.unknown_terms`), not "no approved offer". OpenAPI, the generated
client types (verified identical to a fresh generation) and a typed mock ship together. Nothing is
guessed; held-card behavior and arithmetic are unchanged.

## Scheduling and restart

`recurring-run` selects due targets in stable order, spaces requests to one source, holds a file lock
(exit 75 if busy), is idempotent per `--slot`, isolates a failing source from the rest, writes
`recurring/last_run.json` and `history.jsonl` with per-source state and credits, and keeps lifetime
accounting in the database across restarts. `deploy/recurring-ingestion/` has a wrapper, an env
template, a launchd and a cron example. It is **offline by default**; live spending needs an explicit
`TRIPWISE_RECURRING_LIVE=1` and a credential in the scheduler's environment. Nothing was scheduled or
enabled.

## Synthetic approval → publication → API (never the owner's real facts)

`evals/test_recurring_cli.py` (separate processes) and `evals/test_recurring_welcome_publication.py`:
pending proposal → named acceptance-curator approval → controlled publication → authenticated
welcome-status and acquisition behavior with reload and no restart → changed terms → update proposal →
approval → publication → rollback. These use retained synthetic captures and are not real evidence.
Published rows keep `needs_verification=true` unless every fact field was quoted. A campaign end date
excludes a card opened afterwards but never an existing holder's historical window.

## The gate

The full-suite timing failure (`test_recompute_with_real_catalog_items_stays_fast`, about 950 ms
against 500 ms in the full suite, about 115 ms alone) was a genuine hot loop: recompute's retrieval
ranks about 46,000 catalog places and recomputed two pure taxonomy functions about 140,000 times per
call under heavy GC pressure. Those two functions are now memoized; the threshold is unchanged. The
final `make seed` and unchanged `make gate` log is kept outside Git:
`~/tripwise-ingestion-data/recurring-live-acceptance-20261126/final_gate.log`.

## Genuine remaining limitations / owner decisions

1. **Evergreen offers cannot become proposals today.** Real pages state no end date and no program
   identity, and `valid_to` and `bonus_currency_id` are required. Options: allow an explicit
   "no published end date", and add a verified program registry entry for each issuer currency (a
   financial fact for the owner to approve).
2. Firecrawl's extraction needs a deterministic filter in front of it (above); cache-hit and
   failed-extraction billing remain undocumented. An unchanged page still costs 1 credit per pass.
3. Cohort variants on one page (older vs current welcome terms) cannot be separated by the extractor;
   such an offer is reported as conflicting for a curator.
4. No real approval, origin confirmation or publication occurred.
