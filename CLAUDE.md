# CLAUDE.md

Persistent context for any AI agent working in this repo (Claude Code, opencode, or other). Read this first, every session. Keep it short — it loads into every context window.

## What this is

A non-commercial student/portfolio project for a trip-first travel rewards optimizer: "A travel planner that knows your credit cards." The target prototype unifies itinerary curation, cash travel search, award discovery, points transfers, and card/offer optimization behind one orchestrated experience. The current build is the deterministic **Kernel MVP** for that prototype: given a trip + the user's cards/points + sample travel options, produce an itinerary, a costed budget, an optimal card/offer/payment strategy, and a points-transfer plan — every number explainable, every fact carrying provenance. Initial corridor: India → Singapore. Commercial launch, scale, SLAs, and licensed production inventory are not current goals; if that ever changes, providers and compliance are re-reviewed under spec 16's commercial profile.

Orientation: `docs/ARCHITECTURE.md` (one page). Product destination: specs `08` and `09`. Authoritative detail: `docs/specs/` (17 docs). **Specs win over this file; this file wins over your instincts.**

## Session start protocol (mandatory)

1. Read `DEVIATIONS.md` and the newest file in `reports/` — this is how you recover context. Do NOT re-read all specs and re-decide settled questions.
2. Read `docs/specs/06_implementation_protocol.md` (decision tiers, ambiguity protocol, gates).
3. Read only the spec(s) for the current milestone (see build order below).
4. Work the milestone. Log judgment calls to `DEVIATIONS.md` as you go. Pass the gate. Write `reports/<milestone>.md`.

## The five non-negotiables

1. **LLMs never do money math.** All reward/fee/discount/points arithmetic is deterministic Python. Any number in LLM prose must be copied from a computed artifact, never generated. Same rule on the frontend: render fields, never compute.
2. **The deterministic kernel never touches the web.** During the Kernel MVP, the only request-time external call is the LLM API. In the target prototype, allowlisted live evidence is accessed only through the Data Gateway (specs 09/16). The application never directly crawls booking sites at runtime; financial-rule crawling remains offline, batch, and human-reviewed (spec 05).
3. **Every fact carries provenance** (`source_url`, `last_verified`, `verified_by`, `needs_verification`, `confidence`) and propagates to the UI as trust badges. Never style them away.
4. **Agents propose, humans approve.** No autonomous writes of financial facts to the knowledge base. Ever. This is architecture, not a phase.
5. **Autonomy is deliberately bounded.** The Kernel MVP has exactly four LLM call sites (intake, planner, critic, explainer). Target-platform "agents" are fixed, typed domain workflows coordinated by an orchestrator; most are deterministic services, not free-roaming LLMs. No dynamic provider/MCP discovery, autonomous agent-to-agent delegation, or runtime self-modification of prompts/rules/code.

## Decision authority (full rules in spec 06 §1)

- **Tier F (frozen):** money as integer minor units + basis points + micro-major per-point values; per-transaction floor on points; cap fall-through and shared pools; regret-ordered greedy + improvement sweep; offer stacking order; the Kernel MVP pipeline graph and its four call sites; the groundedness gate; provenance columns; all golden-test expected values; verify-before-transfer as checklist step 1; profile-eligible, allowlisted-only target-platform provider access; never execute transfers or bookings. **If one of these looks wrong: implement to spec anyway, hand-audit per spec 06 §4, log it, `xfail` the test. Never silently "improve" it.**
- **Tier C (your call, log deviations):** naming, wiring, retry/timeout tuning within stated bounds, prompt phrasing (contracts fixed), per-diem constants, frontend details not specified.
- **Tier V (free):** internal decomposition, file names below module level, test organization, logging format, dev tooling.

## Ambiguity protocol

Do NOT stop and ask. Choose the most conservative option that changes no Tier-F behavior and no golden number, log it in `DEVIATIONS.md` (`date, doc§, question, decision, rationale, files`), continue. Ask a human ONLY for: a confirmed Tier-F spec bug, anything needing paid services or credentials, legal/compliance wording, replacing seed placeholder values with real verified data, or public deployment.

