# Held-card welcome-window status (spec 18 Case A, backend slice)

**Status:** backend API slice complete and demonstrated. **This is not spec 18 completion**, and
it is not a traveler-facing feature (see "Deferred").

**Base:** `6f0859b` (`origin/main`). **Branch:** `codex/held-card-welcome-status`.
**Worktree:** `/Users/himanshu_jain/.codex/worktrees/held-card-welcome-status/TripPlanner`.
**Pushed / merged:** no. Nothing was pushed, merged, rebased or opened as a PR.
*(As written for the source branch at `31b9823`. It was later merged with FI3 and the PDF
compatibility branch and re-verified as a combined tree; see
`reports/integration_fi3_welcome_pdf.md`. The behavior and limits below are unchanged.)*

Code commits, in order: `2a1ca53` (feature), `246c0b0` (review fixes), `fbbcce5` (packaging and
gate lines), `814de14` (points-bonus valuation fix). This report is the final, docs-only commit.

---

## What works now

A signed-in traveler (API client) can ask, for a card already in their wallet and a trip revision
they saved, where that card's welcome window stands:

`POST /account/wallet/{entry_id}/welcome-status` with `{trip_id, revision, prior_qualifying_spend_minor?}`

The answer reports the window dates and days remaining, the minimum spend and what remains of it,
what the plan's spend on that card could contribute, the offer terms with provenance and
verification status, and a list of assumptions and typed limitations.

Who can do what: an authenticated owner, through the existing cookie + CSRF API. There is no
traveler screen. With the shipped offer data (deliberately empty) every request reports
`status: "unknown"` and `NO_APPROVED_OFFER` — that is the real production behavior today.

### Properties that matter

- **Server-owned amounts.** Trip dates and spend are read from the stored revision's computed
  `optimizer_result`. The request model is `extra="forbid"`; the only client figure is the
  optional prior spend, returned as user-entered and unverified.
- **Unknown stays unknown.** No `opened_on` -> `unknown`, no window. Omitted prior spend -> no
  shortfall (an explicit `0` is a different answer). A future `opened_on` -> `unknown`.
- **Travel dates are not payment dates.** The plan never observes when money moves. No field
  says "qualifying"; the strongest claim is `could_count_if_paid_by_close`, and the amount is
  reported as *conditional*. Lines outside the window, straddling the close, in another currency
  or attributable to either of two entries for one product are not counted, and when spend cannot
  be attributed the trip-dependent conclusions are `null`, not `false`.
- **Offer terms are never invented.** The shipped catalog is empty. A row is usable only if it has
  a source, is not an agent draft and has a human verifier; the loader refuses any `SYNTHETIC*`
  row from the shipped file. If zero or several offers could have applied, none is chosen.
- **A points bonus is never valued by guesswork.** See next section.
- **Read-only, optimizer untouched.** Nothing is written; assignments are not re-run, re-ranked or
  added to; the bonus is not folded into any total. No change to `core/`, `ingestion/`, goldens,
  seeds or the PDF files.
- **Wrong owner = missing.** A foreign wallet entry and a foreign trip each return exactly the body
  of a nonexistent id (tests compare whole responses).

### Points-currency valuation (corrected after review)

The first version valued a points bonus with the card's best valuation row. An independent review
showed an offer naming `some-airline-miles` was valued at the card's INR 1.00/pt portal rate. The
data model cannot establish the link needed to do this honestly: `PointValuation` is keyed by card
only, `EarnRate.currency` is the *spend* currency, and nothing maps a card to a points program.

So a points bonus now returns `bonus_value_minor: null` with the typed limitation
`POINTS_PROGRAM_NOT_ESTABLISHED`, while the stated points, the program id as named, and the offer
provenance are preserved. Flat (cash/voucher) bonuses are their own value and are unchanged. A
points bonus can only be valued once humans curate a verified card -> points-program mapping in the
knowledge base; that data work is outside this slice.

---

## Demonstration (execution mode: real app in-process, real SQLite, scripted LLM, no network)

```bash
cd backend && .venv/bin/python -m evals.demo_welcome_status
```

Signs in with cookie + CSRF, holds two cards, runs the **real planning job** against the seeded
sample KB, saves the trip through `POST /account/trips`, then requests status. Re-run on
`814de14`:

| Scene | Observed |
|---|---|
| Shipped (empty) catalog | `status: unknown`, limitations `NO_APPROVED_OFFER`; trip spend still reported from the stored plan |
| **Synthetic** offer, prior spend 1,200,000 | `active`, opened 2026-10-01, closes 2026-12-30, 67 days left, minimum 5,000,000, shortfall 3,800,000; plan assigns 22,403,200 to the card, all conditional; bonus 10,000 points, program as named, value `null` |
| Unknown inputs | omitted prior spend -> `shortfall_minor: null`; entry with no `opened_on` -> `unknown`, no window |
| Wrong owner | foreign entry and nonexistent entry -> identical `404 WALLET_ENTRY_NOT_FOUND` |

Every offer in the synthetic scenes is **SYNTHETIC test data** (`verified_by: SYNTHETIC_TEST_FIXTURE`,
`example.invalid` source, notes saying so). It states no issuer term.

Evidence class: synthetic fixtures for offer terms; real-library/real-storage local execution for
the plan, API, auth and SQLite. No live provider, credential, spend or LLM was involved.

---

## Contract and mocks

`contract/openapi.json`, the generated client, the `@/lib/api` facade and the MSW mock were
synchronized in the feature commit and re-synchronized when the bonus shape changed. Against the
base snapshot the change is additive only (one path, new schemas; nothing existing changed). The
mock resolves wallet entry, trip and revision against the same stateful mocks as the wallet and
saved-trip routes, returns the same typed 404s, derives lines/counted spend/plan dates from the
stored mock report, and — like the real route with the shipped data — always answers "no approved
offer". It fixes `as_of` and lists fewer assumptions than the real route; that is stated in the code.

