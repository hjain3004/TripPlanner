# Financial-data readiness for the India → Singapore demonstration

Branch `codex/financial-data-readiness`, based on `main` @ `21f959a`. Decisions: `DEVIATIONS.md`, section
"Financial-data readiness". This track owns `backend/ingestion/` and this report. No seed, golden, spec,
welcome/acquisition code, planning API, provider transport or contract was changed, and no financial value was
approved, applied to a repository seed, or marked verified.

## 1. What an operator can do now

```bash
cd backend                                   # all commands: python -m ingestion.review_server <cmd>
readiness    [--data-dir D] [--seeds-dir S] [--wallet-card ID ...] [--findings F.yaml] [--format md|json] [--out FILE]
review-queue --data-dir D [--status pending|approved|...] [--format md|json] [--out FILE]
# and, unchanged, from earlier work:
stage-capture … --captured-at T     status      bundle      dry-run      apply      coverage      rollback
```

* **`readiness`** answers, for the shipped demonstration trip (`demo-del-sin`, five spend lines) and the
  demonstration wallet (HDFC Infinia + Axis Atlas): which seeded facts the deterministic optimizer actually uses,
  the state of each, what evidence is still missing, which facts the schema cannot hold, and which decisions only
  a human can make. **Influence is measured, not asserted:** every integer fact is doubled and halved, and every
  text fact replaced by the other values the seeds hold for it (a network, an issuer, a card link, a merchant), in
  memory, and the *unchanged* optimizer re-run; whole rules, valuations and offers are removed the same way. Facts it
  cannot vary (lists, dates, facts with no sibling value) are reported **unmeasured, never as harmless**. It reads
  seeds and databases and writes nothing: the databases are opened read-only, a missing directory is not created, and
  a database at another schema version is refused rather than migrated.
* **`review-queue`** prints the packet a curator needs to decide: for each draft, exact quote and offsets, current
  vs proposed value, capture age, the row's provenance today, the fields the draft says nothing about, what blocks
  verification (D1 field coverage, D2 origin), and decision command *templates* with placeholders. It never runs a
  decision. Both commands refuse to write their output inside a git checkout, because packets quote captured
  documents.
