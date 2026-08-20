# Evidence Graph & Target Orchestration — design

**Date:** 2026-07-28
**Status:** DESIGN — approved in brainstorming, not implemented, not yet folded into spec 09.
**Scope:** Amendments to **spec 09 (target platform architecture)** only. The Kernel MVP (spec 03) is untouched.
**Depends on:** specs 03, 05, 09, 16; `docs/research/17_orchestration_substrate_adk.md`.

Written to be self-sufficient from a cold start. You should not need to re-read the three
research papers or re-derive any decision below.

---

## 1. Origin

Three papers were reviewed in `docs/research/`:

| Paper | What it is | Weight |
|---|---|---|
| *Loop Engineering* (HuaShu, Jun 2026) | Playbook for self-running agent loops; generator/evaluator separation; four silent costs | Independent synthesis, no experiments |
| *Graph Engineering* (compiled Jul 2026) | Karpathy autoresearch → AgentHub → Anthropic patterns; graph as shared memory | Independent synthesis, explicitly **not endorsed** by parties named |
| *Harness Handbook* (arXiv 2607.13285, Jul 2026) | Behavior-centric repo representation; measured localization gains | **Primary source with experiments** |

Weight them accordingly: only the third carries measured results.

**The scoping decision:** the human chose to apply these to the **product runtime**, and within
that, to **spec 09's unimplemented target platform only**. The Kernel MVP's six-node graph and
four LLM call sites are Tier F and were confirmed closed — nothing in these papers is a Tier-F
spec bug.

**The net effect of all three on a deliberately-bounded runtime is to strengthen the checking
layer, not the acting layer.** No amendment below adds autonomy. Spec 09 line 176 already gates
an LLM orchestrator behind a Tier-F amendment; nothing here crosses it.

---

## 2. Decisions taken (do not reopen)

