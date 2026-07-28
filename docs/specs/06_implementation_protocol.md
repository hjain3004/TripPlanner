# 06 — Implementation Protocol: Self-Review, Decision Authority & Drift Prevention

**Purpose:** this pack was written so the implementing assistant does not need an external architect in the loop. The architect's review is replaced by three things: (1) executable acceptance gates, (2) explicit decision-authority tiers, and (3) a deviation log. Follow this protocol and no design review round-trips are required.

---

## 1. Decision authority tiers

### Tier F-K — KERNEL FROZEN (do not change, do not "improve")

Changing anything here invalidates the golden tests and the cross-doc consistency of the pack. If one of these seems wrong, follow §3 — do not silently fix it.

1. All money as integer minor units; percentages as basis points; per-point values as micro-major units (01 §5). No floats in money paths, ever.
2. Earn semantics: `points per amount`, per-transaction floor, computed on post-instant-discount amount (01 §3, 02 §4).
3. Cap fall-through and shared cap pools (01 §4, 02 §5).
4. Allocation algorithm: regret-ordered greedy + pairwise improvement sweep + deterministic tie-breaking (02 §5). Do not substitute raw-value greedy, do not add randomness, do not add an MILP in MVP.
5. Offer stacking: one offer per stacking_class per line; coupon before bank_offer on the running amount (02 §6).
6. Effective-cost formula and the dual presentation (blended + cash-now/deferred split) (02 §1).
7. The **Kernel MVP** pipeline graph, its four LLM call sites, and their JSON contracts (03 §1–§7). No new call sites or dynamic tool selection inside M1–M3/F1–F4.
8. LLMs never compute money numbers; the explainer groundedness regex gate is mandatory (03 §6).
9. Provenance columns on every fact table; `needs_verification` propagation to the report (01 §1).
10. `backend/core/` never accesses the network. The Kernel MVP pipeline accesses no inventory/reference provider at request time; only its configured LLM may be external. The target application never directly crawls live booking/search pages at runtime.
11. All golden-test expected values in 04. If your implementation disagrees with an expected number, the default assumption is your implementation is wrong (see §4 for the audit procedure).

### Tier F-P — TARGET-PLATFORM FROZEN BOUNDARIES

These become executable in G1+ and must not be used to add live work to an unfinished kernel milestone:

1. All provider I/O goes through the reviewed, profile-eligible allowlist in 09/16; `backend/core/` never imports it.
2. External inventory is ephemeral evidence with provider, retrieval time, expiry, completeness, and visible trust state. It is never silently promoted into an approved KB fact.
3. Target-platform domain "agents" are fixed typed workflows. No dynamic provider/MCP discovery, arbitrary URL fetching, free-form agent delegation, or runtime self-modification.
4. LLMs and the frontend still never compute money or points.
5. Normal CI never calls live providers; adapters use sanitized recorded fixtures and deterministic clocks.
6. Verify-before-transfer remains checklist step 1 for every award recommendation, including fresh live evidence.
7. The platform never executes a booking or points transfer.
8. The active provider profile is `student_noncommercial`: read-only, low-volume, near-zero-cost integrations with honest experimental states and sample fallbacks. `commercial_production` is inactive and requires a full provider/compliance re-review if ever authorized.
9. Flight evidence types never silently promote: cached `FlightPriceObservation` ≠ current cash `FlightQuote` ≠ sandbox/sample fixture ≠ `AwardQuote`. Only the matching evidence class can support its claim.

### Tier C — CONSTRAINED (your choice, within stated bounds)

Decide freely, but record the choice in `DEVIATIONS.md` only if you deviate from the doc's default: SQLAlchemy table naming/typing details; FastAPI project wiring; retry/timeout tuning within 03 §8 bounds; per-diem constants (must be labeled assumptions in output); prompt wording (contracts and hard rules fixed), POI candidate ranking function (must be deterministic); frontend details not otherwise frozen. In G1+, adapter timeout/retry tuning and student-profile experimental labels are Tier C only inside spec 16's bounds.

### Tier V — FREE

Internal function decomposition, file names below the module level, test organization beyond required cases, logging format (keep TraceEvent fields), dev tooling.

## 2. Precedence order for conflicts

Use topic-specific precedence:

- **Kernel numeric behavior:** golden values (04) > 02 > 07 > 01 > 03 > this doc's examples.
- **Product scope and target architecture:** 08 > 09 > 16 > Kernel MVP scope prose in 00/03/05.
- **Frontend/API contract:** 12 > 13 > 14 > 10/11/15.

No product-scope document may silently change a golden number. A discovered conflict is a required `DEVIATIONS.md` entry: quote both passages, state which precedence applies, and explain the decision.

## 3. Ambiguity & suspected-spec-bug protocol

When the spec is silent or seems wrong, do **not** stop and ask, and do not silently improvise. Instead:

1. Make the most conservative choice — the one that changes no Tier-F behavior and no golden number.
2. Log it in `DEVIATIONS.md` at repo root: `{date, doc§, question, decision, rationale, affected_files}`.
3. If the ambiguity would change a golden number, that's Tier F → run the §4 audit; if the audit still says the spec is wrong, implement to the spec anyway, mark the golden test `xfail` with a linked DEVIATIONS entry, and surface it prominently in the milestone report (§5). Never edit an expected value and a fix in the same commit — expected-value edits get their own commit with the audit reproduced in the message.

