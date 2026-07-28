# Handoff — remaining spec work (2026-07-28)

Cold-start context for finishing the three-spec pass from `~/.claude/plans/ok-so-i-want-majestic-hamming.md`.
Read `DEVIATIONS.md` and `docs/specs/06_implementation_protocol.md` first, per CLAUDE.md.

## Done this session

- **`docs/superpowers/plans/2026-07-28-accounts-persistence.md`** — full 10-task TDD implementation plan for `backend/accounts/`. Not started.
- **`docs/specs/05_ingestion_pipeline_phase2.md`** — revised. Added Stage 0 (Discovery), the `DiscoveryCandidate` model, per-corridor seed aggregators, the ToS gate, component 0, and three new non-goals.

## Remaining

### 1. Revise `docs/specs/01_data_model.md` — network tiers

Additive only. Decisions already made — do not re-litigate:

- **`Card.network_tier: str | None`** — new optional field in §3. Suggested `Literal["infinite","signature","world_elite","world","platinum","centurion","reserve"] | None`, default `None`. Optional means no seed row and no golden expected value changes.
- **New `NetworkBenefit` entity** keyed by `(network, network_tier, country)`, carrying the standard `Provenance` block like every other fact. Fields: lounge program + visits, golf, hotel-collection status, travel insurance summary, concierge — each `str | None` or `int | None`.
- **The Tier-F risk is resolved, not deferred.** `NetworkBenefit` entitlements are **report-only** and **never enter the offer stacking order** (02 §6). Precedent: 01 §3 already treats `lounge_intl_visits_per_year` as "stored for report color; not optimized in MVP." This makes the addition provably additive — the frozen stacking order (`coupon` first, then `bank_offer`, one per `stacking_class`) is untouched and zero golden values move.
- **Network-*targeted offers* stay as `Offer`.** `Offer.networks` already exists (01 §6) and already stacks. Optionally add `Offer.network_tiers: list[str] | None` (None = any tier) — additive, does not change stacking order.
- Clean separation to state in the spec: **network-targeted promo = `Offer`** (stacked, optimized); **tier entitlement = `NetworkBenefit`** (report-only, never optimized).

Verification: `cd backend && .venv/bin/python -m pytest` must stay at 97 passing with no expected-value edits. `git diff --stat -- backend/evals/golden/` must be empty.

### 2. New `docs/specs/18_card_acquisition_and_welcome_offers.md`

**Number 18, not 17** — 17 is reserved for `accounts_and_persistence` and is referenced by name throughout the persistence plan. Renumbering would break it.

The feature: surface that a card the user does *not* hold has a welcome bonus that would materially improve this trip's economics.

Content to cover:

- **The higher-value, lower-risk half first:** for a card the user *already holds*, detect an **active** welcome window from `WalletEntry.opened_on` (spec 17) and surface "43 days left to hit the ₹X minimum spend — putting the flights here clears it." This needs no application, no eligibility guessing, and no advice framing. Specify it before the new-card case.
- **`CardAcquisitionOffer` model** with `Provenance`: bonus points/value, `min_spend_minor`, `spend_window_days`, `expected_approval_to_card_days`, eligibility exclusions (e.g. "not held in prior 24 months"), annual fee, fee-waiver conditions.
- **Deterministic math only** (non-negotiable #1): `net_first_year_benefit_minor = welcome_bonus_value_minor + trip_earn_delta_minor − annual_fee_minor`, integer minor units throughout. The LLM copies these numbers, never generates them.
- **The timing gate** — the suggestion is suppressed unless the trip's bookable spend falls *after* expected card arrival *and* inside the min-spend window. Most naive versions of this feature get this wrong and recommend a card that cannot arrive in time.
- **Facts the system cannot know must be stated as unknown, never assumed:** credit score, income, existing issuer relationships, prior-product history.
- **Non-goals (hard):** no application submission, no pre-qualification API, no credit checks, no affiliate/referral links (consistent with the new spec 05 non-goal), no "you will be approved" claims, and never ranked above the strategy built from cards already held.

### 3. Index and log updates

- `docs/specs/00_README_BUILD_PLAN.md` — add rows for 17 (mark pending/reserved) and 18 to the documents table; the line "17 spec docs" at §Repo layout and the `docs/specs/` comment both need the new count.
- `DEVIATIONS.md` — add rows for: the spec-05 discovery revision (including *why* `aggregator_hint` was rejected in favour of a separate `DiscoveryCandidate` type), the spec-01 additive network-tier revision, and the new spec 18.
- `CLAUDE.md` + its identical `AGENTS.md` copy — build order and checkpoint sections need these slotted in with a gate per spec 06 §5. **Both files must stay byte-identical.**
