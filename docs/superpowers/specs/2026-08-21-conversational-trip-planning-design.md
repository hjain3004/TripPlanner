# Conversational Trip Planning and Preference Memory

**Date:** 2026-08-21

**Status:** Human-approved architectural design; implementation not started

**Operating profile:** `student_noncommercial`
**Relationship to existing architecture:** This design surrounds the frozen Kernel MVP. It does
not change deterministic money/points behavior, golden values, the four Kernel LLM call sites, or
provider safety rules.

## 1. Problem

The current product collects trip facts through a five-step form, asks for interests as a short
comma-separated list, submits one request, and generates a plan. If intake needs clarification,
the frontend renders a static list and sends the user back to the review form. After generation,
F5/F5.1 support valuable deterministic itinerary edits, but there is no multi-turn planning
conversation.

That interaction is not sufficient for the target product. A sophisticated travel planner must
understand trade-offs that travelers rarely express in one form: trip purpose, daily rhythm,
flight tolerance, hotel-location preferences, food priorities, mobility needs, downtime,
cash-versus-points preferences, and which choices are hard constraints versus suggestions.

The product must therefore become an **interview-first conversational planning workspace**. It
asks a bounded set of useful questions before planning, confirms what it understood, and then
keeps the conversation available beside the generated itinerary for refinement.

## 2. Product decisions

The following decisions were made explicitly with the project owner:

1. The system asks questions before generating any itinerary or searching travel providers.
2. The intake is conversational and covers the whole trip: flights, hotels, itinerary, food,
   accessibility, budget, cards, points, and optimization priorities.
3. The interface combines natural-language messages with quick replies, multi-select chips,
   sliders, date controls, and optional free text. It is not a disguised static form and is not a
   text-only chat box.
4. A short fixed backbone guarantees essential coverage. Deterministic branching adds only
   contextually relevant follow-ups.
5. A normal interview contains approximately 8–12 short decisions.
6. Every nonessential question offers `No preference — choose for me`.
7. A reviewable summary and explicit `Build my trip` confirmation are mandatory before planning.
8. Stable preferences live in a visible, editable user profile. Trip-specific choices live with
   the planning session and saved trip.
9. When a trip answer conflicts with a saved preference, the user chooses `This trip only` or
   `Update my profile`; the system never silently promotes an inference into memory.
10. The LLM is used where semantic understanding adds real value. Cost control governs when it is
    invoked; it does not reduce the experience to rigid rules.
11. The deterministic interview engine remains authoritative. The LLM may select from an approved
    question catalog and personalize wording, but it may not invent state fields, provider tools,
    calculations, or unbounded questions.

## 3. Goals and non-goals

### Goals

- Make planning feel like working with a thoughtful travel advisor rather than completing a form.
- Gather enough information to materially tailor the complete trip before spending provider or
  planning budgets.
- Reuse confirmed profile preferences without repeatedly interrogating the traveler.
- Preserve a deterministic, inspectable source of truth beneath the conversational presentation.
- Use LLMs for ambiguity, nuance, conflict detection, tailored follow-ups, itinerary synthesis,
  critique, and explanation.
- Keep the interview useful during LLM/provider outages and keep external spend at USD 0 under the
  active profile.
- Allow post-plan natural-language refinement while routing ordinary edits through the existing
  zero-LLM deterministic recompute path.
- Make every profile update, provider re-query, broad replan, and expensive prose refresh explicit.

### Non-goals

- A free-roaming autonomous agent that invents questions, tools, workflows, or providers.
- Calling an LLM for every button/chip response merely to make the UI appear intelligent.
- Voice input, voice output, avatars, or human-agent role-play in the first implementation.
- Silent behavioral profiling from clicks or inferred preferences.
- Storing hidden chain-of-thought, raw provider responses, credentials, or bank/loyalty passwords.
- Booking, paying, transferring points, or performing any irreversible action.
- Replacing the deterministic optimizer, transfer pathfinder, evidence rules, or money arithmetic.

## 4. Architecture

```text
User profile defaults
        |
        v
PlanningSession + deterministic InterviewPolicy
        |                       \
        |                        -> bounded LLM InterviewAssistant
        v
Confirmed structured TripBrief
        |
        v
Target orchestrator
  -> flight / hotel / award / itinerary workflows
  -> provider gateway (only after confirmation)
        |
        v
Frozen deterministic kernel
        |
        v
FinalReport + conversational planning workspace
        |
        -> typed edits / scoped replans / explicit profile updates
```

### 4.1 Module boundaries

The exact filenames are Tier V, but the responsibilities are fixed:

