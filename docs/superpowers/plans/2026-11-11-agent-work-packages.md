# Agent work packages: backend and change feed

**Date:** 2026-11-11 (second version: roles and spend corrected by the owner)
**Base for every task:** latest `origin/main` (reviewed at `a9efea0`).
**Companion plan:** `docs/superpowers/plans/2026-11-11-travel-change-feed.md`.

## 1. How this is organised

Work is split by the way the owner uses each agent.

| Role | Agents | Does | Does not |
|---|---|---|---|
| Design | Claude Opus, ChatGPT Sol | Decides open questions in a short design note. Reviews finished pull requests. | Write or edit code. |
| Core | Gemini Argon | Writes the load-bearing part: types, signatures, the one or two hard functions, and an acceptance test that defines done. Leaves the rest as marked seams. | Fill in routine code. |
| Build | Claude Sonnet, Gemini Flash, ChatGPT Luna | Fills the seams, wires everything up, makes the acceptance test pass, passes the gate. | Change the design silently. |
| Labor | Kiro | Mechanical checklists. | Make design decisions. |

Each stream runs Design, then Core, then Build, then Review. A step is skipped where it adds
nothing. To start a task, paste three things in order: the **common preamble** (section 3), the
**role add-on** (section 4) and the **task prompt** (section 7).

**Spend rule.** The USD 50 of Claude API credit is for the deployed site only. No agent makes a
paid API call during development or testing. Model behaviour is checked with scripted or recorded
clients, or with the existing free-tier provider (`HostedFreeTier`). The Claude client is checked
against the real API once, by the owner, on deployment day (stream G).

## 2. Step 0, before any agent starts (owner)

**1. The instruction files forbid this work.** `CLAUDE.md` and `docs/specs/06` on `main` freeze
"the pipeline graph and its four LLM call sites" and set a USD 0 spend ceiling, and they tell
agents that specs win. An agent asked to skip the intake call will refuse or "implement to spec
anyway". Add the section below to the top of `CLAUDE.md` and `AGENTS.md` (the two files must stay
identical). Edit it first; the lines marked `CONFIRM` are your decisions.

```markdown
## Owner decisions (2026-11-11)

These supersede anything older in this file, in DEVIATIONS.md and in docs/specs/.

1. Spend. USD 50 of Claude API credit and USD 150 of AWS credit exist for the deployed site only.
   No agent makes a paid API call in development or testing. Use scripted or recorded clients, or
   the existing free-tier provider. Any other paid service needs my approval.
2. Runtime LLM. In production the Claude API, behind the existing LLMClient protocol, is the
   provider, with hard spend caps enforced in code.
3. Pipeline. This replaces spec 06 section 1, Tier F-K item 7. A request that already carries a
   valid TripSpec skips the intake call. The critic call is off by default and can be turned on by
   configuration. The planner and explainer call sites and every JSON contract are unchanged. The
   new model roles in docs/superpowers/plans/2026-11-11-travel-change-feed.md are allowed.
4. Still frozen. Money arithmetic, golden expected values and provenance fields. A model never
   computes or alters a money value. No model or agent writes to core/seeds/ or the knowledge base.
5. Real data. Agents may prepare proposals with evidence through the ingestion review path. Only I
   approve and apply them.
6. Sources. Daily Drop, The Points Guy and point.me are never fetched automatically. Every other
   source needs a SourcePolicyRecord before its first fetch.
7. Deployment. One AWS instance, one replica. CONFIRM: private demo, or public?
8. CONFIRM: the project remains non-commercial.
9. Roles, tasks and file ownership are in
   docs/superpowers/plans/2026-11-11-agent-work-packages.md.
```

**2. Agents cannot see these files yet.** This file, the change-feed plan and
`backend/scripts/loadtest/` are untracked in the primary checkout, which is on a stale branch.
Agents work in fresh worktrees from `origin/main`. Commit the three additions and the `CLAUDE.md` /
`AGENTS.md` change on a branch from `origin/main` and merge it before starting.

## 3. Common preamble (paste first, for every role)

