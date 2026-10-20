# A3 — Persistent Wallet Product Wiring

**Status:** COMPLETE — review remediation and the final committed-tree gate passed.

**Source/base commit:** `a378d0b0b5e5728912fbbfd7ebceaff8ebb02c66` (`codex/integrate-fi0-g3-5-g4`)
**Branch:** `codex/a3-wallet-product-wiring`
**Worktree:** `/Users/himanshu_jain/.codex/worktrees/a3-wallet-product-wiring/TripPlanner`
**Plan:** `docs/superpowers/plans/2026-10-19-a3-wallet-product-wiring.md`
**Pushed / merged:** no. Nothing was pushed, merged, amended, or rebased.

`origin/main` was `eccb19885557001fec7a87d5b459998dda646e57` when this work started, and is a full
ancestor of the base commit (base is 33 ahead, 0 behind).

---

## What shipped

A signed-in traveler can now see the cards and loyalty balances saved to their account, add a card
by choosing an approved product from the seeded knowledge base, edit the safe metadata, remove an
entry after confirming, and see which wallet conversational planning will use before confirming.
An empty persisted wallet reaches planning as an empty `UserWallet` and produces truthful
cash-only output rather than a substituted demo wallet.

No PAN, expiry, CVV/CVC, PIN, banking credential, or loyalty password is accepted or stored —
those field names are rejected outright rather than ignored.

### Commits, one per plan task

| Commit | Task |
|---|---|
| `d62d26a` | The implementation plan |
| `e54cfca` | 1 — migration-safe `WalletEntry` versioning |
| `f0af25d` | 2 — owner-scoped mutations with versioned CAS |
| `112dcea` | 3 — durable idempotency on `client_event_id` |
| `63abda8` | 4 — eligible card products from the seeded KB |
| `19b0774` | 5 — the authenticated `/account/wallet` API |
| `25b86e4` | 6 — API-to-session projection guarantees |
| `2eb3e7c` | 7 — contract, generated client and MSW synchronization |
| `eccec32` | 8 — the authenticated `/wallet` route |
| `462d37e` | 9 — the projected planning wallet before confirmation |
| `bb1e1ba` | 10 — privacy, concurrency and boundary coverage |
| `ca2bd40` | 11 — the end-to-end browser journey |

### Route family

`/account` prefix, kept separate from the read-only deterministic kernel routes:
`GET /account/wallet`, `GET /account/wallet/projection`, `GET /account/card-products`,
`POST /account/wallet`, `PATCH /account/wallet/{entry_id}`, `DELETE /account/wallet/{entry_id}`.

`UserWallet` remains **derived**. It is folded from stored rows on read and there is deliberately
no endpoint that writes it.

---

## Verification — measured on the final committed clean tree

Every number below was read from a run on this tree, not copied from an earlier report.

| Check | Result |
|---|---|
| `make gate` | **GATE PASSED** (`GOLDENS_OK`, `CONTRACT_OK`, `BRIEFS_IDENTICAL`, `TREE_CLEAN`) on the final committed tree |
| Backend pytest | **1778 passed, 1 skipped** |
| mypy `--strict` (`core accounts planning agents api gateway ingestion`) | clean, **179 source files** |
| Ruff zero-tolerance (`accounts planning agents gateway evals`, and `ingestion`) | All checks passed |
| Ruff legacy ratchet (`core/` + `api/`) | **7** findings, ceiling 12 — unchanged from baseline, **0** in new `api/wallet.py` |
| Frontend `tsc --noEmit` | exit 0 |
| Frontend Vitest | **177 passed** |
| Frontend ESLint | **0 errors** (14 warnings, all in pre-existing files) |
| `token-lint` | 0 violations across 15 rules |
| `no-dead-classes` | 0 dead classes (run against a fresh build) |
| Production build | compiled successfully; `/wallet` prerendered |
| Browser suite (complete, live tests disabled) | **492 passed, 76 skipped**; A3 wallet slice **34 passed, 2 skipped** across chromium / mobile / tablet / reduced-motion |
| OpenAPI byte-stability | regenerated twice → identical SHA-256, and identical to the committed artifact |
| Generated client byte-stability | regenerates byte-identically; `git status` stays empty afterwards |

**Baseline comparison.** Before Tasks 3–6 the branch stood at 1722 passed / 1 skipped and mypy
clean over 177 files. The backend grew by 55 tests (12 idempotency, 9 card products, 15 API,
8 projection, 6 privacy, 4 concurrency, 1 boundary) and 2 source files (`accounts/cards.py`,
`api/wallet.py`). Frontend Vitest grew from 163 to 176.

The 2 A3 browser skips are the header link below 960px; see "Open findings". The first complete
browser run exposed three CP3 fixture failures because the A3 session contract added required
`wallet` data; the shared CP3 fixture was synchronized and the complete rerun passed.

---

## Findings worth recording

**Two genuine security defects were found and fixed, not hypothetical ones.** Before A3, both
`set_points_balances(entry_id, …)` and `remove_wallet_entry(entry_id)` resolved a row by primary
key alone (`session.get(WalletEntryRow, entry_id)`) with **no owner predicate**. Nothing exposed
them yet, but any caller holding an entry id could have mutated or deleted another user's card.
Both are now owner-scoped, and a wrong-owner failure is deliberately indistinguishable from a
missing entry so the API cannot be used to probe for another user's entry ids.

**An ordering trap in the idempotency path.** In `update_wallet_entry` the replay check must run
*before* the existence and stale-version checks. A retry of an update that already succeeded
necessarily carries the *original* `expected_version`, which is stale by then; checking staleness
first would reject precisely the retry idempotency exists to absorb.