- **Accounts preference store:** owns durable, user-approved travel defaults. It follows spec 17's
  isolated mutable-data boundary; `backend/core/` never imports it.
- **Planning session store:** owns mutable pre-plan interview state, conversation events, confirmed
  briefs, and links to generated revisions. It is separate from immutable `SavedTrip` and
  `TripRevision` snapshots.
- **Question catalog:** declares approved topics, answer contracts, presentation controls,
  prerequisites, profile mappings, skip behavior, and impact domains.
- **Interview policy:** deterministically selects required questions, evaluates branching rules,
  prevents repetition/cycles, enforces the decision ceiling, and decides when the LLM checkpoint
  is due.
- **Interview assistant:** a separately specified target-platform LLM call site. It interprets
  bounded free text, detects contradictions, and proposes catalog question IDs and personalized
  wording through a strict typed contract.
- **Trip Brief assembler:** deterministically creates the reviewable canonical brief from profile
  defaults and confirmed session answers.
- **Conversation intent router:** maps post-plan messages into typed edits, scoped replans,
  clarifications, explanations, or profile-update proposals. Deterministic matches run first; an
  LLM is used for semantic interpretation when needed.
- **Impact/invalidation engine:** determines which domains must be recomputed or re-queried after a
  confirmed change. The LLM cannot decide invalidation.
- **Frontend conversation workspace:** renders server-authored conversation events and typed
  controls. The server remains authoritative; no local/session storage is introduced.

### 4.2 Frozen-kernel compatibility

The Kernel MVP continues to have exactly four LLM call sites: intake, planner, critic, and
explainer. The interview assistant is an explicitly specified target-platform layer outside the
Kernel graph. It does not alter money math or golden behavior.

After confirmation, the structured `TripBrief` is serialized deterministically into the existing
intake boundary unless a future human-approved Tier-F change introduces a typed equivalent. The
current intake call therefore remains present rather than being silently bypassed. Provider
gateway integration remains outside `backend/core/`.

## 5. Conversational interview

### 5.1 Fixed backbone

The interview covers these decisions in a natural order:

1. **Trip essentials:** origin, destination, dates or flexibility, travelers.
2. **Purpose and party:** leisure, work, celebration, family, solo, couple, group, and relevant
   companion constraints.
3. **Budget and optimization:** total/rough budget, flexibility, cash conservation, points usage,
   and whether the objective is lowest cash, highest value, convenience, or a balance.
4. **Flights:** cabin, stops, schedule tolerance, baggage, airport flexibility, and important seat
   preferences.
5. **Stay:** lodging style, neighborhood priorities, room/bed requirements, location-versus-price,
   and hotel-program preferences.
6. **Daily rhythm:** pace, mornings/evenings, downtime, transit tolerance, and day-trip appetite.
7. **Experiences:** interests, food, iconic-versus-local balance, nightlife, shopping, nature,
   culture, and indoor/outdoor preferences.
8. **Hard constraints:** accessibility, dietary requirements, immovable events, exclusions, and
   anything the planner must never assume away.

Profile-backed answers are presented for confirmation rather than silently skipped. Several
closely related fields may be answered by one conversational control, so the 8–12 target counts
decisions, not database columns.

### 5.2 Adaptive follow-ups

After the backbone has enough information, the interview policy prepares compact structured state
for the LLM assistant. The assistant returns:

- a short acknowledgement grounded in supplied answers;
- zero or more approved `question_id` values, ranked by expected planning impact;
- personalized wording for the selected question;
- normalized candidates for any pending free-text answers;
- detected contradictions referencing exact answer IDs;
- no calculations, provider calls, or invented schema fields.

The policy validates every returned question ID, removes answered/inapplicable topics, applies the
8–12-decision budget, and selects at most one next question for display. A contradiction consumes a
follow-up slot only when resolving it can change the plan.

The normal live path **requires one adaptive LLM review**. A second interview call is permitted
only for unresolved free text or a material contradiction. The hard pre-plan interview ceiling is
two LLM calls. If the LLM is unavailable, the session records a degraded-assistance diagnostic and
continues with deterministic catalog branches; it must not pretend the adaptive review occurred.

### 5.3 Mandatory confirmation

The final review is deterministic and editable. It separates:

- trip facts;
- stable profile defaults being applied;
- trip-only preferences;
- cards, points balances, and optimization objective;
- skipped decisions and `choose for me` delegations;
- unresolved contradictions and material assumptions;
- pending profile-update proposals.

`Build my trip` remains disabled until required facts and explicit hard-constraint acknowledgement
are complete. Confirmation freezes a versioned `TripBrief` snapshot. Later changes create a new
brief/revision; they never rewrite the confirmed historical snapshot.