* **`--findings`** is a small YAML file of what a human found reading a capture ("this document does not state the
  forex markup"). It is shown next to the fact and is labelled as a human observation, not tool output.

## 2. Evidence mode, and what was not done

| | |
|---|---|
| Evidence available locally | **one** manual plain-text copy of an HDFC Infinia product page, saved 2026-10-30 22:40 PDT (`2026-10-31T05:40Z`), 6 days old when this packet was produced. No other issuer capture exists on this machine. |
| Research vs. ingestion-eligible evidence | **No web research was done in this task.** Everything about the page comes from the saved local copy, read by the assistant; it is ingestion-eligible only as a manual capture (D2 origin is *not* confirmed). |
| Extraction | assistant-authored curator-style extraction (`claude-operator`), **not** model output, not by the owner. |
| Network / credentials / spend / crawling | none. |
| Axis Atlas, offers, HDFC rules | **no capture exists**: the dependency is documented (section 6), nothing is manufactured. |

## 3. The reality, by category

| Category | State today |
|---|---|
| **Implemented arithmetic** | Deterministic, unchanged, golden-protected: card forex markup and its tax, base earn, rule earn and caps, point valuations, offer discounts (percent, flat, cap, uses), cap fall-through. Measured on this trip, **annual fee and lounge visits do not move it**; forex markup, base earn, rule earn/cap, valuation value, offer discount/cap, **and a card's network and issuer (they decide which restricted offers apply)** do. |
| **Populated but unverified** | **Every** seeded fact in scope is a placeholder (`manual_curation`, `verified_by UNVERIFIED`, `needs_verification=true`, last touched 2026-07-07). Of the 63 facts this trip depends on, **0 are verified**. |
| **Missing** | no welcome offers (shipped catalog empty), no card→points-program link, no real program identity for the demo wallet's points balance; for Axis Atlas and for offers, no evidence at all. |
| **Awaiting human approval** | 2 drafts staged this task (below); and 4 earlier approvals by the owner on an older source identity, which cannot reach verification (section 5). |

What the trip depends on (63 facts): **31 measured to move the result, 32 that could not be varied and are
unmeasured** (they could matter). By issuer: HDFC Bank 8 card + 10 rule + 4 valuation + 11 offer facts; Axis Bank 8 card
+ 9 rule + 3 valuation; Klook offer 10. Offers that currently do not apply to this trip (removing the seeded
MakeMyTrip coupon changes nothing) are not counted, but their eligibility facts are unmeasured and should be checked
before anyone relies on them.

## 4. The drafts prepared (the review queue)

Staged through the real path (`stage-capture`, real SQLite, no model, no network), under the new source identity
`hdfc-bank-in-manual-card-page` (a copy of the owner's policy that **only the owner can attest**):

| Row | Fields quoted by the page | Would any value change? |
|---|---|---|
| `cards/hdfc-infinia` | `annual_fee_minor`, `base_earn.points`, `base_earn.per_amount_minor`, `issuer`, `name` | **No** — all equal the seed |
| `point_valuations/infinia-portal-val` | `value_micro_major_per_point` | **No** — equals the seed |

Both are `pending`, blocked from verification by **D1** (the card draft leaves `base_earn.currency`, `country`,
`fee_currency`, `forex_markup_bp`, `forex_markup_tax_bp`, `lounge_intl_visits_per_year`, `network` unevidenced; the
valuation draft leaves `card_id`, `path`, `currency`, `min_points`, `conditions`) and **D2** (manual capture, origin
unconfirmed). Even if the owner approves and confirms origin, neither row can become verified from this capture.

What the page does **not** support, recorded as findings next to the facts (16 in the readiness view): no forex
markup or its tax is stated (a link to a rates page only); no network; the portal earn is a multiplier of the base
rate ("up to 10x") and cannot confirm the seed's "points per ₹100"; the rule's categories/channels/exclusions/validity
and earn cap are not stated or need judgment; no minimum redemption; international lounge access is stated as
unlimited, which the integer field cannot hold (and contradicts the seed's finite number).

## 5. Reused approvals vs. approval still required

The owner's 2026-10-31 approvals cover 4 facts (annual fee, two earn fields, the valuation) on source policy
`hdfc-bank-in-manual` (allows only `manual_capture`). They **still apply** (`status`: `approval_applies=true`), so the
operator demonstration used **those only**:

```
bundle b55a245c…  (the same hash as the earlier pilot: deterministic)
dry-run           both entries confirmed_unchanged, kb_constructs true, seed files unchanged
apply (scratch)   committed, ledger-only: no seed file changed
readiness after   3 trip facts move from "approved, not applied" to "evidence recorded, origin unconfirmed"
optimizer         repository seeds vs applied scratch seeds: identical result
rollback          rolled_back; scratch seeds byte-identical; repository seeds untouched
```

They do **not** transfer to the new drafts (a different policy, target, snapshot and proposal identity). Origin
confirmation is impossible for the old identity (its policy does not allow `card_page`), which is why the new
drafts exist. Asking for a bundle from a draft nobody has decided is refused, and now says why (defect below).

## 6. Evidence still to be captured (by the owner, by hand, within each issuer's terms)

| Issuer | Document | Unverified facts the trip depends on |
|---|---|---|
| Axis Bank | fees & charges / MITC | 8 (forex markup and tax, base earn, network, issuer, …) |
| Axis Bank | rewards terms (rate, cap, exclusions, portal terms) | 8 |
| Axis Bank | rewards redemption terms | 2 |
| HDFC Bank | fees & charges / MITC (the saved page links to it) | 7 (3 without any draft or finding, 4 read but not stated: forex markup and tax, network, lounge) |
| HDFC Bank | rewards terms / SmartBuy terms | 10 (2 without any draft or finding, 8 read but not stated) |
| HDFC Bank | rewards redemption terms | 4 (2 without any draft or finding, 2 read but not stated) |
| HDFC Bank, Klook | offer terms pages | 12 + 10 (no capture; the seeded merchant offers are not on any captured page) |

The tool lists these because the saved page does not state them; it does not know whether another capture exists
elsewhere ("point us to one" is in the decisions below).

## 7. Data requirements this track cannot meet (owner: card-acquisition / schema; described, not built)

* **Welcome offers.** The shipped held-card catalog holds 0 offers for the demo wallet, and no ingestion table can
  hold one. The acquisition model needs a minimum spend and a spend window; the saved HDFC page states a points
  welcome benefit tied to fee realisation and activation and **no** minimum spend or window (possibly in terms not
  captured). Whether such an offer fits the model is the acquisition track's decision; nothing is guessed here.
* **Program identity.** No `card_currency` loyalty program is seeded and neither `Card` nor `PointValuation` links a
  card to a program, so a points bonus has nothing to be valued through. The demo wallet's points balance is in
  `voyager-prime`, which is not a seeded program; the seeded transfer graph and award chart are fictional placeholders.
* **Not representable in today's rows:** a monthly redemption cap in points (on the saved page), a fee waiver on
  annual spend, an "unlimited" lounge entitlement. They must not be written into free-text fields.

## 8. Defect found and fixed

`bundle` for a draft with no decision recorded the refusal as the raw text "tuple index out of range". Nothing
unsafe happened (zero entries; `apply` refuses it), but the operator could not tell the draft was awaiting a
curator. It now says "no decision yet: the proposal is still awaiting a curator"
(`backend/evals/test_financial_readiness.py`).

## 9. Exact decisions only the owner can make

1. **Confirm the policy copy** `hdfc-bank-in-manual-card-page`: that your 2026-10-30 terms review stands for page
   class `card_page`. (Nothing staged under it should be relied on until you do.)
2. **Decide the card draft** — `proposal:hdfc-infinia:snapshot:hdfc-infinia-card-page:…` (5 fields, no value
   changes): `inspect`, then `decision … --curator-id <you> --action approve|edit|reject --expected-version 1`.
3. **Decide the valuation draft** — `proposal:infinia-portal-val:snapshot:hdfc-infinia-card-page:…` (1 field, no
   value change).
4. **Decide whether to `confirm-origin`** for that capture (document class `card_page`) so approved evidence can
   count; without it every row keeps `needs_verification=true`.
5. **Which captures to make or point us to** (section 6), starting with the two that move this trip most: the
   HDFC and Axis fees-and-charges documents (forex markup and tax are the largest unverified inputs to the Singapore
   spend).
6. **Representation decisions** for the lounge entitlement, the portal earn multiplier and the redemption cap
   (section 7), and hand the welcome-offer and program-identity requirements to the acquisition track.

`needs_verification` was not cleared anywhere, and no decision was run as the owner.

## 10. Verification

Execution mode: real CLI processes, real SQLite, real stored data copied from the untouched originals (re-hashed
afterwards: unchanged), the unchanged optimizer, no network. The operator sequence is a local script
(`~/tripwise-ingestion-data/financial-data-readiness-20261106/run-readiness.sh`, not committed: it names the
owner and the page). The `make seed` and unchanged `make gate` outcome for the committed tree is stated in the pull
request.

**Independent review** (one read-only reviewer): confirmed that neither new command can write a fact, record a
decision, clear `needs_verification` or touch a repository seed, and found two Important issues, both fixed with
tests: (1) `network` was reported as not moving the trip although it decides which network-restricted offers apply, so
text facts are now varied with sibling values and anything that cannot be varied is reported *unmeasured*, never
harmless; (2) `readiness` migrated an older ingestion database on open, so it now reads with SQLite `mode=ro` and
refuses a database at another schema version. Minor findings also fixed: ledger evidence is matched by proposal and by
the current value (a stale value does not count), a fact counts as `evidenced` only when its capture's origin is
confirmed, the seed's own "verified" flag is labelled a claim, `review-queue` no longer creates a missing data
directory, and the probe is cross-checked against a direct optimizer run. Accepted limit: a state shows the strongest
of several simultaneous states first and lists the others in its evidence notes.

## 11. Limits

One page, one issuer, two rows: nothing here says anything about other issuers or pages. Influence is measured on
one trip by doubling and halving integers and substituting sibling text values; a fact with no observed effect may
matter for another trip, and facts that cannot be varied (lists, dates, values with no sibling) are reported
unmeasured. The 16 findings are the assistant's reading of the saved page and
should be checked by the owner against it. The draft extraction is assistant-authored from a plain-text copy, so
neither an HTML parser nor a PDF library was exercised on real input.