`DEVIATIONS.md` is the async replacement for architect review: a human (or a later model) can audit every judgment call in one file without replaying the build.

## 4. Numeric disagreement audit (before touching any golden value)

Reproduce the disputed line by hand in the commit message / deviation entry, showing each step: (a) matched rule and why, (b) cap pool state before/after, (c) discount order and caps, (d) points floor arithmetic, (e) valuation path used, (f) forex = amount × markup_bp × (1 + tax_bp/10⁴). Nine times out of ten the discrepancy is one of: forgot post-discount points base, forgot tax-on-markup, ceil instead of floor, pool not shared, coupon/bank_offer order swapped. The worked example in 02 §8 was computed step-by-step to be internally consistent; treat it as ground truth unless the hand audit proves an arithmetic error in the spec itself.

## 5. Self-review gates (replaces "show results for review")

Run at the end of each milestone; all boxes checked = proceed without external review. Emit `reports/milestone_N.md` containing the checklist output, test summary, and any DEVIATIONS added.

**Gate M1:** `pytest evals/ -k optimizer` green (all ≥12 golden files); `python -m core.optimizer demo` output diff-identical to the 02 §8 table (commit the canonical output as a fixture and assert byte equality); determinism check (two runs, identical bytes); property tests green; `mypy --strict core/` clean; a grep audit: no `float` in money paths (`grep -rn "float" core/optimizer core/models.py` reviewed line-by-line, findings justified in the report); every Pydantic model in 01 exists with all fields.

**Gate M2:** end-to-end demo trip via `POST /plan` < 60s, FinalReport schema-valid; planner referential-integrity tests green on recorded fixtures; groundedness regex gate implemented **and covered by a test that feeds a deliberately hallucinated number and asserts rejection**; fail-soft paths exercised by tests (kill each LLM node via a fake that always errors → assert the documented fallback, not a 500); intake fixture suite green; TraceEvents written and schema-valid.

**Gate M3:** LM-judge anchors ranked correctly; golden itineraries mean ≥ 4.0, groundedness = 5; provenance warnings render for a seeded `needs_verification` fact (test with one); report footer disclaimers present (03 §9); `evals/report.md` generates.

**Gate A1 (accounts persistence, spec 17 §1–3, §5–6):** `mypy --strict accounts/` clean; **a test walks `core/`'s AST and asserts zero `accounts` imports** — the boundary is proven, not assumed; a test asserts that running `core.db.seed_database` twice leaves the accounts tables intact (this is the `drop_all` hazard, and it must be exercised rather than reasoned about); no account model declares a name in `FORBIDDEN_FIELD_NAMES` **and** constructing one with `pan=…` raises; `add_revision` twice yields revisions 1 and 2 with revision 1's stored bytes unchanged; the `UserWallet` projection is order-independent and does not double-count a pooled points currency; `delete_user` cascades and is idempotent; the pre-existing backend suite passes unchanged with an empty `git diff -- evals/golden/`.

**Gate A2 (accounts auth, spec 17 §4):** `mypy --strict accounts/ api/` clean; `grep -rn "localStorage\|sessionStorage" api/ accounts/` returns **nothing**; no stored row and no response body contains a plaintext password, an Argon2 hash, or a raw session token (assert by test, not by inspection); the session cookie carries `HttpOnly`, `Secure`, and `SameSite`; the CSRF cookie is deliberately *not* `HttpOnly`, and a state-changing request missing the matching header returns 403; wrong-password and unknown-email logins return byte-identical responses; logout revokes server-side such that a subsequent authenticated call returns 401; `delete_user` removes credentials and sessions.

Gates A1 and A2 are also restated task-by-task inside their implementation plans (`docs/superpowers/plans/2026-07-28-accounts-*.md`). Where a plan and this section disagree, this section wins.

## 6. Anti-drift rules for multi-session implementation

1. Start every session by reading `DEVIATIONS.md` and the latest `reports/milestone_N.md` — not by re-reading all specs and re-deciding.
2. Never refactor Tier-F behavior "while you're in there." Behavior changes and refactors are separate commits; golden tests must be green between them.
3. Adding any feature not in the specs requires a DEVIATIONS entry tagged `SCOPE+` — default no. Features in 08/09/16 are in target-prototype scope but cannot be pulled into M1–M3/F1–F4 without an explicit human reprioritization and deviation entry. Booking/transfer execution remains no in every phase.
4. Do not require commercial licences, SLAs, affiliate approval, or production scale for the active student profile. Conversely, never carry a student-profile provider approval into commercialization without the separate spec 16 commercial review.
5. If context is lost mid-milestone, the gates are the recovery mechanism: run the milestone gate; whatever fails is exactly what remains.

## 7. The short list of things that DO require asking the human

Only these: (a) a Tier-F spec bug confirmed by the §4 audit (implement-to-spec + xfail first, then ask); (b) anything requiring a paid service or credentials; (c) legal/compliance wording changes to the disclaimers; (d) replacing seed data placeholder values with real verified values (human verification is the point); (e) publishing/deploying anywhere public; (f) changing the operating profile to commercial. Free anonymous read-only provider research/spikes inside spec 16 do not require a commercial-access discussion. Everything else: decide, log, proceed.