```text
You are working in the TripPlanner repository. Create a fresh git worktree on a new branch from the
latest origin/main. Do not work in, or modify, any other worktree or branch.

Read first, in this order:
1. CLAUDE.md. The section "Owner decisions (2026-11-11)" overrides older text and the specs.
2. docs/superpowers/plans/2026-11-11-agent-work-packages.md: your task and what your stream owns.
3. docs/superpowers/plans/2026-11-11-travel-change-feed.md, if your stream is C, D, E, I or J.
4. Only the code your task names. Do not re-read every spec or old report.

Rules for every task:
- Money arithmetic, backend/evals/golden/ and provenance fields do not change. A model never
  computes or alters a money value. Nothing writes to core/seeds/ or the knowledge base without the
  owner's recorded approval.
- Make no paid API call. To exercise a real model use the existing free-tier provider
  (HostedFreeTier) if a key is configured; otherwise use scripted or recorded clients and say so.
- Never fetch a website that has no SourcePolicyRecord allowing it.
- Touch only what your task names. If you need a change elsewhere, make the smallest one and list it.
- Add no dependency, service or framework that your task does not name.
- Open one pull request to main. Do not merge it.

Report back in this order:
1. What a traveler or operator can do now that they could not do before (for a design note: what
   is now decided).
2. The exact command you ran to show it, and its output.
3. What is still missing or unproven.
4. What you changed outside your task, and why.
5. What you need from the owner.
Do not report line counts, test counts or coverage.

If you are blocked by something only the owner can decide (a credential, a website's terms,
approving a financial fact), stop and ask one specific question. For anything else, take the
conservative option, record it in DEVIATIONS.md and continue.
```

## 4. Role add-ons (paste second)

**Design (Opus, Sol)**

```text
Your role is design. Do not write or edit code.

Read the code your task names, then write one design note at the path given. Keep it to two pages.
For each numbered question give a decision and the reason in one or two sentences. Give interfaces
as signatures. End with what could go wrong and the acceptance check the builders must pass.
Do not restate the plan or describe the existing code at length. Where the code contradicts this
prompt, trust the code and say so. Where a question is really the owner's to answer, say that and
give your recommendation. Open a docs-only pull request.
```

**Core (Argon)**

```text
Your role is the load-bearing core. Read your stream's design note first and follow it; if you
think it is wrong, say so in the pull request and do not silently diverge.

Deliver three things:
1. The types and function signatures for the stream.
2. The hard functions your task names, fully working.
3. An acceptance test that defines done for the whole stream. Mark it xfail(strict=True) so the gate
   passes now and fails as soon as the builders finish without removing the marker.

Leave everything else as a seam: a function that raises NotImplementedError with one line saying
what belongs there. List every seam in the pull request description. `make gate` must pass.
```

**Build (Sonnet, Flash, Luna)**

```text
Your role is build. Read your stream's design note and the core pull request first.

Fill the seams, wire the feature through the real application, make the acceptance test pass and
remove its xfail marker. Run the real workflow early, before building around it; fix what actually
fails, then rerun. Follow the design. If it is wrong or incomplete, say so in the pull request and
do not silently diverge.

Finish with `make gate` passing from a clean tree. It needs backend/.venv and the regional catalogs.
If the catalogs are missing, say so; do not call a catalog-less run "the gate".
```

**Labor (Kiro)**

```text
Your role is a mechanical task. Follow the checklist exactly and in order. Make no design
decisions. If a step is ambiguous, or a command fails in a way the checklist does not cover, stop
and report what happened. Do not improvise.
```

**Review (Opus, Sol; never the same vendor as the author)**

```text
Your role is review. Review pull request <number> against its task in
docs/superpowers/plans/2026-11-11-agent-work-packages.md and its stream's design note.

Check out the branch and run the task's "Done when" command yourself. Do not rely on the pull
request description.

Look for, in this order:
1. Any change to money arithmetic or to backend/evals/golden/.
2. Any path by which model output reaches a money value, core/seeds or the knowledge base.
3. Any paid API call, or any model call that bypasses the spend ledger and its caps.
4. Any fetch that is not gated by a source policy.
5. Departures from the design note that the author did not declare.
6. Claims in the author's report that no command output supports.
7. Ordinary defects: a concrete input or state that produces a wrong result or a crash.

Report each finding with file and line, a concrete failure scenario, and how serious it is, most
serious first. If you find nothing, say so plainly. Do not ask for style changes, do not add tests
and do not push to the branch. One review per pull request.
```

## 5. Who does what

| Stream | Design | Core (Argon) | Build | Labor (Kiro) | Review |
|---|---|---|---|---|---|
| A Runtime LLM: fewer planning calls, Claude in production | Opus | A-core | Sonnet (A-build-0, A-build-1), Luna (A-build-2) | none | Sol |
| B Concurrency | Sol | none | Sonnet | none | Opus |
| C Change-feed foundation | Sol | C-core | Flash (C-build-1), Luna (C-build-2) | none | Opus |
| D Feed run: triage, extraction, command | covered by C-design | D-core | Flash | none | Sol |
| E Real corridor data | Opus | none | Sonnet | E-labor | owner approves facts |
| F Allocator benchmark | none | F-core | Luna | none | Opus |
| G One AWS instance | none | none | none | G-labor | Sol |
| H Sign-in and saved-trip screens | none | none | Luna | none | Opus |
| I For you: match and impact | Opus | I-core | Sonnet | none | Sol |
| J Leads and the Corroborator | Sol | J-core | Flash | none | Opus |