---

## Independent review

One independent review of `2a1ca53` (cold brief, read-only). No Critical findings.

| # | Finding | Disposition |
|---|---|---|
| 1 | Unattributable spend (duplicate entries, currency mismatch) made `trip_alone_clears…` a definite `false` and `after_trip` the full shortfall | **Fixed** (`246c0b0`): now `null`; regressions assert it |
| 2 | Prior spend may already include this plan's bookings, double-counting | **Fixed** (`246c0b0`): explicit assumption that it must not |
| 3 | Window close treated as inclusive (optimistic by a day if the open day is day 1) | **Kept**: spec 18 §4 states "on or before window_closes_on"; disclosed in `assumptions` |
| 4 | Pay-at-property hotels are judged as paid at booking | **Kept, disclosed**: stated payment-timing assumption; spend is conditional |
| 5 | Mock disagreed with the real route (lines, counted spend, dates, limitations) | **Fixed** (`246c0b0`) |
| 6 | Points bonus valued with a valuation unrelated to `bonus_currency_id` | **Fixed properly** (`814de14`): see above; the first attempt only disclosed it, which was not enough |

The review did not catch that `pyproject.toml` lacked the new package; the first full-suite run did
(an existing guard test), and it was fixed in `fbbcce5`.

---

## Verification (measured this session)

Backend, `make gate` on the clean committed tree `814de14` (code-identical to the final commit,
which adds only this report):

| Check | Result |
|---|---|
| Backend pytest (`TRIPWISE_REQUIRE_REGIONAL_CATALOGS=1`) | **2758 passed, 1 skipped** |
| mypy `--strict` | clean: 200 files (core/accounts/planning/agents/api/gateway), 19 (ingestion), 4 (welcome) |
| Ruff zero-tolerance (accounts/planning/agents/gateway/evals, ingestion, welcome) | all passed |
| Ruff legacy ratchet (`core/` + `api/`) | **8** (ceiling 12); `api/main.py` has 5 before and after my two lines, `api/welcome.py` has 0 |
| Frozen artifacts / contract / briefs / tree | `GOLDENS_OK`, `CONTRACT_OK`, `BRIEFS_IDENTICAL`, `TREE_CLEAN`, **GATE PASSED** |
| `make seed` | ran before the suite |

Frontend and contract:

| Check | Result |
|---|---|
| `scripts/check-contract-drift.sh` | `CONTRACT_DRIFT_OK` (deterministic export, client in sync) |
| `tsc --noEmit` | exit 0 |
| Vitest | 229 passed (13 files) |
| ESLint | 0 errors, 14 warnings (all in pre-existing files) |
| token-lint | 0 violations across 15 rules |
| Production build | **passes with `next build --webpack`**; the default Turbopack build fails (see limits) |
| no-dead-classes (fresh build) | 0 dead classes |

Packaging: the wheel was built from a scratch copy of the committed backend
(`tripwise_backend-0.1.0-py3-none-any.whl`, about 0.9 MB). It contains `welcome/__init__.py`,
`catalog.py`, `models.py`, `status.py` and `welcome/data/card_acquisition_offers.yaml` (the empty
list), and no synthetic fixture. Importing it with `python -I` and loading the shipped catalog
gives `NO_APPROVED_OFFER`.

Mutation checks (specific guards, not a campaign): making an omitted prior spend count as 0, and
making on-trip lines count regardless of the window, each failed the intended tests.

A final `make gate` on the report commit is recorded in the hand-off message, since this file
cannot state the outcome of a run that has not happened when it is written.

### Failures encountered and how they were resolved

- First full-suite run failed `test_no_stubs::test_planning_is_in_packaging_and_gates`: not disk. My
  edit changed the exact gate command strings the guard matches and `pyproject.toml` did not list the
  package. Fixed by separate gate lines and the packaging entries (`fbbcce5`); the guard is unmodified.
- An earlier gate attempt was interrupted when the session ended during a critically low-disk period.
  Nothing from it is relied on; every number above is from a later complete run.
- `token-lint` flagged a comment containing "404s" as a hardcoded timing; reworded.
- Default `next build` (Turbopack) fails here with `node_modules ... points out of the filesystem
  root`. Cause: to save disk, this worktree's `node_modules` and `.venv` are symlinks to another
  worktree's identical-lockfile install (`a4-saved-trips`), used read-only. This is an environment
  property, not a code defect; webpack builds fine. A normal checkout with its own `node_modules`
  was not exercised.

---

## Deferred / not claimed

- **Traveler UI and report placement.** No screen exists. Spec 18 §6's inline placement in the
  payment strategy, a wallet-card status panel, and prominent entry of `opened_on` / prior spend are
  not built. The browser (Playwright) suite was not run: no UI changed.
- **Case B** (new-card suggestions, timing gate, net-first-year value, application logic): untouched.
- **Real offer data.** The catalog is empty; adding issuer terms needs human verification. Until then
  production reports `NO_APPROVED_OFFER`.
- **Valuing points bonuses** needs a curated, verified card -> points-program mapping in the KB.
- **Not modeled:** issuer-specific excluded spend, posting dates vs transaction dates, day-counting
  conventions, pay-at-property hotel timing. All are stated in `assumptions`.
- **Prior spend** is user-entered and unverifiable; there is no bank linking or transaction import.
- **Wheel** was built and inspected, not installed into a fresh environment or deployed.
- Disk: the worktree uses symlinked environments (above) and a 254 MB ignored `frontend/.next` from
  the verification build.