## Build order

Backend: **M1** (specs 00,01,02 — data model + optimizer + golden tests) → **M1b** (spec 07 — transfer pathfinder) → **M2** (spec 03 — pipeline + FastAPI) → **M3** (spec 04 — critic, evals, provenance rendering).
Frontend: **F1** (specs 10,11 — tokens + primitives) → **F2** (spec 12 — contract, codegen, wizard) → **F3** (specs 13,14,15 — loading + results + wit) → **F4** (performance + one live integration run).
Target prototype: specs **08,09,16** are authoritative design now; provider/gateway implementation begins only after the test-data Kernel MVP and frontend pass F4, unless the human explicitly changes the order. Use the active `student_noncommercial` provider profile; paid services/credentials still require human approval. Flight evidence is typed by meaning: current cash quote ≠ cached price observation ≠ sandbox fixture ≠ award availability (see `reports/flight_data_strategy.md`).

Gate before advancing. Gates are in spec 06 §5 (backend) and spec 10 §5 (frontend). A milestone is not done because the code exists; it is done when its gate passes.

## Current checkpoint (2026-07-24)

- **M1 is functionally green but not formally closed:** the existing suite has 20 passing tests, the 12 optimizer golden cases and determinism checks pass, strict type checking is clean, and the canonical demo is byte-identical. `reports/milestone_1.md` is still missing and must be written from fresh gate output before advancing.
- **M1b is the immediate implementation milestone:** `backend/core/transfer/` is still empty. Execute `docs/superpowers/plans/2026-07-24-m1b-transfer-pathfinder.md` test-first, pass Gate M1b, and write `reports/milestone_1b.md`. Do not begin M2 in the same change.
- **Later layers are scaffolds:** `backend/agents/`, `backend/api/`, `backend/ingestion/`, `frontend/`, and `contract/` contain no implementation yet. There is no provider gateway, runtime adapter, or project MCP configuration.
- **Do not connect travel-provider MCPs during M1b.** Developer MCPs are added just-in-time during F1–F4; runtime providers begin only after G1 creates normalized contracts, the provider registry, and `SampleAdapter`. Gondola is the first planned read-only live spike; installation never activates an adapter.
- **Git is initialized:** baseline commit `b3790e8` is on `main`; implementation work starts on `feat/m1b-transfer-pathfinder`. No remote is configured yet. Commit M1b changes in small test-green units on this branch; never claim a push or PR until a remote exists and the human requests it.

## Repo boundaries

- `backend/core/` imports nothing from `agents/` or `api/`.
- Future `backend/gateway/` owns all provider I/O. `backend/core/` must never import it; orchestration maps normalized quotes into kernel inputs.
- Nothing crosses `backend/` ↔ `frontend/` except `contract/openapi.json`.
- Schema change, snapshot, generated code, MSW fixtures, and UI updates ship in ONE PR (spec 12 §8). Split PRs are the drift vector.
- `docs/specs/` is read-only during implementation.
- Never use localStorage/sessionStorage. Never commit secrets. Developer/tooling MCP servers not listed in spec 10 §3 require a DEVIATIONS entry. A runtime provider MCP is an adapter transport and must pass the matching spec 16 student/commercial activation profile; installation alone never activates it.
- Registry-fetched component code (Magic UI, Aceternity, shadcn) is reviewed line-by-line before commit and rewired to semantic tokens in the same commit.

## Anti-drift

Behavior changes and refactors are separate commits; golden tests green between them. Never refactor Tier-F behavior "while you're in there." Any feature not in the specs needs a `SCOPE+` DEVIATIONS entry, and the default answer is no. Target-prototype features specified in 08/09/16 are in product scope but remain out of the Kernel MVP build order until its gates pass. Do not impose hypothetical commercial-launch requirements on the student prototype; do not waive the commercial re-review if the project is ever monetized. If context is lost mid-milestone, run the gate — whatever fails is what remains.

## Note for non-Claude agents

This file is the canonical agent brief. If your harness reads `AGENTS.md`, that file is a copy of this one — keep them identical.