Each stream owns these paths; nothing else changes without being declared.

| Stream | Owns |
|---|---|
| A | `agents/pipeline.py`, `agents/llm.py`, `agents/config.yaml`, `agents/confirmed_trip.py`, new `agents/claude_client.py`, `agents/llm_budget.py`, `agents/llm_factory.py`, `get_llm` and the body of `plan` in `api/main.py`, `api/runtime_config.py`, `contract/`, generated client and mocks, the wizard submit handler |
| B | `api/job_manager.py`, the three places a plan job is dispatched, `gateway/places/adapters/snapshot.py`, `deploy/nginx/`, `agents/trace.py`, `agents/retrieval.py` |
| C, D, J | `backend/ingestion/**`, new `backend/feed/` queries, `api/feed.py`, the `/feed` page |
| E | a test seed fixture and the test wiring that points at it, staged captures, proposals, two documents |
| F | new files under `backend/evals/` and `reports/` |
| G | `deploy/**` except `deploy/nginx/default.conf` rate-limit lines owned by B, `docs/DEPLOYMENT.md` |
| H | new frontend routes |
| I | `backend/feed/match.py`, `impact.py`, `writer.py`, new golden files |

## 6. Order

| When | Opus | Sol | Argon | Sonnet | Flash | Luna | Kiro |
|---|---|---|---|---|---|---|---|
| Start | A-design | C-design | F-core | A-build-0 | C-build-1, first pull request | H-build | E-labor, part 1 |
| Next | E-design | B-design | A-core, then C-core | A-build-1 | C-build-1, second pull request | A-build-2, then F-build | E-labor, part 2 |
| Then | reviews, I-design | reviews, J-design | D-core | B-build, then E-build | D-build | C-build-2 | G-labor |
| Last | reviews | reviews | I-core, then J-core | I-build | J-build | spare | spare |

Argon has six core tasks in a row and is the bottleneck. A-core is the smallest; if Argon falls
behind, give A-core to Sonnet with the design note.

Two ordering rules. B-build starts only after A-build-2 has merged, because both change how `plan`
starts a job. E-build's seed pinning must merge before any real card value exists anywhere.

## 7. Task prompts (paste third)

### Stream A: runtime LLM

**A-design (Opus)**

```text
Task A-design. Write docs/superpowers/specs/2026-11-11-runtime-llm-design.md.

Context, measured on origin/main a9efea0 (backend/scripts/loadtest/README.md): a plain plan makes
four model calls and sends about 33k characters of prompt: intake 3.0k, planner 12.4k, critic 15.8k,
explainer 1.5k. The wizard (frontend/src/app/plan/page.tsx, handleSubmit) and the confirmed brief
(agents/confirmed_trip.py) already hold structured data, turn it into text, and the intake call
parses it back. The critic re-checks what core/itinerary/compose validates, and when it fails the
plan is treated as passed. The only runtime client, HostedFreeTier in agents/llm.py, speaks the
OpenAI chat-completions format. Production will use the Claude API; development never pays for it.

Read: agents/pipeline.py, agents/llm.py, agents/intake.py, agents/critic.py,
agents/confirmed_trip.py, api/main.py (plan, get_llm), api/confirmed_planning.py,
gateway/weather/budget.py (the ledger pattern to copy).

Decide:
1. How a structured request enters: an optional trip_spec on TripIntakeRequest, or something else.
   Which deterministic checks from agents/intake.py still run.
2. How the confirmed-brief path builds its TripSpec without a model, and what becomes of
   validate_confirmed_intake.
3. What "critic off" means precisely: the stage order, which composer warnings become caveats, and
   how the existing critic replays and tests stay valid.
4. Provider selection by environment: scripted, recorded, free tier, Claude. Model per role. What
   the app does when nothing is configured.
5. The spend ledger: its table, how cost is computed from reported usage, and three caps (per run,
   per day, lifetime). What happens to a request already in flight when a cap is reached.
6. One limiter shared by all concurrent jobs, and what happens on HTTP 429.
7. A response cache for temperature-0 calls: key, scope and lifetime. Requests contain traveler
   text, so say where cached content may live.
8. How the Claude client is verified with no development spend: tests against documented response
   shapes, plus one owner-run call on deployment day. Say what that call must prove.

Done when: Argon and two builders can start from the note without asking you anything.
```

**A-core (Argon)**