No Gondola, Tripadvisor, flight, hotel, award, routing, or other live provider search may occur
before this confirmation. Tests enforce the boundary with transports that raise on any early call.

## 6. Profile preference memory

### 6.1 Visible durable preferences

The profile page exposes editable groups for:

- home country, currency, and usual origin airport;
- preferred cabin, seat, stop, schedule, baggage, and airport flexibility;
- hotel style, room needs, location priorities, and loyalty programs;
- typical pace, daily rhythm, downtime, transit tolerance, and day-trip appetite;
- activity, food, shopping, nightlife, nature, and culture preferences;
- dietary and accessibility requirements;
- usual cash-versus-points and convenience-versus-value priorities.

Card products and points balances continue to use the wallet projection from spec 17 rather than
being duplicated in the preference model.

### 6.2 Consent and provenance

Each durable preference records at minimum its value, update timestamp, and source category:
`user_profile_edit` or `user_confirmed_from_trip`. `llm_inferred` is never a durable source value;
an inference remains a pending proposal until the user confirms it.

When an answer differs from a saved preference, the conversation asks:

- `Use for this trip only`; or
- `Update my profile`.

Profile changes are explicit account mutations with the existing authentication, CSRF, privacy
export, and account deletion guarantees. The profile UI lets users inspect, edit, reset, or remove
every stored preference without starting a trip.

## 7. Planning-session state and persistence

A `PlanningSession` is mutable and server-owned. Its conceptual state includes:

- session/user ID, version, created/updated/expiry timestamps;
- status: `interviewing`, `reviewing`, `confirmed`, `planning`, `complete`, `failed`, or `abandoned`;
- current approved question ID and progress estimate;
- structured answers, skips, applied profile values, and confirmation state;
- user-visible conversation events;
- LLM-call count and assistance diagnostics;
- pending profile mutations;
- confirmed versioned `TripBrief` snapshots;
- generated plan/revision reference;
- post-plan edit/replan events and domain invalidations.

Optimistic version checks reject stale double submissions. Answer submission is idempotent through
a client-generated event ID. A session can resume across devices after authentication.

Abandoned unsaved sessions expire after 30 days by default and are deleted by the accounts/storage
layer. A session attached to a saved trip follows that trip's retention and deletion behavior.
Privacy export includes visible conversation events and structured answers. Hidden prompts,
chain-of-thought, secrets, and raw provider responses are never persisted as conversation data.

## 8. API and contract direction

Exact route names may change during the implementation plan, but the public capabilities are:

1. Create a planning session using profile defaults.
2. Read/resume the current session state.
3. Submit a typed answer, skip, or optional free-text response with an expected session version.
4. Receive the next user-visible conversation event and structured control contract.
5. Amend the reviewable Trip Brief.
6. Confirm the brief and start the planning job exactly once.
7. Read planning progress and the completed report.
8. Submit a post-plan message and receive a typed proposed action.
9. Confirm any provider-invalidating replan or profile mutation.
10. Read and mutate visible profile preferences.

Schema, OpenAPI snapshot, generated frontend types, runtime validation, MSW fixtures, frontend
consumers, and contract tests ship together under the existing one-PR rule.

The conversation API returns structured events such as `assistant_question`, `user_answer`,
`assistant_acknowledgement`, `brief_review`, `action_proposal`, `clarification`, `system_progress`,
and `error`. The UI never parses prose to discover state or decide which control to render.

## 9. G3.4 and provider integration

The original G3 plan's G3.3 section—disabled registry selection and standalone fallback proofs—is
already implemented on the Gondola branch. Production `/plan` and product-contract integration is
G3.4. Existing reports that call the missing production wiring “G3.3” contain a naming drift that
must be corrected when those documents are next updated.

G3.4 should consume a confirmed `TripBrief` rather than hardening the current one-shot form as the
permanent product boundary. Provider workflows remain reusable independently of this interview.

Provider invalidation is deterministic. At minimum:

| Confirmed change | Domains invalidated |
|---|---|
| Destination or dates | Flight, hotel, award, itinerary, cost, card/transfer strategy |
| Travelers or occupancy | Flight, hotel, award, itinerary capacity, cost, card/transfer strategy |
| Cabin, stops, airport, flight schedule | Flight and relevant award evidence, then dependent cost |
| Hotel style, room, area, loyalty preference | Hotel and itinerary-area fit, then dependent cost |
| Interests, food, pace, accessibility | Itinerary and affected cost lines only |
| Wallet, points balance, optimization objective | Award/card/transfer/kernel outputs; inventory only if its request semantics changed |