| Decision | Choice | Rationale |
|---|---|---|
| Evidence graph **model** (nodes, edges, four invariants) | **ADOPT NOW** | Human overrode the recommendation to defer. Retrofitting lineage later is expensive; the multi-provider disagreement case is genuinely graph-shaped. |
| Graph **store technology** | **SQLite edge tables** | SQLite edge tables were chosen and shipped; NetworkX is available later only as a non-authoritative analytical projection. See §11.1. |
| Evidence validator | **Deterministic, no LLM** | Link resolution, expiry, completeness and comparability are all checkable in code. Adding a fifth LLM call site would erode non-negotiable #5 for no ambiguity that needs a model. |
| LLM-arbitrated entity resolution | **REJECTED** | The source paper (§II.D) uses a model to arbitrate canonical clusters. Here that would put an LLM in a position to decide two prices are "the same" — money reasoning by the back door (non-negotiable #1). Deterministic matching rules only. |
| LLM orchestrator | **REJECTED for now** | Spec 09 line 176 gates it; ADK doc §8 triggers stand at 0 of 5. |
| Full five-plane architecture (control/execution/artifact/graph/evaluation) | **REJECTED** | The architecture the paper itself says to reach last. Trades a provable kernel for capability with no traffic to justify it. |

---

## 3. The structural rule

> **Workflows never call each other. They read and write the evidence graph; the orchestrator
> sequences them.**

Star topology, not mesh. If the flight workflow could call the award workflow, the call graph
becomes emergent and unbounded. With the star, N workflows means N interfaces and every
interaction is a graph write — inspectable by construction.

```text
                         Target Orchestrator
                        (typed state machine)
                                 │
      ┌──────────┬──────────┬────┴─────┬──────────┬──────────┐
      ▼          ▼          ▼          ▼          ▼          ▼
   Intake     Flight     Hotel     Itinerary    Award    Card/Offer
      │          │          │          │          │          │
      └──────────┴──────────┴────┬─────┴──────────┴──────────┘
                                 │  every workflow reads/writes only here
                        ┌────────▼────────┐
                        │  Evidence Graph │ ◀── Data Gateway ── reviewed adapters
                        │  claims·sources │
                        │  runs·artifacts │
                        └────────┬────────┘
                                 │  orchestrator marshals typed inputs
                        ┌────────▼────────┐
                        │ Deterministic   │  Cost Estimator
                        │ Kernel          │  Rewards Optimizer
                        │ (pure, no I/O)  │  Transfer Pathfinder
                        └────────┬────────┘
                                 ▼
                   Critic → Groundedness Gate → Explainer
```

### Component naming

"Agent" in casual conversation maps to several different things. Spec 09 line 96 already says
no LLM call is implied by the word. Concretely:

| Colloquial | Actual components | LLM? |
|---|---|---|
| "flights + hotels agent" | **Flight workflow** + **Hotel workflow** (separate) | No — both deterministic |
| "miles/points agent" | **Award workflow** (evidence) + **Card/offer workflow** (invokes Rewards Optimizer) + **Transfer Pathfinder** (kernel) | No — all deterministic |
| "trip itinerary agent" | **Itinerary workflow** | Yes — call site 2 |

Flight and hotel stay split: fares expire in minutes and rates in hours; comparability
preconditions differ (fare conditions vs. occupancy/room-plan alignment); failure modes differ.
Merging them puts two incompatible validation rulebooks in one unit.

**Invariant to preserve: exactly four LLM call sites** — intake, itinerary, critic, explainer.
Adding a tenth provider adapter adds zero. This is what keeps non-negotiable #5 true as the
platform grows.

---

## 4. The evidence graph

### Node types

`Claim` · `Source` · `Artifact` · `Run` · `Evaluation`

### Edge types

`SUPPORTS` (source→claim) · `CONTRADICTS` (claim↔claim) · `SUPERSEDES` (claim→claim) ·
`RESOLVED_TO` (claim→canonical) · `DERIVED_FROM` (artifact→claims consumed) ·
`EVALUATED_BY` (claim|artifact→evaluation)

### The four invariants (binding)

1. Every `Claim` has a `Source` **or** is marked `is_inference`.
2. Every `Artifact` names an authoring `Run` and a version.
3. Every `Evaluation` names a rubric.
4. Every superseded or resolved-away object **remains addressable**. A merge is never a delete.

### `DERIVED_FROM` is load-bearing

DERIVED_FROM lets the graph prove that structured artifacts are grounded —
every computed value resolves to claims, upstream artifacts, or approved KB
facts. It does not replace spec 03 §6's numeric groundedness check over
explainer prose, which remains Tier F and unchanged: prose figures must still be
extracted and matched against structured artifacts, or carry exact field
citations. The graph complements that gate; it does not supersede it.

### Types

```python
class EvidenceRecord(BaseModel):          # what every workflow emits
    evidence_id: str
    run_id: str
    adapter_id: str
    kind: Literal["cash_quote", "price_observation", "sandbox_fixture",
                  "award_availability", "reference_fact"]
    claim: NormalizedPayload              # spec 16 contract
    source_id: str | None                 # provider, retrieved_at, source_url, terms_ref
    status: Literal["live", "cached", "estimated", "stale", "verify_required"]
    lifecycle: Literal["active", "superseded"]
    superseded_by: str | None
    is_inference: bool
    confidence: float
    needs_verification: bool


class ResolutionRecord(BaseModel):        # two records judged the same real-world thing
    resolution_id: str
    members: list[str]
    canonical_id: str
    rule: str                             # deterministic rule name, not prose rationale
    confidence: float
    created_by_run: str
```

`kind` is not new — `reports/flight_data_strategy.md` already establishes that flight evidence is
typed by meaning (current quote ≠ cached observation ≠ sandbox fixture ≠ award availability).
This makes it structural.

**Note:** `CONTRADICTS` edges are canonical. The inline `contradicts` list field is deprecated in favor of explicit symmetric edges.
**Tier-F precision:** these are **gateway-layer types under spec 16**. They are *not* the KB's
`Provenance` columns, which are Tier F and unchanged. Do not merge the two models.

### What each workflow touches

| Workflow | Writes | Reads |
|---|---|---|
| Intake | `Artifact(TripSpec)` | — |
| Flight | `Claim(cash_quote)`, `Claim(price_observation)`, `Source` | TripSpec |
| Hotel | `Claim(hotel_rate)`, `Source` | TripSpec, KB areas |
| Itinerary | `Artifact(DraftItinerary)` `DERIVED_FROM` POI claims | TripSpec, POI claims, chosen hotel |
| Award | `Claim(award_availability)`, `Source` | TripSpec, flight claims (route/cabin) |
| Card/offer | `Artifact(OptimizerResult)` `DERIVED_FROM` costed lines | approved KB facts, CostedTrip |

---

## 5. Aggregators are leads, never sources

This is the question most likely to be re-derived wrongly, so it is recorded here in full.

Credit-card aggregators — CardExpert, Paisabazaar (IN); YallaCompare, PolicyBazaar UAE (AE);
NerdWallet, The Points Guy (US) — are **not** ingested by the card/offer or award workflow, and
never touch the evidence graph.

- **Wrong layer.** Discovery is spec 05 Stage 0, offline batch. Spec 09 §4: offline ingestion
  "writes proposals, never approved facts" and "does not serve live inventory." At request time
  the card/offer workflow reads **approved KB facts only**.
- **Wrong role.** `DiscoveryCandidate` has no `Provenance` block and no `source_type`, so an
  aggregator claim is *type-incapable* of becoming a stored fact. Spec 05 explicitly pre-rejects
  adding an `aggregator_hint` to `Provenance.source_type`, because that would make every KB row
  able to carry hint provenance and reduce the invariant to a runtime check.

The only path: aggregator asserts a card exists → curator promotes to watchlist → pipeline
fetches the **issuer** page → extractor quotes that page → human approves. Three human gates,
and no aggregator number is an input to any of them. No affiliate link is stored, followed, or
rendered. No source is crawled before its ToS record exists in `discovery_sources.yaml`.

Assume aggregator *coverage* is commercially biased even where the *existence* claim is reliable.

---

## 6. Validation, resolution, budget

### Validator is separate from producer

Today `DomainResult` carries "a declared quality state" (spec 09 line 96) declared by the
workflow that produced it — self-grading. Split it: the declaration becomes an **input**, and a
deterministic validator issues the verdict.

The validator **acts**, it does not merely read:

- resolves the verify link,
- checks quote expiry against wall-clock,
- confirms price completeness (mandatory fees in scope),
- confirms currency, occupancy, room/rate and fare-condition alignment **before** permitting any
  cross-source comparison.

Emits `Evaluation{rubric_id, verdict, reasons[]}` (invariant 3).

### Resolution is reversible

Merges retain aliases, source, deterministic rule name, confidence, and creating run. Members
stay addressable. A false merge is the expensive mistake — it silently contaminates every
downstream comparison — so reversal must never require rebuilding.

### `PlanBudget` declared per run

Max provider calls, max concurrent fan-out, wall-clock, tokens, retries, cost — plus a
**minimum evidence bar for finalization**.

On exhaustion, return:

```python
PartialResult(best_artifact=..., completed=[...], unresolved=[...], stop_reason="...")
```

The stop reason renders to the user. Never hide partial failure behind fluent prose.

---

## 7. Orchestration policy

- **Fixed registry, enumerated in config.** No dynamic discovery. No LLM chooses workflows. No
  workflow spawns another.
- **Concurrency only in phase 1**, capped by `PlanBudget.max_fan_out`.
- **Branches are explicit code** — spec 09 §6's six, plus the contradiction policy in §8 below.
- **Degradation is per-workflow.** Award fails → continue without award options plus a warning.
  Flight fails entirely → fatal, no plan.

> **Boundary rule:** the orchestrator routes on evidence **status and quality**; it never reads
> claim **values** to make a money decision. "Is this good enough to use" is orchestration.
> "Which is cheaper" is the kernel. This is what stops provider-selection logic from quietly
> becoming pricing logic.

### Run sequence (BOM → SIN, 12–18 Oct, 2 adults)

| Phase | What runs | Notes |
|---|---|---|
| 0 | Intake (LLM) → `TripSpec` | wallet cards + balances attached |
| 1 | Flight ∥ Hotel ∥ reference POI retrieval | independent, concurrent under budget |
| 2 | Award — **conditional** | only if balances exist *and* a profile-eligible adapter is enabled; sequenced after flights because it needs route + cabin. No balances → skip, render unlock note |
| 3 | Validation + resolution (deterministic) | writes `Evaluation` nodes |
| 4 | Curate itinerary (LLM) | now knows actual hotel location |
| 5 | Kernel: `estimate_cost()` → `optimize()` → `find_transfer_plans()` | orchestrator marshals typed inputs; kernel never touches the graph |
| 6 | Critic → groundedness gate → explainer | |

**The area cycle, resolved.** Hotel appears to need candidate areas that only a curated itinerary
produces. Spec 09 §6 already resolves this and the amendment must state it explicitly: hotel
search runs in phase 1 against **KB reference areas ranked by interest overlap** — deterministic,
not against a curated itinerary. This is the first thing an implementer would get wrong.

---

## 8. Contradiction and supersession

```text
10:00  Adapter A → Claim(₹24,500, live, expires 10:20)  ◀─SUPPORTS─ Source(A)
10:01  Adapter B → Claim(₹26,100, live)                 ◀─SUPPORTS─ Source(B)

validator: same carrier/flight/date/cabin/fare-conditions
        → ResolutionRecord{members:[A,B], rule:"exact_itinerary_match"}
        → prices differ 6.5% > threshold
        → CONTRADICTS edge

orchestrator policy (explicit code, not judgment):
        prefer live over cached;
        on live-vs-live disagreement, exclude from bookable winner, label `estimated`

10:21  Claim A expired → re-query once if budget remains
        → Claim A' SUPERSEDES Claim A;  A remains addressable
```

The kernel only ever receives the canonical, validated claim set.

---

## 9. Testing

Add to spec 09 §12:

- **Trajectory assertions** — workflow sequence matches the state machine; skips are the
  *specified* skips; no workflow runs twice; budget respected. (The target-platform counterpart
  of the ADK doc §5.1 item, which was specced for Gate M3 and never built.)
- **Invariant assertions** — every finalized claim satisfies source-or-inference; every artifact
  names a run and version; every evaluation names a rubric; every superseded object resolves.
- **Structural aggregator test** — assert `"provenance" not in DiscoveryCandidate.model_fields`
  and that no code path constructs a KB row from any `DiscoveryCandidate` field other than
  `issuer_url_to_verify` (spec 05 already requires this on day one of Phase 2).
- **Groundedness as graph query** — every currency figure in the report reaches a `Claim` via
  `DERIVED_FROM`.

---

## 10. Explicitly not adopted

| Idea | Source | Why not |
|---|---|---|
| Agent swarms, 1,000 sub-agents | Graph Engineering §IV | Non-negotiable #5; ADK doc §8 triggers at 0/5 |
| Dynamic workflow generation | Graph Engineering §IV.B | Spec 09 line 78 forbids providers/LLMs creating tools or modifying the workflow |
| LLM entity resolution | Graph Engineering §II.D | Money reasoning by the back door |
| Five-plane architecture | Graph Engineering §VI.G | Reached last, not first; no traffic justifies it |
| Adversarial LLM evaluator | Loop Engineering §V | Human decision, 2026-07-28: not now |
| Harness Handbook for the repo | arXiv 2607.13285 | Out of scope — that is the dev harness, not the product runtime. Still worth doing; see `17_orchestration_substrate_adk.md` §5.3 (`SPECS-DIGEST.md`, specced at M1 exit, never built) |

---

## 11. Open questions for implementation

1. **Graph store technology.** The graph *model* is adopted (§2); only the backing store is open.
   Candidates: SQLite with edge tables (consistent with
   existing storage, zero new dependency) vs. NetworkX in-memory per run (matches the paper,
   but loses cross-run lineage) vs. an embedded graph DB. Decide at G1; the type contracts above
   do not depend on it. Note spec 09 §7 already has four stores — this must not become a fifth
   without justifying why the KB's relational store cannot host the edge tables.
2. **Contradiction threshold.** 6.5% used illustratively in §8. The real threshold is per-`kind`
   and must be a named config constant, not a literal.
3. **Graph retention.** How long claims survive after a plan completes, and whether spec 17
   accounts change the answer (saved trips referencing expired evidence).

---

## 12. Relationship to existing specs

- **Spec 03** — untouched. Kernel MVP graph and four call sites remain Tier F.
- **Spec 05** — unchanged; §5 above restates its Stage 0 rules, it does not amend them.
- **Spec 09** — the target of every amendment here: §4 (boundary rules), §5 (workflow contracts),
  §6 (orchestration policy), §7 (storage), §12 (testing).
- **Spec 16** — `EvidenceRecord` and `ResolutionRecord` are gateway-layer normalized contracts
  and belong to this spec's family.
- **Spec 17** — accounts may extend graph retention; see §11.3.

Implementation begins only after the Kernel MVP and frontend pass their gates, per the build
order in `AGENTS.md`. This document is design, not a work order.