```text
Task A-core. Implement the pipeline change and the interfaces for stream A.

Write in full:
- In agents/pipeline.py: a request that carries a valid TripSpec skips run_intake but still runs the
  deterministic intake checks; free-text requests behave exactly as today. A critic switch read from
  agents/config.yaml, off by default; with it off the order is planner, estimator, kernel,
  explainer, and composer warnings still reach the report as caveats.
- The direct construction of a TripSpec from a confirmed brief in agents/confirmed_trip.py.

Leave as seams, with signatures from the design note: agents/claude_client.py,
agents/llm_budget.py (ledger, caps, shared limiter), agents/llm_factory.py, the response cache, and
the contract and frontend change.

Acceptance test, using a scripted client that counts calls per node: a request with trip_spec makes
two calls (planner, explainer); a free-text request makes three with the critic off and four with
it on; the report for the same inputs is identical with and without the intake call.

Watch for: recorded replays under backend/evals/recorded are keyed by a hash of the prompt text the
caller passes. Do not change the wording of existing prompts.
```

**A-build-0 (Sonnet), needs no design; start immediately**

```text
Task A-build-0. Two small fixes in HostedFreeTier.complete_json in agents/llm.py. Touch nothing else.

1. The `if tools:` branch rebuilds the system prompt from `system` and throws away the JSON-schema
   instruction added just above it. Append to the existing prompt instead. The planner is the only
   caller that passes tools, and it is the node that fell back to the deterministic composer in the
   recorded live smoke. If a free-tier key is configured, run one plan before and after and say
   whether the planner still falls back. If no key is configured, say the check was not run.
2. Fall through to the next configured model on HTTP 429 as well as 404.

Add a focused test for each.

Done when: both tests pass, the gate passes, and your report states plainly whether the fallback
question was answered or not.
```

**A-build-1 (Sonnet)**

```text
Task A-build-1. Fill these seams from A-core: agents/claude_client.py, agents/llm_budget.py,
agents/llm_factory.py. Then point get_llm in api/main.py at the factory, validate the new variables
in api/runtime_config.py and document them in backend/.env.example and deploy/.env.example.

Before writing the client, read the current Claude API documentation at platform.claude.com/docs:
Messages API, model ids, JSON or structured output, prompt caching, usage fields, rate-limit
headers. Do not rely on memory for any of these.

The client must match HostedFreeTier where it matters: schema-validated output, the planner's
"itinerary or search intent" case, redacted errors, no key in any log.

You make no call to the Claude API. Test the client against a fake transport that returns the
documented response shapes, including an error, a rate limit and a malformed body. Prices are
configuration, not constants.

You may add the official `anthropic` package and regenerate the lockfile, or use the standard
library as HostedFreeTier does. Say which and why.

Done when: a cap set to zero stops a call before any request is built; two plans started together
share one limiter; with no provider configured the app starts and a plan fails with an honest
message; and your report says in one line that the client is untested against the real API until
the deployment-day check in stream G.
```

**A-build-2 (Luna)**

```text
Task A-build-2. Finish stream A's remaining seams after A-core has merged.

1. Add the structured request field to the API exactly as the design note specifies. The contract,
   the generated client and the mock fixtures change in this same pull request;
   evals/test_contract_one_pr.py enforces that.
2. Make the wizard send the structured TripSpec. Free-text entry keeps working.
3. Implement the response cache from the design note. It is disabled under tests.
4. Remove the xfail marker from A-core's acceptance test.

Done when, using the fake LLM and BENCH_PROMPT_LOG in backend/scripts/loadtest: a wizard plan logs
two calls and a free-text plan logs three; and the goldens are untouched.
```

### Stream B: concurrency

**B-design (Sol)**

```text
Task B-design. Write docs/superpowers/specs/2026-11-11-concurrency-design.md.

Context, measured on a9efea0 with one worker (backend/scripts/loadtest/README.md): 100 simultaneous
plans push status-poll p95 to 18 seconds; 300 drop 56 connections at 1.6 GB and 341 threads; 25
simultaneous requests on a cold catalog cache kill the process, because each cold request loads the
catalog itself at about 300 MB. /plan/recompute tops out near 10 requests a second.

Read: api/job_manager.py, the three places a job thread is started (plan in api/main.py,
api/confirmed_planning.py, api/saved_trips.py), accounts/store.py (start_planning_job and the
durable job rows), gateway/places/adapters/snapshot.py, agents/retrieval.py, deploy/nginx.

Decide:
1. A bounded worker pool and queue: sizes, and what a caller gets when the queue is full.
2. Durable owned jobs commit a row before dispatch and are idempotent on a start event. Say exactly
   what state such a job is in when it is queued, refused, or the process dies while it waits.
3. Eviction of finished anonymous jobs: time limit and cap.
4. Loading each catalog once under concurrency, and a memory budget: six regional catalogs at about
   300 MB each do not fit a 2 GB instance. Say which stay loaded.
5. Where unauthenticated request limits live: the proxy, the app, or both.
6. Whether the per-request full-catalog sort in agents/retrieval.py should become an index built
   once, and what that does to recompute throughput.
7. Target numbers for the load test on the deployment instance size.

Done when: one builder can implement it without asking you anything.
```