**A second ordering trap in error mapping.** All three typed wallet errors subclass `ValueError`,
as do the model validators. The broad `ValueError` arm in `api/wallet.py::_handle` has to come
last, or a genuine 404 or 409 would be reported as a 422.

**A data-model gap in the knowledge base.** The plan specified a `points_currency_id` on the card
product listing. It was **dropped**, because the seeded KB cannot populate it truthfully:
`Card.base_earn.currency` is the *spend* currency (`INR` for all four seeded cards),
`PointValuation.currency` is the currency a valuation is denominated in, and loyalty currencies are
`LoyaltyProgram` ids referenced by `TransferEdge` (`voyager-prime` → `lionmiles`) that **no `Card`
row references**. `voyager-prime` is a seeded `card_currency` program nothing points at, so the
card→points-currency relationship is modelled nowhere. Shipping the field permanently null would
have invited a frontend affordance that can never populate.

**The session snapshots its wallet.** `create_session` calls `_profile_for_user` once and passes
the result to `start_interview(..., wallet=wallet)`; it is persisted in the session payload
(`planning/contracts.py`) and carried into the brief (`planning/brief.py`). It is **not re-derived
per request**. The review step therefore renders `SessionOut.wallet` — the session's own copy —
rather than `GET /account/wallet/projection`, which could otherwise promise cards that
confirmation would not actually price.

**Task 6 required no implementation change.** All eight API-to-session boundary tests passed on
first run. Recorded as verification, not repair, so a later reader does not assume the coverage
implies a fixed defect.

**The baseline was broken and was repaired, not excused.** On a fresh worktree `make seed` fails
because the Makefile invokes bare `python`, which is not on PATH, and the gitignored regional
catalogs are absent. Before repair: 54 failed / 1623 passed / 5 errors. The Makefile was **not**
edited; `make seed PY=.venv/bin/python` and the already-approved catalog artifacts were used
instead, and the catalogs remain ignored and untracked.

---

## Open findings and limitations

1. **`/wallet` has no mobile or tablet navigation entry point.** The header nav block is
   `max-[960px]:hidden` in the approved composition, so "Your wallet" — like the pre-existing
   "Plan a trip" and "How it works" — is only reachable from the header at ≥960px. The wallet
   *page itself is responsive*: every other browser test passes at 390px and 768px. Adding a
   mobile affordance means changing the approved header composition for all three nav items, which
   is a visual-design decision outside A3.
2. **A wallet edited mid-interview does not update a running planning session.** The divergence is
   now visible (the review step shows the session's wallet, which is the truthful value) but it is
   not reconciled. Surfacing or resolving it is future work.
3. **No card→loyalty-currency mapping exists in the KB** (see above). Until one does, points
   balances remain keyed by user-entered currency ids.
4. **`set_points_balances` is owner-scoped but not CAS-protected.** It reads the current version
   and immediately writes, so it gives no concurrent-edit protection. The API deliberately uses
   `update_wallet_entry` with an explicit `expected_version` instead; the wrapper is retained for
   internal callers and tests.

---

## Scope confirmations

Verified by diff, not assertion:

- No change to Tier-F optimizer or transfer arithmetic, and no golden expected value changed
  (`GOLDENS_OK`, `BRIEFS_IDENTICAL`).
- `docs/specs/` untouched.
- CP4, FI1/crawler work, and spec 18 card acquisition not started.
- No live provider activated — Gondola, Tripadvisor, Open-Meteo and every other MCP remain
  disabled. No credentials or paid services used.
- No bank linking, transaction import, statement parsing, booking, payment, or transfer execution.
- No account identity, `last4`, or private wallet metadata sent to an LLM.
- `backend/core/` imports nothing from `accounts/`, `gateway/`, `ingestion/`, or `api/` — now
  enforced by a test, where previously only the `accounts` direction was.
- No `localStorage` or `sessionStorage` anywhere under `frontend/src/`.
- The legacy unauthenticated `/plan` fixture path is unchanged: `TripSpec.wallet` remains a
  required caller-supplied field with no server-side default.
- No other worktree was modified or cleaned. The source worktree remains at `a378d0b` with a clean
  tracked tree.

---

## Deviations

Roughly 30 judgment calls are recorded in `DEVIATIONS.md` under the A3 sections for tasks 1–11,
including three corrections to the plan itself (errors co-located in `store.py` rather than a new
`errors.py`; `points_currency_id` dropped; the `now` parameter removed from
`update_wallet_entry`) and two test corrections where the test, not the code, was wrong.

---

## Review closure

- The fresh independent whole-branch review found no Critical findings. Four Important findings
  were verified and fixed with regression coverage: additive migration of the pre-A3 accounts
  schema; preservation of hidden point balances during compact card edits; durable
  `client_event_id` values on all frontend mutations; and explicit projection/card-product
  read-failure states instead of a false cash-only result.
- The review's three Minor findings are dispositioned as follows: generated error-response
  declarations remain a non-blocking contract-documentation gap because runtime typed errors are
  already decoded defensively; card-product seeding remains an approved seeded-environment
  precondition; and invalid-card validation before a conflicting create replay remains a harmless
  invalid-input ordering edge, not a successful mutation or data-loss path. These are recorded,
  but do not alter A3's authenticated wallet correctness boundary.
- The exact-tree backend gate passed on the clean remediation commit. This report status is now
  COMPLETE; a final post-documentation gate will be run after this closure commit as required.
