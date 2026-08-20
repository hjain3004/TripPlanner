# P1 — Prompt Hardening Against a Real Model

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:executing-plans`. Steps use checkbox
> (`- [ ]`) syntax. Also required: `superpowers:test-driven-development`,
> `superpowers:systematic-debugging`, `superpowers:verification-before-completion`.

**Goal:** Make the four LLM call sites survive varied real requests, and make finding the next
failure cost almost nothing.

**Why.** The pipeline ran against a live model for the first time on 2026-08-16. The first three
calls produced three defects that 475 passing tests could not see — a rejected User-Agent, a
`{"trip_spec": {...}}` wrapper that defeated even the repair retry, and an `unresolved` threshold
so loose that every trip demanded clarification. All are fixed. **That was one request shape.**
There are four call sites and one has only ever been exercised on the happy path.

**Cost is a first-class constraint here, not an afterthought.** The human's framing:
*"i guess it'll take a few trial and errors which will take a lot of tokens."* Correct — which is
why Part A exists. Naive iteration re-pays for all four call sites every time you touch one
prompt. Part A makes a re-run cost zero for the prompts you did not change. **Do Part A first.
Do not start tuning prompts before record/replay works.**

---

## What you are working with

| Thing | Where | Note |
|---|---|---|
| Real client | `agents/llm.py::HostedFreeTier` | OpenAI-compatible; reads `TRIPWISE_LLM_*` from env |
| Test client | `agents/llm.py::ScriptedLLMClient` | ignores prompt text entirely |
| Repair loop | `agents/llm.py::complete_with_repair` | retries **once** on `ValidationError` |
| Recording dir | `backend/evals/recorded/` | **exists, empty** — created 2026-07-24, never used |
| The four call sites | intake, planner, critic, explainer | Tier-F: exactly four. Do not add a fifth. |
| Groundedness gate | `agents/explainer.py::_is_grounded` | falls back to deterministic prose on failure |

Provider in use: Groq, `https://api.groq.com/openai/v1`, model `llama-3.3-70b-versatile`.
Config lives in `backend/.env` (gitignored). `source backend/.env` before running anything live —
nothing auto-loads it.

---

## Global Constraints