**B-build (Sonnet), after A-build-2 has merged**

```text
Task B-build. Implement docs/superpowers/specs/2026-11-11-concurrency-design.md.

Rerun the baseline in backend/scripts/loadtest/README.md yourself first, on your machine, so your
before and after numbers come from the same hardware.

In short: one submit method on the job manager backed by a bounded pool and queue, replacing the
three unbounded thread starts; refusal with 503 and Retry-After when full, creating no job;
eviction of finished anonymous jobs; one load per catalog under concurrency; request limits for
unauthenticated POST /plan and /places/search; a sweep of old trace files; and the retrieval index
if the design calls for it.

Done when the same load test shows the targets in the design note: no dropped connections at 300
simultaneous plans, the excess refused quickly, the cold start with 25 surviving, and memory back
at its starting level after the eviction time. Put the before and after table in your report.
```

### Stream C: change-feed foundation

**C-design (Sol)**

```text
Task C-design. Write docs/superpowers/specs/2026-11-11-change-feed-design.md. It covers streams C
and D.

Read section 5 to 7 of the change-feed plan, then: backend/ingestion/contracts.py, diff.py,
snapshots.py, extraction.py, storage.py, migrations.py, policy.py, and on branch
codex/firecrawl-ingestion: acquisition_control.py and extraction_runtime.py.

Decide:
1. Event identity: exactly what goes into the event_id hash so the same change detected twice is
   one event, and how a correction supersedes an earlier event.
2. The typed terms for transfer_bonus, welcome_offer and earn_rate_change: fields and units. Amounts
   are integer minor units or basis points.
3. How subjects resolve to knowledge-base ids, and what an unmapped event may and may not do.
4. The two lanes: when a published event also opens a ChangeProposal for human review.
5. Storage: the review queue's SQLite file or a separate one, and the migration.
6. Changed blocks: how normalized text is cut into blocks, how much context each carries, and how
   rotating banners and timestamps are kept from producing a block every night.
7. The Triage and Extractor contracts: inputs, outputs, and what happens to a field whose quote is
   not found at the stated offsets.
8. The nightly run as a sequence of resumable steps: what is recorded after each, and what a rerun
   after a crash does.
9. Which model client the roles use in development (free tier or scripted) and in production.

Done when: Argon can write the contracts and the builders can write storage and the run command
without asking you anything.
```

**C-core (Argon)**

```text
Task C-core. No model calls and no fetching.

Write in full, in backend/ingestion/:
- events.py: ChangeEvent, the three typed terms blocks, EventImpact, and event_id.
- One deterministic validator per event type: dates in order, basis points in a sane range, every
  subject resolved or marked unmapped.
- In diff.py, the function that returns changed blocks with context, as the design note specifies.
  Keep the existing SnapshotDiff fields so current callers are unaffected.
- The additions to PageKind and DiscoveryCandidate.kind listed in the plan.

Leave as seams: event storage (put, get, list, retract), the migration, and the feed queries.

Acceptance test: two versions of a fixture page produce the expected changed blocks; a hand-built
event from them is stored, stored again without creating a duplicate, listed and retracted; and
`python -m ingestion.review_server check-config` still passes.
```

**C-build-1 (Flash), two pull requests**

```text
Task C-build-1.

Pull request 1, needs no design; start immediately. codex/firecrawl-ingestion is 14 commits ahead
of main and does not merge cleanly as of a9efea0. Bring it onto current main, resolve the conflicts
without dropping behaviour from either side, and pass the gate. Change nothing else. In your report
list each conflicted file and how you resolved it.

Pull request 2, after C-core has merged. Fill the storage and migration seams exactly as the design
note specifies, and remove the xfail marker from C-core's acceptance test.

Done when: pull request 1 passes the gate with the Firecrawl demo command still working, and pull
request 2 passes C-core's acceptance test.
```

**C-build-2 (Luna), after C-build-1's second pull request**

```text
Task C-build-2. Anyone can open a page and read this week's changes.

Read-only access to the events store. No model calls and no fetching at request time.
- backend/feed/: queries over published events.
- api/feed.py: GET /feed (published only; filter by type, programme and date; paginated) and
  GET /feed/{event_id}. The signed-in endpoint belongs to stream I.
- The contract, generated client and mock fixtures change in this same pull request.
- A /feed page: a plain list. Each item shows type, programmes, dates, a source link, when it was
  first seen and its verification label (lead only, confirmed at source, reviewed), using the
  existing trust chip. Include an empty state.

Done when: five fixture events stored through the storage API appear on the page in live mode, not
mock mode, with working source links; and a retracted event disappears.
```

