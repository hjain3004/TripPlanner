# 17 — Orchestration Substrate: Google ADK Evaluation & Phased Adoption

**Status:** evaluation + forward plan. **Decision: do NOT adopt for Phase 1 (MVP). Adopt-candidate for Phase 3 (live agentic platform), subject to the triggers in §8.** Three ideas are borrowed immediately without taking the dependency (§5).

This doc exists so the ADK question is decided once, with reasons, rather than relitigated every time someone encounters the repo. It references Phase 3 docs (`09_target_platform_architecture`, `16_data_gateway_and_adapters`) that may not be written yet; where it does, treat this doc as the input to those, not the authority over them.

Numbering note: `08`–`09` are reserved for product vision and target-platform architecture; `16` for the data gateway. This doc is `17` because it depends on all three.

---

## 1. What ADK is (verified 2026-07-25 from the repo)

Google's Agent Development Kit — an open-source, code-first Python framework for building, evaluating, and deploying agents. Apache 2.0. `pip install google-adk` (extras: `google-adk[extensions]`). ~19.6k stars, 3.4k forks, 58 releases, latest v1.33.0 (2026-05-08), release cadence stated as roughly bi-weekly, ~486 open issues / ~328 open PRs. Sibling implementations exist for Java and Go; a separate `adk-web` repo provides the dev UI; `adk-python-community` hosts community tools and deployment scripts. Docs: `google.github.io/adk-docs`.

Positioning per the README: modular framework applying software-development principles to agent creation, optimized for Gemini but **model-agnostic, deployment-agnostic, and compatible with other frameworks**.

Capabilities relevant to us:

- **Rich tool ecosystem** — pre-built tools, custom Python functions, **OpenAPI specs**, and **MCP tools**.
- **Modular multi-agent systems** — specialized agents composed into hierarchies; `LlmAgent` with `sub_agents` performs model-guided delegation. A workflow-agent family (sequential / parallel / loop composition) is documented separately — **verify exact class names and signatures against the pinned version at adoption time** (see §9 churn risk).
- **Tool Confirmation** — a human-in-the-loop flow that guards tool execution with explicit confirmation and custom input.
- **Rewind** — rewind a session to before a previous invocation.
- **Agent Config** — define agents declaratively without code.
- **Dev UI** — built-in web UI to test, evaluate, debug, and demo agents.
- **Evaluation** — `adk eval <agent> <evalset.json>` CLI plus evalset files.
- **Deployment** — containerize to Cloud Run, or scale on Vertex AI Agent Engine; recent work adds custom service registration for the built-in FastAPI server.
- **A2A protocol** integration for remote agent-to-agent communication.
- **`llms.txt` / `llms-full.txt`** — condensed and full framework context files intended to be pasted into an LLM's context when building with ADK.

## 2. Why this is a real candidate, not hype

The two whitepapers in `docs/research/` are Google's own agent papers; ADK is Google's reference implementation of that material. The concepts our architecture already borrowed — coordinator patterns, sequential/loop composition, tool-grounded reasoning, HITL gating, AgentOps-style evaluation — appear in ADK as first-class primitives. That is corroborating evidence that our design choices are mainstream-correct, and it makes ADK's source the fastest way to see those concepts as running code.

Two features in particular *validate* frozen decisions rather than challenging them: **Tool Confirmation** is our human-approval gate (spec 05) as a framework primitive, and **Rewind** is a generalization of our bounded critic revision loop (spec 03 §6).

## 3. Fit against the current architecture

