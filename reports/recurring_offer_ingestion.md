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

**Outcome: a real pending proposal and incomplete review evidence.** REWARDS's retained
response supports 5,000 points, a ₹1,000 qualifying spend and a 30-day window. Its pending proposal
survives reopening SQLite and is visible in `review-queue`; the issuer names `EDGE REWARDPoints`,
but its mapping to an approved program and the campaign end remain unknown. Eligibility exclusions
also lack evidence. These gaps are visible to the reviewer; no real decision or publication was made.
The initial immutable proposal retains its original empty exclusions field but the queue marks it as
unresolved evidence (D1). A replay with corrected representation was refused as a conflicting
immutable payload; the existing audit record was preserved. New extraction records absent exclusions
as unknown, not as a claim that none exist.

Atlas's annual fee is not a welcome bonus. The source mixes 2,500- and 5,000-mile terms for different
card-sourcing cohorts; the review packet preserves both and refuses the unsupported association.
The first-transaction condition is not a monetary spend threshold. No start date or bonus is guessed.

**Private paths (outside Git).** Workspace
`~/tripwise-ingestion-data/recurring-live-acceptance-20261126/`:
`data/` (database and artifacts, a copy of the pilot data so its charge stays in the ledger),
`inputs/`, `retained-responses/` (the five complete responses and their request metadata, mode 0600,
no credential), `live_run_1..3.json`, and the review packet
`review_packet_incomplete_drafts.md` and the newer `review_packet_followup.md`. The pending proposal
is accessible with `python -m ingestion.review_server review-queue --data-dir <workspace>/data`.

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

## Gate status — failed, acceptance pending

On committed tree `85d3f6b6ca5cf9a559fe892a515e81dbb8e51e14`, `make seed` succeeded and the
unchanged `make gate` failed in full pytest: `test_recompute_with_real_catalog_items_stays_fast`
took 899.03 ms (limit 500 ms). The suite otherwise reported 3,414 passed, one skipped and three
warnings; gate stopped before its later phases. Its complete log is retained outside Git at
`~/tripwise-ingestion-data/recurring-live-acceptance-20261126/gate-85d3f6b.log`. This is not a
passing acceptance gate. The private retention and confinement checks passed, as did strict typing
and lint for the changed packages, deterministic contract regeneration, frontend TypeScript and
ESLint (15 warnings). The old process-wide `gc.freeze()` is removed.

The unchanged performance test passed in isolation with synthetic heaps of one million and six
million tracked objects. A diagnostic run through the preceding tests observed about 3.1 million
tracked objects and 835–877 ms full collections during catalog setup; in that run the timed test
passed. These observations support the GC concern but do not establish a reliable fix for the
full-suite timing failure. The diagnostic was stopped after reaching that test, and its log and
GC events remain in the task's private evidence directory and `/private/tmp` respectively.

The subsequent offline re-extraction rejects the Atlas annual fee as a bonus and refuses to
associate the older cohort's 5,000-mile benefit with the later cohort's start date. It preserves
quoted `EDGE Miles` and `EDGE REWARDPoints` names as unmapped evidence, not approved program
identifiers. The refreshed private packet is `review_packet_followup.md` beside the live captures.
No provider calls or credits were used for this follow-up.

## Genuine remaining limitations / owner decisions

1. Unknown expiry is represented as unknown, not perpetual. Offers with unknown end or eligibility
   exclusions are withheld from both acquisition and held-card selection. The latter is deliberately
   conservative: historical entitlement is not independently established by an omitted expiry.
   An unmapped issuer program stays unvalued and requires an owner-approved mapping.
2. Firecrawl's extraction needs a deterministic filter in front of it (above); cache-hit and
   failed-extraction billing remain undocumented. An unchanged page still costs 1 credit per pass.
3. Cohort variants require a curator: the mapper retains competing context rather than inferring
   a qualifying window or joining a bonus to the wrong cohort.
4. No real approval, origin confirmation or publication occurred.