### Stream D: the feed run

**D-core (Argon), after C-core and A-build-1**

```text
Task D-core. The Triage and Extractor roles and the skeleton of the nightly run, as the change-feed
design note specifies.

Write in full:
- The role contracts and prompts. Triage reads one changed block and answers whether it is a rewards
  change and of which type. The Extractor fills the typed terms; every field carries a verbatim quote.
- The check, in plain code, that each quote is in the snapshot at the stated offsets. A field that
  fails is dropped, never guessed.
- The run as resumable steps: refresh due targets, diff into blocks, triage, extract, validate,
  deduplicate, publish, and open a linked ChangeProposal where the design says so.

Fetched text is untrusted. These roles get no tools.

Leave as seams: the command-line interface, ledger wiring, the escalation from the small model to
the larger one, the timer, and the prompt-injection tests.

Acceptance test, with a scripted client: replaying two snapshots of one fixture page emits the
correct event; an unchanged page makes no model call; a response whose quote is not in the snapshot
yields no field.
```

**D-build (Flash)**

```text
Task D-build. Fill D-core's seams.

1. `python -m ingestion.feed run | list | show | retract`.
2. Route every model call through the budgeted client from stream A.
3. Add the existing prompt-injection fixture as a test for each role.
4. The extractor has never run with a real model on a real page. If a free-tier key is configured,
   run FinancialExtractor in its AUTHORIZED_CLIENT mode on the Axis Atlas capture retained from the
   Firecrawl pilot (reports/firecrawl_ingestion.md, section 5) and compare the output field by field
   with the curator-authored result from the same pilot. If that capture is on the owner's machine
   and not in the repository, ask the owner for it; do not scrape the page again. If no key is
   configured, say the check was not run.
5. Give the owner a timer definition and a grading sheet for a seven-night unattended run.

Done when: D-core's acceptance test passes without its marker, `feed run` on fixture snapshots
publishes an event that `feed list` shows, and your report states what the real-model check found
or that it was not run.
```

### Stream E: real corridor data

**E-labor (Kiro), two parts**

```text
Task E-labor, part 1. Collect what websites say about automated access. Record; do not judge.

For each site in the list below, read exactly three things: /robots.txt, the terms-of-use page, and
the page that links to it. One plain read per page. Wait at least 11 seconds between reads on the
same domain. Use the user agent "TripWise-source-permissions-research/1.0 (student project; reads
public terms and robots.txt only)". No login, no retries, no JavaScript. If a site answers with a
block or a challenge, record the status code and stop for that site.

Sites: the four issuers already in reports/card_bank_source_permissions.md (HDFC, Axis, SBI Card,
ICICI), Singapore Airlines KrisFlyer, Air India's loyalty programme, and The Points Guy.

For each site write one row in docs/research/change_feed_source_facts.md: the three URLs, the date
read, the robots.txt rules that apply to general agents, and every sentence in the terms containing
any of these words, quoted exactly: automated, robot, spider, scrape, crawl, copy, reproduce,
database, commercial, personal use. Do not write a verdict and do not store any other page text.
```

```text
Task E-labor, part 2, after E-design. Stage captures for the cards and programmes the owner
approved, exactly as the E-design note lists them. For a page marked automated, run the acquire
command given in the note. For a page marked manual, do nothing and add it to a list for the owner
to save by hand. Then stage each saved file with the stage-capture command given in the note.
Report the list of staged captures and the list waiting on the owner.
```

**E-design (Opus)**

```text
Task E-design. Two outputs.

1. reports/change_feed_source_permissions.md. Kiro has collected the raw clauses in
   docs/research/change_feed_source_facts.md. Give each source a verdict in the same form as
   reports/card_bank_source_permissions.md: automated allowed, manual only, or do not use. Where a
   clause is ambiguous, quote it, say it is ambiguous and leave the decision to the owner. State
   that this is a reading of public terms, not legal advice. Daily Drop is already decided as
   manual leads only. End with a draft of about 25 watch targets (URL, page kind, verdict, check
   frequency) that the owner can approve or strike line by line.

2. docs/superpowers/specs/2026-11-11-real-data-rollout.md. Decide:
   a. Which eight to ten cards and which corridor programmes and transfer relationships to verify
      first, and why. The seeds today hold four placeholder cards and three invented programmes
      (lionmiles, skyorchid, grandstay). The owner confirms the list.
   b. How to protect the tests before any real value exists. Recorded replays are keyed by a hash of
      the prompt text, and the intake prompt embeds the card catalog (agents/intake.py,
      _card_catalog), so one new card changes those keys; other tests read core/seeds directly. Say
      where a pinned copy of the placeholder seeds lives and how tests are pointed at it.
   c. The exact commands for capture, staging, extraction, review, bundle, dry-run, apply and
      rollback, in order, for one card. Apply has only ever run against scratch seeds.
   d. What the owner must check before approving a fact.

Done when: Kiro can stage captures and Sonnet can pin the seeds from the note alone.
```