1. **Exactly four LLM call sites.** Tier-F (`CLAUDE.md` non-negotiable #5). Hardening prompts is
   in scope; adding a call site is not.
2. **LLMs never do money math.** Any number in LLM prose must be copied from a computed artifact.
   If you find the explainer inventing a figure, that is a *bug in the groundedness gate*, not a
   prompt-tuning opportunity — report it as a defect.
3. **Prompt phrasing is Tier C** — your call, log it. Prompt *contracts* (the schema each site
   returns) are fixed.
4. **Money goldens are frozen.** `backend/evals/golden/` must not change.
5. **No secret ever enters a recorded fixture.** Recordings capture prompts and responses; assert
   the API key never appears in `evals/recorded/`.
6. **`make gate` is the backend gate.** Whole, pasted whole.
7. **Report numbers you measured.** Including token/call counts.

---

## Measured Baseline

Verify in Task 0.

| Metric | Value |
|---|---|
| `make gate` | PASSED, 475 tests |
| live pipeline run | `PipelineStatus.OK`, 4-day itinerary, effective cost 18,444,055 minor, savings 494bp |
| known-good request | "Plan a 4 night trip from Delhi to Singapore for 2 people starting 2026-09-01. Balanced style. We like food and nature. I have the HDFC Infinia card." |
| catalogs active | 6 regions, 307MB; SIN has 28,540 places |
| `evals/recorded/` | empty |

---

## Task 0: Preflight

- [ ] `git status --porcelain` empty; `make gate` passes before you change anything.
- [ ] `source backend/.env` and confirm a single live call succeeds (the known-good request above).
- [ ] Create branch `feat/p1-prompt-hardening`.

---

# PART A — Make iteration cheap (do this first)

## Task 1: Record/replay for LLM calls

- [ ] Add `RecordingLLMClient` (wraps any `LLMClient`): on each call, writes
      `evals/recorded/{node}/{sha256(system+user+model)[:16]}.json` containing the request hash,
      node, model, and the **raw response content**. Never the API key or the Authorization header.
- [ ] Add `ReplayLLMClient`: same key derivation; returns the recorded response, and raises a
      clear "no recording for this prompt — run in record mode" error on a miss.
- [ ] The key must include a hash of the prompt text, so **changing one prompt invalidates only
      that node's recordings** and everything else still replays. This is the entire point of the
      task; get it right.
- [ ] Failing test first: record a call with a stub transport, replay it, assert identical parsed
      output and **zero transport calls** on replay.
- [ ] Add a test asserting no file under `evals/recorded/` contains the value of
      `TRIPWISE_LLM_API_KEY` (extend `evals/test_no_committed_secrets.py` if simpler).
- [ ] Decide and document: are recordings committed? Recommend **yes** for a small curated set —
      they make CI able to exercise real model output shapes without a key. They are prompts and
      responses about public travel data, no secrets. If you commit them, keep them small.
- [ ] `make gate`. Commit: `feat(evals): record and replay real LLM responses`.

## Task 2: A scenario matrix, as data

- [ ] Create `evals/scenarios.yaml` — 12–15 requests chosen to stress *different* things, not 15
      variations of the same happy path. Cover at least:
      a clean happy path; a request missing dates; one with no card mentioned; an unknown card;
      an unsupported destination (should return capability `absent`, not a fallback);
      a `budget_supported=false` region (BOM/DXB/NYC/LON/PAR — the budget block must be absent
      with a stated reason, not zero-filled); a one-night trip; a long trip (10+ nights);
      a request with contradictory constraints; a request in the style of a real person typing
      quickly, lowercase, no punctuation; a request naming a venue that does not exist.
- [ ] Each scenario declares what "acceptable" means — e.g. `expect: ok` / `expect:
      needs_clarification` / `expect: capability_absent`. Not a golden string; a category.
- [ ] `make gate`. Commit: `test(evals): scenario matrix for real-model behaviour`.

## Task 3: The runner

- [ ] `python -m evals.prompt_probe --record` runs every scenario live and records.
      `--replay` re-runs from cache with zero network.
- [ ] Output a table: scenario × call site → `ok` / the failure class (schema violation, wrong
      status, groundedness fallback fired, integrity guard tripped, crash).
- [ ] **Cost discipline, required:**
      - default to `llama-3.1-8b-instant` for breadth (measured 101ms; cheapest), and only
        re-validate the final prompt set on `llama-3.3-70b-versatile`;
      - honour Groq's rate limits with backoff — a 429 storm wastes the quota;
      - print total live calls made at the end of every run, and report it.
- [ ] `make gate`. Commit: `feat(evals): prompt probe runner`.

---

# PART B — Find and fix, in bounded rounds

## Task 4: Baseline the failures

- [ ] Run `--record` once across all scenarios on the cheap model. Record the failure table
      verbatim into your report. **This is the only expensive step; everything after replays.**
- [ ] Classify each failure: prompt defect / genuine product bug / test-expectation wrong.
      These are not the same thing and the fix differs. I7 and the F4 repair both turned up
      "the test was wrong" cases; expect some here too.

## Task 5: Fix, at most three rounds

- [ ] For each prompt defect: change the prompt, re-run **only the affected node** live, replay
      the rest. Record the before/after in the report.
- [ ] **Hard stop after three rounds.** If a scenario still fails, report it as an open finding
      with the evidence. Do not grind — the human explicitly flagged the token cost, and an honest
      "still failing, here is why" is a better deliverable than a silent budget burn.
- [ ] Anything you conclude is a *product* bug (not a prompt bug) gets a failing test and a fix,
      or an explicit "not fixed, out of scope" line — not a prompt workaround papering over it.
- [ ] `make gate` after each round. Commit per round.

## Task 6: Lock the behaviour in

- [ ] Convert the passing scenarios into a replay-backed test that runs in `make gate` with **no
      network and no API key**, so a future prompt edit that breaks a shape fails the gate
      immediately instead of at the next live run.
- [ ] Anti-vacuity: assert the replay test actually loaded recordings and exercised all four call
      sites — a replay suite with no recordings passes forever.
- [ ] `make gate`. Commit: `test(evals): replay-backed prompt regression suite`.

---

## Task 7: Report

- [ ] `reports/p1_prompt_hardening.md`: the baseline failure table, every prompt changed with
      before/after, every defect classified prompt-vs-product, total live calls made, and every
      scenario still failing.
- [ ] Update `DEVIATIONS.md` for each prompt change (Tier C).

---

## Explicitly out of scope

- Adding a fifth LLM call site. Tier-F.
- Changing what any call site *returns* (the schemas). Phrasing only.
- Swapping providers or models as a fix for a prompt defect. If a prompt only works on one model,
  say so — that is a finding, not a solution.
- Tuning the groundedness gate to accept invented numbers. If prose disagrees with the artifact,
  the prose is wrong.

---

## Final Response Requirements

1. **Per-task status** — `done` / `partial` / `not started`.
2. **Full `make gate` output**, pasted whole.
3. **The baseline failure table**, and the same table after fixes.
4. **Total live LLM calls made**, and on which models.
5. **Every prompt changed**, before and after.
6. **Every scenario still failing**, with its evidence.
7. **Everything you did not do**, and why.

Do not push. Do not open a PR. Report and stop.

---

## Self-Review Notes

- Did I build record/replay *before* tuning prompts, or did I burn tokens re-running unchanged
  call sites?
- Does changing one prompt invalidate only that node's recordings?
- Does the replay suite run with no network and no API key? Verify by unsetting the key.
- Did I paper over a product bug with prompt wording?
- Did any recording capture the API key?
- Is the model still `llama-3.3-70b-versatile` for the final validation run?