The system shows the impact and requests confirmation before any repeated live-provider calls.
Unchanged evidence remains reusable only within its licence, cache, and freshness rules.

## 10. Post-plan conversational workspace

Chat remains visible beside the itinerary rather than replacing it. The itinerary, map, flights,
hotel, points strategy, and payment recommendations remain first-class visual artifacts.

Post-plan messages resolve into typed intent classes:

- `deterministic_edit`: move, remove, reorder, add, or replace an activity;
- `scoped_itinerary_replan`: change pace, rhythm, interests, area balance, or a day theme;
- `provider_invalidating_change`: dates, destination, travelers, cabin, hotel requirements, or
  other search semantics;
- `wallet_or_objective_change`: cards, balances, or optimization priorities;
- `explanation_request`: explain an existing computed decision without recomputing it;
- `profile_update_proposal`: suggest a durable preference update;
- `clarification_required`: ask one focused question rather than guessing.

Known UI actions map directly to typed operations with zero LLM calls. Natural language first runs
through deterministic matching; semantic interpretation uses at most one cheap-model call for that
message. The resulting typed proposal is displayed before broad replans or provider-invalidating
changes. Money/card/transfer recomputation remains deterministic. Prose refresh remains explicit.

## 11. LLM use and cost contract

### 11.1 Required semantic work

The LLM is not ornamental. It is required in the normal experience for:

- interpreting nuanced optional free text;
- identifying contradictions and missing high-impact preferences;
- choosing and wording contextually relevant catalog follow-ups;
- itinerary synthesis across qualitative trade-offs;
- critic review of soft feasibility and unsupported claims;
- grounded natural-language explanation;
- semantic routing of post-plan requests that deterministic matching cannot resolve.

It is prohibited from owning session state, inventing durable preferences, doing arithmetic,
selecting arbitrary tools/providers, deciding cache invalidation, or initiating external actions.

### 11.2 Budgets and model routing

- Pre-plan interview: one required adaptive call; maximum two calls.
- Structured UI responses: zero calls.
- Kernel planning: existing bounded call sites and provider-invocation ceiling remain unchanged.
- Post-plan typed controls: zero calls.
- Post-plan free-text interpretation: maximum one interpreter call per message, with a configurable
  per-session ceiling and deterministic controls remaining available after exhaustion.
- Prose refresh: explicit user action only.
- All roles use provider-agnostic configuration. Cheap/free-tier models are preferred for
  extraction, routing, and acknowledgements; a stronger configured model may be reserved for
  itinerary synthesis.
- Repeated identical semantic requests within the same session revision reuse validated results.
- Model inputs contain compact structured state and only the relevant recent message, not an
  ever-growing transcript.
- The `student_noncommercial` USD 0 out-of-pocket rule remains binding. Positive spend fails
  closed; free-tier exhaustion degrades to deterministic controls rather than silently billing.

Normal automated development uses recording/replay clients. Live LLM and provider acceptance is
manual, bounded, read-only, secret-safe, and never required by CI.

## 12. Failure and safety behavior

- **LLM interview failure:** record `assistance_status=degraded`, use deterministic catalog
  branching, and disclose that tailored follow-ups were unavailable. Do not fake an LLM review.
- **Invalid LLM question ID or schema:** reject it, consume no unbounded retry, and fall back to the
  deterministic next question.
- **Contradictory answer:** ask one focused clarification. Never silently select a side.
- **Stale answer submission:** return the current session version without duplicating events.
- **Provider failure after confirmation:** preserve the confirmed brief and return the existing
  honest fallback/partial evidence state.
- **Post-plan ambiguity:** present the interpreted change for confirmation or ask a question; do
  not mutate the confirmed plan based on a guess.
- **Profile-write failure:** keep the trip-only answer and report that the default was not updated.
- **Prompt injection in user/provider text:** user text is data under the assistant contract;
  provider text retains existing sanitization and never controls questions or tools.
- **Session expiry:** tell the user before destructive expiry where feasible; saved confirmed
  briefs/revisions follow account retention rather than ephemeral-session retention.

## 13. UX and accessibility requirements

- One primary question at a time, with visible approximate progress such as “About 6 of 10.”
- Keyboard and screen-reader access for every quick reply, slider, date control, edit, and
  confirmation action.
- Minimum 44×44 px touch targets and no horizontal overflow at the existing mobile gate.
- Focus moves to each new question and announcements use a polite live region; progress messages
  must not spam assistive technology.
- `No preference — choose for me`, `Back`, and `Review answers` remain available.
- Profile-derived answers are visually distinguishable and editable.
- The mandatory confirmation clearly distinguishes facts, preferences, assumptions, and profile
  changes.