**E-build (Sonnet)**

```text
Task E-build. Two pull requests.

Pull request 1: pin the test seeds as docs/superpowers/specs/2026-11-11-real-data-rollout.md
specifies. This is a refactor only. Run the gate before the change and after it; both must pass, and
no golden file or recorded replay may change. Move the three invented programmes into the fixture.

Pull request 2, after the owner has approved a card list and Kiro has staged captures: run
extraction on each staged capture and produce insert or update proposals with quotes in the review
queue. Use the free-tier provider or the curator-authored mode; make no paid call. You do not
approve anything. After the owner has recorded decisions in the review tool, build the bundle,
dry-run it, apply it to the real seeds and confirm that rollback restores the previous state.

Done when: a plan for a wallet holding one of the real cards shows that card's rules with the
owner's reviewer id and a source link in its provenance, and the coverage command lists exactly
which facts are still unverified.
```

### Stream F: allocator benchmark

**F-core (Argon), needs no design; start immediately**

```text
Task F-core. The allocator in core/optimizer/allocate.py is a regret-ordered greedy pass followed by
a pairwise improvement sweep. It is a heuristic, and nothing measures how good it is. Do not change
the allocator or any golden file. If it loses, that is a finding for the owner.

Write in full, in backend/evals/allocator_benchmark.py:
- A naive baseline: the best option for each line on its own, ignoring that lines share caps, with
  the caps then applied in line order.
- An exhaustive oracle for small trips (up to about eight lines): enumerate every assignment and
  keep the best feasible one. Use the kernel's own option and commit functions so the arithmetic is
  identical, and the same objective the allocator ranks by. If the oracle optimises a different
  objective, the comparison means nothing; show in a test that on a one-line trip all three agree.

Leave as seams: the seeded case generator and the report writer.

Acceptance test: on the existing golden cases in backend/evals/golden, the oracle is never worse
than the allocator.
```

**F-build (Luna)**

```text
Task F-build. Fill F-core's seams.

1. A seeded, deterministic case generator covering exhausted caps, shared cap pools, rounding
   boundaries, offers with minimum transaction sizes, per-card use limits and negative forex cases.
2. A report at reports/allocator_benchmark.md, regenerated by one command from a seed: the share of
   cases where the allocator matches the oracle; the size of the gap when it does not, in minor
   units and basis points; the gain over the naive baseline; and run time.
3. For the cases the allocator loses, the smallest one written out line by line so a reader can
   check it by hand.

Report the numbers as they come out. Do not tune the generator to make the allocator look better.

Done when: one command regenerates the report from a seed.
```

### Stream G: one AWS instance

**G-labor (Kiro), after A-build-1**

```text
Task G-labor. Prepare deployment files and a runbook for one small AWS instance. You create nothing
in AWS; the owner runs the runbook with their own credentials.

Checklist, starting from deploy/compose.yaml:
1. The backend is on a network with no outbound access, so it cannot reach a model API. Give the
   backend outbound access to the Claude API host only. Say how you restricted it.
2. TLS on the proxy with automatic renewal.
3. A unit that starts the stack at boot.
4. A nightly timer that runs `python -m ingestion.feed run`.
5. A nightly SQLite backup and a copy of snapshots to object storage. Include the restore command
   and run it once locally against a backup you made.
6. One ARM instance with 2 GB of memory. No load balancer, NAT gateway or managed database.
7. Inbound ports 80 and 443 only. Administration without an open SSH port.
8. A billing alarm at USD 20 a month.
9. A monthly cost table taken from the AWS pricing calculator, with the date you read it.
10. In docs/DEPLOYMENT.md, a "deployment-day check" section for the owner: set the Claude key and
    the spend caps, run one plan, confirm one row per call in the spend ledger and a total of a few
    cents at most, then set the lifetime cap. This is the first and only verification of the Claude
    client against the real API, so write down what to do if it fails.

Ask the owner whether the demo is private or public before writing the access rules.

Done when: the local compose stack starts with the restricted outbound rule in place, and the
runbook can be followed top to bottom without guessing.
```

### Stream H: sign-in and saved-trip screens

**H-build (Luna), needs no design; start immediately**

```text
Task H-build. Frontend work. The backend already has accounts, wallets, saved trips and durable
jobs, and no traveler can reach any of them because there is no sign-in screen.

Build, against the existing API and following frontend/CLAUDE.md:
- /register and /sign-in using the /auth endpoints, including the CSRF header.
- A signed-in header with links to wallet, trips and sign out.
- /trips: list saved trips and reopen one, using the saved-trips API.
- A "save this trip" action on the plan result.
Use no browser storage; the session is the cookie. Do not change the contract.

Done when, in live mode: a new user registers, signs in, adds a card to the wallet, generates a
plan, saves it, and after a backend restart signs in again and reopens it.
```

