# Handoff — remaining spec work (2026-07-28)

Cold-start context for finishing the three-spec pass from `~/.claude/plans/ok-so-i-want-majestic-hamming.md`.
Read `DEVIATIONS.md` and `docs/specs/06_implementation_protocol.md` first, per CLAUDE.md.

## Done this session

- **`docs/superpowers/plans/2026-07-28-accounts-persistence.md`** — full 10-task TDD implementation plan for `backend/accounts/`. Not started.
- **`docs/specs/05_ingestion_pipeline_phase2.md`** — revised. Stage 0 (Discovery), the `DiscoveryCandidate` model, per-corridor seed aggregators, the ToS gate, component 0, three new non-goals.
- **`docs/specs/01_data_model.md`** — revised, additively. `Card.network_tier` (optional), new §3.1 `NetworkBenefit`, `Offer.network_tiers` (optional), index and seed-size notes.
- **`docs/specs/18_card_acquisition_and_welcome_offers.md`** — new.
- **`docs/specs/00_README_BUILD_PLAN.md`** — documents table rows for 17 (pending) and 18; spec-doc count corrected.

Verified after the spec-01 revision: `cd backend && .venv/bin/python -m pytest` → **100 passed**, and `git diff --stat main -- backend/evals/golden/` empty. The additive claim holds.

> **Correction to a stale number:** `CLAUDE.md`'s current-checkpoint section says the backend regression is 97 tests. It is **100**. The count moved before this session (nothing here touched `backend/`). Use 100 as the baseline; fix `CLAUDE.md` when you next edit it.

## Remaining

### ~~1. `DEVIATIONS.md` — log the three spec changes~~ — DONE (`265d7fb`)

### ~~2. `CLAUDE.md` + `AGENTS.md`~~ — DONE. Build order carries specs 17/18; checkpoint dated 2026-07-28; regression baseline recorded as 100 with the M3 historical 97 left intact; both files re-verified byte-identical.

### ~~3. `docs/specs/17_accounts_and_persistence.md`~~ — DONE. Written after the plan and authoritative over it. Adds what the plan deferred: Argon2id credentials in a **separate `UserCredential` table** (not a column on `User`), server-side sessions with an `httpOnly`/`Secure`/`SameSite` cookie storing only a token hash, CSRF requirements, and the privacy/retention section. The plan has been annotated with the refinement.

### 4. Remaining: execute the persistence plan

`docs/superpowers/plans/2026-07-28-accounts-persistence.md`, 10 tasks, via `superpowers:subagent-driven-development`. **Not started, and deliberately so** — the human's instruction was specs and plan docs only.

### ~~5. An auth plan~~ — DONE

`docs/superpowers/plans/2026-07-28-accounts-auth.md`, 8 tasks. Implements spec 17 §4. **Hard dependency: the persistence plan must be complete and Gate A1 passing first** — it extends `accounts/models.py`, `accounts/db.py` and `AccountStore`.

Two things in it that a reviewer should check rather than skim: `authenticate()` returns `User | None` with no reason, and burns a dummy Argon2 verification when the user is absent or locked, so login is not a user-enumeration oracle by response body *or* by timing. And the CSRF cookie is deliberately **not** `httpOnly` — that is the double-submit pattern working as intended, not an oversight.

It also fixes a gap in the persistence plan: `delete_user`'s cascade must grow to cover `user_credentials` and `sessions`, marked ⚠ in Task 5.

## Nothing further is planned

Both remaining plan docs exist. All work from here is execution, which the human has explicitly reserved.

---

## Superseded (kept for the audit trail)

### 1. `DEVIATIONS.md` — log the three spec changes

Rows needed (six-column format, new `## Specs — accounts, discovery, network tiers` section):

- **Spec 05 discovery.** Record *why* `aggregator_hint` was rejected as a `Provenance.source_type` member in favour of a separate `DiscoveryCandidate` type with no `Provenance` block: adding it to the `Literal` would let every KB row carry a hint provenance and reduce the invariant to a runtime check on a type that permits the bad state. This is a deliberate departure from the brainstorm plan's stated approach.
- **Spec 01 network tiers.** Additive: `NetworkBenefit` is report-only and never enters the Tier-F stacking order, with precedent in 01 §3's treatment of `lounge_intl_visits_per_year`. Verified: 100 tests still pass, golden diff empty.
- **Spec 18.** New spec ahead of its dependency (17), same process inversion as the persistence plan. Case A (held-card welcome window) is specified as shippable independently of Case B.

### 2. `CLAUDE.md` + `AGENTS.md` — build order and checkpoint

Slot specs 17/18 into the build order with a gate per spec 06 §5, and correct the 97 → 100 regression count. **Both files must stay byte-identical.**

### 3. Still unwritten: `docs/specs/17_accounts_and_persistence.md`

The persistence plan builds ahead of it (logged SCOPE+). Spec 17 owes: the auth/session approach, privacy and retention policy, and the parts of the entity model the plan did not cover. When written, it wins over the plan's code.

### 4. Not started: executing the persistence plan

`docs/superpowers/plans/2026-07-28-accounts-persistence.md` is ready to run via `superpowers:subagent-driven-development`.

## Uncommitted and deliberately left alone

`frontend/design/probes/` — 6.4 MB of design-probe binaries (2.5 MB traced SVG, source JPEGs, PNG screenshots). Wikimedia sources are CC BY-SA and need attribution before they go in the repo. `frontend/design/pipeline/posterize.py` likewise untracked.