- The post-plan conversation and visual plan remain synchronized; the UI never claims a change is
  applied while recomputation is pending.
- The existing light, premium neo-brutalist/retrofuturist design direction remains applicable. Chat
  bubbles must not turn the product into a generic dark AI interface.

## 14. Verification strategy

Passing tests must prove behavior, not merely component presence.

### Deterministic policy

- Exhaustively/property-test catalog branches for cycles, repeats, dead ends, and the normal
  8–12-decision bound.
- Verify all required trip facts and hard-constraint acknowledgement precede confirmation.
- Verify every optional question has a skip/delegation path.
- Verify profile defaults, trip-only overrides, and explicit profile updates remain distinct.
- Verify no provider transport can be invoked before confirmation.

### LLM assistance

- Replay-backed cases where different traveler answers select meaningfully different follow-ups.
- Contradiction cases where the assistant must propose an approved clarification.
- Hostile/free-text cases proving the assistant cannot invent a question ID, profile field, tool,
  number, or provider call.
- A teeth/mutation test replacing the assistant with a no-op must fail personalization acceptance,
  proving the LLM is materially used rather than ceremonially called.
- Call-budget assertions for zero-call structured paths, the required adaptive checkpoint, the
  two-call interview ceiling, and one-call post-plan interpretation.

### Persistence and contracts

- Resume a session across authenticated clients without browser storage.
- Idempotent answer submission and optimistic concurrency conflict tests.
- Privacy export/delete and abandoned-session expiry.
- Forbidden sensitive fields and no account data in inappropriate LLM prompts.
- One-PR OpenAPI/generated-code/MSW/UI contract gate.

### End-to-end product behavior

- Complete interviews for materially different personas and demonstrate different confirmed
  briefs and itineraries.
- Confirm that `Build my trip` is the first possible provider-search boundary.
- Apply simple post-plan edits with zero LLM/provider calls.
- Change dates and prove only the confirmed invalidation path can re-query providers.
- LLM outage, provider outage, free-tier exhaustion, stale quote, and resumed-session scenarios.
- Accessibility across desktop, tablet, mobile, keyboard, screen reader semantics, and reduced
  motion.

## 15. Implementation decomposition and order

This design is too large for one implementation milestone. It is delivered in the following
dependency order:

1. **CP1 — Preference profile and interview domain:** durable visible preferences, question
   catalog, deterministic policy, session/brief contracts, storage, privacy behavior, and policy
   tests. No LLM or provider activation.
2. **CP2 — Conversational session API and pre-plan UI:** resumable interview, typed controls,
   progress, skips, review/amendment, mandatory confirmation, OpenAPI/frontend synchronization,
   and accessibility gates. Deterministic assistant fixtures only.
3. **CP3 — Bounded LLM interview assistance:** strict assistant contract, adaptive checkpoint,
   free-text interpretation, replay corpus, teeth tests, budgets, model routing, and degraded mode.
4. **G3.4 — Confirmed-brief gateway product integration:** production orchestration consumes the
   confirmed brief; Gondola/sample fallback evidence reaches the product contract with provenance.
   This phase must first resolve or conservatively handle the still-unverified successful Gondola
   structured response shapes documented by G3.2.2.
5. **CP4 — Post-plan conversational actions:** intent routing, deterministic edits, scoped
   replanning, invalidation confirmation, profile-update proposals, and synchronized workspace.
6. **CP5 — Acceptance and polish:** cross-persona evals, cost/failure tests, responsive and
   accessibility gates, live bounded smoke where explicitly authorized, and documentation sync.

Every milestone receives its own executable plan, report, code review, and full applicable gate.
No phase may weaken the deterministic kernel or activate positive external spend to unblock itself.

## 16. Success criteria

For a supported trip, an authenticated user can:

1. See and edit stable travel preferences in the profile.
2. Start or resume a conversational interview covering the whole trip.
3. Complete a normal interview in 8–12 decisions, with useful LLM-selected follow-ups and a skip
   path for nonessential preferences.
4. Review exactly what will be planned and explicitly confirm it before any provider search.
5. Receive a plan whose choices materially reflect the confirmed brief.
6. Refine that plan conversationally while ordinary edits remain fast, deterministic, and cheap.
7. Understand when a change will replan, refetch evidence, update the profile, or spend an LLM
   call.
8. Continue with honest degraded behavior when an LLM or provider is unavailable.

The feature is not complete merely because a chat UI exists. Acceptance requires behavioral proof
that the conversation changes the structured brief, the structured brief changes the resulting
plan, LLM assistance improves relevant follow-up selection, and no financial number or external
action escapes deterministic governance.