### Stream I: For you

**I-design (Opus), after stream E's first real data and D-build**

```text
Task I-design. Write docs/superpowers/specs/2026-11-11-for-you-design.md.

Goal: a signed-in traveler sees which changes affect their own wallet and trips and what each is
worth to them. Read Phase 2 of the change-feed plan, then accounts/store.py (wallet_entries, trips,
latest_revision), ingestion/activation.py (the in-memory dry-run), core/optimizer, and
agents/explainer.py (the groundedness check).

Decide:
1. The matching rule, precisely: which ids intersect, which date windows overlap, and what an
   unmapped event does.
2. How the what-if knowledge base is built from an event's proposed row, and whether the dry-run
   code can be reused as it is.
3. What an EventImpact stores and how the before and after are compared.
4. The two labels, "if confirmed" and "reviewed": when each applies and when an impact is recomputed.
5. When impacts are computed (nightly, and on wallet or trip change) so the API only reads.
6. The Writer's contract and the rule that every number is copied from the computed impact.
7. New golden tests for impact amounts, without editing existing golden files.

Done when: Argon and one builder can start without asking you anything.
```

**I-core (Argon)**

```text
Task I-core. Write in full: backend/feed/match.py and backend/feed/impact.py as the design note
specifies, in plain code with no model call, plus new golden tests for impact amounts.

Leave as seams: the Writer, GET /feed/for-me, the count of changes on the trip overview, and the
nightly and on-change triggers.

Acceptance test: a synthetic transfer bonus against the demo wallet produces the expected difference
in minor units; an event that touches nothing in the wallet produces no impact; an unmapped event
matches nobody.
```

**I-build (Sonnet)**

```text
Task I-build. Fill I-core's seams: the Writer with the groundedness check and template fallback
reused from agents/explainer.py, GET /feed/for-me, the count on the trip overview, the triggers, and
a "For you" tab on the feed page. The contract, generated client and mock fixtures change in the
same pull request.

Done when: I-core's acceptance test passes without its marker, and in live mode a signed-in user
with the demo wallet sees the synthetic event with its computed difference and a sentence whose
numbers match it exactly.
```

### Stream J: leads and the Corroborator

**J-design (Sol), after D-build**

```text
Task J-design. Write docs/superpowers/specs/2026-11-11-corroborator-design.md.

Goal: the owner pastes a link, or a permitted feed supplies a headline, and the system confirms or
rejects the claim at the primary source. Read Phase 3 of the change-feed plan, then
agents/discovery/contracts.py and controller.py (the bounded loop to copy), ingestion/preflight.py
and ingestion/policy.py.

Decide:
1. What a lead stores: a title, a link and a one-line summary in our own words. Never page text.
2. The loop: its tools (look up registered pages for an issuer or programme; fetch through the
   preflight-gated fetcher; web search restricted to registered primary domains), its budget (at
   most three searches and three fetches per lead), and its three outcomes with the evidence each
   needs.
3. How "restricted to registered domains" is enforced in code, not in the prompt.
4. What a confirmed lead becomes, and how long an unconfirmed one lives.
5. Clustering: the deterministic key, and when a model is asked to break a tie.
6. Web search is a paid tool. Say how the loop is developed and tested without it, and what the
   production cost per lead is expected to be.
7. The acceptance set: twenty past leads with the right answer, supplied or approved by the owner.

Done when: Argon and one builder can start without asking you anything.
```

**J-core (Argon)**

```text
Task J-core. Write in full: ingestion/corroborate.py with the bounded loop, the tool interfaces, the
domain restriction enforced in code, and the typed outcome.

Leave as seams: the "paste a link" form in the review server, the feed poller, clustering, and the
harness that runs the labelled lead set.

Acceptance test, with a scripted client and a fake fetcher: a lead whose claim is on a registered
page is confirmed with a quote; a contradicted lead is reported as contradicted; the loop stops at
its budget; and an attempt to fetch an unregistered domain is refused before any request is made.
```

**J-build (Flash)**

```text
Task J-build. Fill J-core's seams: the form, the poller for the feeds stream E marked as permitted,
clustering, and the harness for the labelled set. Ask the owner for the twenty labelled leads.

Run the harness with the free-tier provider and a recorded search tool; make no paid call.

Done when: J-core's acceptance test passes without its marker, and your report gives the number
correctly confirmed, contradicted and not found out of twenty, with a transport log showing no
fetch outside the registered domains.
```