| ADK capability | Phase-1 stance (frozen) | Phase-3 relevance |
|---|---|---|
| Multi-agent hierarchies, `sub_agents` delegation | **Excluded** — no agent-to-agent delegation (CLAUDE.md #5) | Medium — orchestrator may route, but bounded |
| LLM-driven dynamic tool selection | **Excluded** — fixed graph, four call sites | High — provider choice is a real decision |
| Sequential / loop composition | Equivalent to a `for` loop and a bounded `while` | Low — still trivial |
| Parallel composition | No parallelism needed (one KB read path) | **High** — provider fan-out is the core need |
| MCP tools | Dev-time MCPs only (spec 10 §3); none at runtime | **High** — Gondola-class sources plug in directly |
| OpenAPI-spec tools | N/A | **High** — adapter contracts are OpenAPI-shaped |
| Tool Confirmation (HITL) | Implemented by hand in the review queue | **High** — verify-before-transfer gate |
| Evaluation / evalsets | Custom golden tests + LM judge (spec 04) | Medium — trajectory evals add coverage |
| Dev UI / tracing | TraceEvent JSON (spec 03 §1) | Medium — better debugging |
| Deployment (Cloud Run / Agent Engine) | Free hosting, FastAPI | Medium — cost-dependent |
| Streaming / bidi audio-video | Out of scope | Out of scope |
| A2A protocol | Out of scope | Out of scope (single-owner system) |

Read the left column honestly: **the features that make ADK powerful are the ones Phase 1 deliberately forbids.** What remains reduces to control-flow primitives Python already has.

## 4. Why not Phase 1 — four reasons

1. **Near-zero net capability.** Our six-node fixed pipeline maps to sequential composition plus one bounded loop. Taking a framework dependency for that is negative value.
2. **Churn versus autonomous implementation.** Bi-weekly releases and v1.33 within roughly a year of launch means APIs move. An implementing agent whose training predates the pinned version will produce plausible-but-wrong ADK code — the same failure class we added Next.js DevTools MCP to catch on the frontend, but without an equivalent runtime error signal for agent-graph misuse. Mitigable (§9) but real.
3. **Kernel purity.** Golden tests call `optimize()` and `find_transfer_plans()` as pure functions with no session, state, or event machinery. That purity is *why* the money math is provable. Wrapping the kernel in agent abstractions during Phase 1 would trade the project's strongest asset for nothing.
4. **Gravity.** Optimized for Gemini and most frictionless on Google Cloud. Both are fine choices later; neither should be locked in before the provider-agnostic LLM interface (spec 03 §5) has been exercised against at least one free-tier provider.

**Tier placement:** the orchestration substrate is **Tier C** (spec 00 already says "plain Python pipeline first; optional LangGraph wrapper only if streaming/checkpointing is wanted"). ADK occupies that same slot. Adopting it violates no Tier-F rule — it is a judgment call, and this doc records the judgment. Reversing it requires a DEVIATIONS entry citing §8 triggers.

## 5. Adopt immediately — three ideas, zero dependency

**5.1 Trajectory evaluation (amend spec 04).** ADK's evalsets score not only final output but the path taken. Spec 04 currently checks only outputs. Add a third eval class: **pipeline trajectory tests** asserting, per golden trip, the exact node sequence, that the critic looped ≤ 2 times, that the transfer pathfinder ran iff `points_balances` was non-empty, and that no node was skipped or repeated. Implementation: assert over the existing `TraceEvent` list — no new machinery. This catches a whole class of regression (silently skipped critic, double-run planner) invisible to output-only tests. **Action: add to spec 04 as §5; required at Gate M3.**

**5.2 Tool Confirmation as a validation, not an adoption.** ADK shipping HITL tool-gating as a first-class primitive is external corroboration for spec 05's review queue and spec 07's verify-before-transfer checkpoint. Keep both exactly as specced; cite this in DEVIATIONS if anyone proposes relaxing them.

**5.3 The `llms.txt` pattern for this repo.** ADK ships a condensed and a full context file for agents building with it. Do the same: generate `docs/specs/SPECS-DIGEST.md` — a single file containing the five non-negotiables, decision tiers, all frozen constants and conventions (minor units, basis points, micro-major, floor semantics, stacking order), every interface signature, and every golden-test expected value, with pointers to the full docs. Target ≤ 1,500 lines. Sessions load the digest plus the current milestone's spec instead of paging through fourteen documents. **Action: generate at the end of Milestone 1, regenerate whenever a Tier-F constant changes; add a CI check that the digest is newer than the specs it summarizes.**

## 6. Phase 3 adoption design (if triggers fire)

The target-platform shape from the review of the product vision — orchestrator over domain workflows over a deterministic kernel — maps onto ADK cleanly:

- **Provider fan-out** → parallel workflow agent invoking flight / hotel / award / offer adapters concurrently, with per-adapter timeouts and partial-result tolerance. This is the single strongest reason to adopt: hand-rolled concurrent fan-out with per-provider circuit breaking is exactly the code nobody wants to own.
- **Adapters as tools** → OpenAPI-spec tools for keyed HTTP providers; **MCP tools for MCP-native sources (Gondola, SerpApi-class wrappers)**, which removes the need for bespoke adapter code per MCP source.
- **Orchestrator** → a coordinator agent whose delegation set is *explicitly enumerated*, never open-ended. Its real decisions: cash vs. points, which provider to trust on disagreement, whether to re-search flexible dates, whether a quote has expired mid-plan.
- **Critic loop** → loop agent with hard max iterations; consider Rewind for re-planning after a stale-quote invalidation.
- **Verify-before-transfer** → Tool Confirmation on any tool whose output feeds a transfer instruction. The gate becomes framework-enforced rather than convention-enforced. **This does not relax spec 07 §5**; it implements it.
- **Deterministic kernel** → exposed to ADK as plain function tools wrapping `optimize()`, `find_transfer_plans()`, and the cost estimator.

**The kernel boundary rule (proposed Tier F on adoption):** *ADK may orchestrate around the kernel; it may never orchestrate inside it.* All money, points, cap, offer, forex, and transfer arithmetic stays in `backend/core/` as pure functions with their existing tests. No agent, callback, or model output may compute, adjust, or re-derive a kernel number. Consequence: every golden test in spec 04 survives adoption unchanged, which is also the migration safety net (§7).

FastAPI stays the public API surface (spec 12's contract is frontend-facing and must not change); ADK sits behind it. ADK's custom service registration for its built-in FastAPI server is worth evaluating at that point, but the OpenAPI snapshot contract is authoritative either way.

## 7. Migration protocol (non-negotiable if adoption happens)

1. **Pilot one workflow only** — the provider fan-out. Do not port intake, planner, critic, or explainer in the first pass.
2. **Run both paths in parallel** behind a flag. The existing plain-Python pipeline remains the reference implementation.
3. **Equivalence gate:** for all golden trips, the ADK path must produce a `FinalReport` byte-identical to the plain-Python path (modulo trace ids and timestamps). Determinism (spec 02 §9 item 11) is the acceptance criterion, not "it looks right."
4. **Pin the version** in `pyproject.toml` (exact, not caret). Upgrade is a deliberate PR with the equivalence gate re-run.
5. Only after the pilot passes twice on consecutive weeks does anything else port. Behavior changes and framework migration never share a commit (spec 06 §6).

## 8. Re-evaluation triggers

Revisit adoption when **two or more** hold:

1. ≥ 3 live provider adapters exist and need concurrent fan-out per request.
2. The orchestrator needs genuine dynamic routing (provider disagreement, conditional re-search) rather than a fixed sequence.
3. ≥ 5 MCP-native tools are in the runtime path.
4. Managed deployment or autoscaling becomes a real requirement (traffic, not aspiration).
5. Streaming or voice enters scope.

Fewer than two → stay on plain Python. Record the check in DEVIATIONS when the question next arises.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| API churn breaks the build | Exact version pin; upgrade PRs gated on §7.3 equivalence |
| Implementing agent writes stale-API code | Load `llms-full.txt` for the pinned version into agent context; prefer official docs over model recall; expect first-pass errors |
| Gemini / Google Cloud lock-in | Keep spec 03 §5 provider-agnostic interface; exercise a non-Gemini provider before adopting; verify Cloud Run free-tier viability |
| Abstraction obscures money math | Kernel boundary rule (§6), enforced by unchanged golden tests |
| Framework complexity exceeds benefit | Pilot-one-workflow rule (§7.1); abandon if the pilot doesn't beat the hand-rolled fan-out on clarity *and* determinism |
| Community-repo tools are unvetted | Treat `adk-python-community` code like registry components (spec 10 §3): line-by-line review before commit |

## 10. Protocol amendments

Add to spec 06 **Tier C**: choice of orchestration substrate (plain Python / LangGraph / ADK), governed by §8 triggers and §7 migration protocol. Add to **Tier F** *on adoption only*: the kernel boundary rule (§6). Add to spec 04: trajectory evals (§5.1) as a new eval class, required at Gate M3. Add to spec 00 Milestone 1 exit: generate `SPECS-DIGEST.md` (§5.3).

## 11. Ecosystem comparison — substrates and platforms

Decided once here so the question isn't reopened per-session. **Current verdict: plain Python substrate + Hugging Face as a data/inference source. No agent framework in Phase 1.**

### 11.1 Orchestration substrates (mutually exclusive — pick at most one)

| Option | Strengths | Costs for us | Verdict |
|---|---|---|---|
| **Plain Python** | Zero deps; the 6-node graph is a function call sequence; kernel stays pure; nothing between golden tests and the thing they prove | Manual concurrency and circuit-breaking if Phase 3 needs fan-out | **Phase 1 default (current)** |
| **LangGraph** | Graph-first; durable checkpointing; interrupt/resume maps onto `needs_clarification`; lighter than ADK; framework-agnostic models | Same Tier-C churn risk; state model wants to wrap the kernel; features overlap what spec 12's job API already does | **Phase 3 candidate — evaluate head-to-head with ADK** |
| **ADK** | Best tool ecosystem (MCP + OpenAPI as first-class tools); Tool Confirmation HITL; `adk eval`; parallel fan-out; deployment story | §4 reasons; Gemini/GCP gravity; bi-weekly churn | **Phase 3 candidate (this doc)** |
| **LangChain** | Broad provider/loader/retriever abstraction | Abstracts a problem we don't have: one LLM interface (~30 lines, spec 03 §5), no chains, no RAG, no memory in MVP. Large fast-moving surface area for negative net value | **Reject.** Reconsider only if Phase-2 ingestion needs many document loaders — and pdfplumber already covers T&C PDFs |
| **Lightweight typed-LLM SDKs** (Pydantic-AI class) | Typed structured outputs with minimal surface | Our `complete_json` Protocol already does this in a page | **Reject for now**; revisit only if hand-rolled JSON validation proves flaky |

Decision rule at Phase 3: the deciding question is **concurrent provider fan-out and per-provider failure handling.** Whichever option makes that boring wins. Run §8 triggers, then §7's pilot protocol against the top candidate; do not pilot two frameworks simultaneously.

### 11.2 Hugging Face — not a substrate, three separate uses

Evaluate each independently; adopting one does not imply the others.

1. **Dataset distribution — ADOPT NOW (Phase 1).** FSQ OS Places is served from the HF Hub (`hf://datasets/foursquare/fsq-os-places/release/dt=<date>/places/parquet/*`). POI ingestion depends on `huggingface_hub` / `datasets` regardless of any framework decision. Pin the release date in the seed loader so the corpus is reproducible, and record it in provenance (`source_url` = the dataset path, `last_verified` = release date). Apache 2.0 — storage and commercial use permitted.
2. **Inference provider — EVALUATE (Phase 1/2).** HF Inference Providers is a legitimate candidate behind the spec 03 §5 `LLMClient` Protocol. Adoption cost is one config profile, not an architecture change — which is exactly why the Protocol exists. **Verify current free-tier credits and rate limits at signup; these terms move.** Requires no change to any Tier-F rule.
3. **Local models / embeddings — REJECT for MVP.** Small local models underperform on intake structuring and itinerary quality (spec 03 §5 note), and total token volume is tiny because the kernel is deterministic. `sentence-transformers` becomes relevant only if the POI corpus exceeds ~1k rows (spec 00 already sets that threshold for vector search); at MVP scale SQL + tag filtering beats embeddings on accuracy, latency, and debuggability.

Spaces is a viable free host for the FastAPI backend but offers no advantage over Render/Fly for a plain API; treat as a fallback.

### 11.3 The principle behind all of the above

These frameworks abstract **LLM plumbing**, and LLM plumbing is not this project's hard part. The hard parts are the reward-rules schema, cap-aware allocation, the transfer graph, and provenance discipline — no framework touches any of them. Every dependency added near the kernel is surface area between the golden tests and the thing they prove. Adopt a framework only when it removes work that is genuinely hard *and* genuinely ours to do; fan-out and provider failure handling is the first thing that will qualify.
