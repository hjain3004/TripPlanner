# Itinerary I2 — Place Contracts, Provider Registry, Sample Adapter

**Date:** 2026-08-11
**Phase:** I2 of `docs/superpowers/specs/2026-08-02-itinerary-intelligence-design.md` §14.
**Purpose (verbatim from the design):** *"freeze the internal seam before choosing real data
transports."*

This phase writes **zero** provider code, makes **zero** network calls, and uses **zero**
credentials. It defines the typed boundary that a real provider will later plug into, and proves
that boundary works by implementing a fixture-backed adapter behind it.

---

# PART 0 — READ BEFORE WRITING ANY CODE

## 0.1 Failures from the two previous phases

Both prior phases were reported complete before they were. Every miss was mechanically
checkable. Read this table; it is the highest-value part of this document.

| # | What happened | Rule that prevents it |
|---|---|---|
| 1 | Reported a **multi-item task complete when 1 of 5 items was done** — claimed "updated top-of-file notes across superseded documents" when `git diff --name-only -- docs/` returned *nothing*. | A task with N numbered sub-items is done when N are done. Report status **per sub-item**, with the command that proves each. |
| 2 | Reported test deltas as *"(Inherited from previous subagent, assumed net positive)"*. | **Never report a metric you did not measure.** If you inherit work, say so *and* measure it yourself. |
| 3 | Ran `mypy` on a narrower target set and presented that as the gate result. | Gate commands are literal. Copy them character for character. |
| 4 | Three features added; test count went 151 → 151. Existing tests were edited instead of new ones added. | New behavior = new test function. The count must rise. |
| 5 | Wrote `patch_*.py` / `commit_script.sh` to edit files, left them in the tree, reported "completely clean." Twice. | Edit files directly. Paste `git status --short` before any cleanliness claim. |
| 6 | Computed a violation signal but never wired it to a consequence, then reported the requirement met. | A warning is not enforcement. If a rule says X must not happen, a test must prove X is **rejected**. |
| 7 | Zero commits across a whole phase, despite per-task commit instructions. | Commit per task, before starting the next. |

**Meta-pattern: confident completion claims that one command would have disproved.** Assume every
claim you make will be checked by someone running that command. Run it first.

## 0.2 Hard rules

1. No scripts that patch source files. Edit directly. Delete any temp file before committing.
2. No narrower substitutes for the gate commands.
3. The words "clean", "complete", "passing", "done" appear only adjacent to pasted raw output.
4. New behavior gets a new test function. Editing an existing test counts only when a signature
   genuinely changed.
5. **`contract/openapi.json` must not change.** I2 is internal. API/UI exposure is phase I6, and
   spec 12 §8 requires schema + snapshot + generated client + MSW fixtures + UI in ONE PR — which
   this is not. If the file changes, stop and report.
6. **`backend/evals/golden/` must not change.**
7. **`backend/core/` must never import `gateway`.** There is already an AST test enforcing this
   (`backend/evals/test_evidence_boundary.py`). Keep it passing.
8. **No network, no credential, no real provider, no HTTP client.** Not even an unused import.
   `PlanBudget.max_cost_minor` stays `0`.
9. Do not proceed to task N+1 until task N is committed.

## 0.3 Per-task closing protocol — paste raw output, every task

```bash
cd <worktree>/backend
.venv/bin/pytest -q 2>&1 | tail -3
.venv/bin/mypy --strict core/ agents/ api/ gateway/ 2>&1 | tail -2
.venv/bin/ruff check gateway/ evals/test_place_*.py evals/test_registry_*.py 2>&1 | tail -2
cd ..
git status --short
git log --oneline -1
```

Then one line each: test count before → after (must increase); was `git status --short` empty.

---

# PART 1 — PREREQUISITE: MERGE I0 AND I1 FIRST

**Do not start this phase until this section is resolved.** As of 2026-08-11 the work I2 depends
on sits on two unmerged branches:

| Branch | Location | State |
|---|---|---|
| `feat/i0-evidence-hardening` | `.worktrees/itinerary-i0-evidence-hardening` | 7 commits, Gate I0 passed, 196 tests |
| `feat/i1-safety` | `/Users/himanshu_jain/TripPlanner_I1` | Gate I1 passed, 159 tests |

Both branched from `origin/main` (`aa08dd4`). Neither is merged.

I2 needs **both**:
- from **I0**: the evidence graph (`Claim`, `EvidenceIdentity`, `EvidenceGraph`, `add_edge`
  validation, `SqliteEvidenceStore`) — Task 5 below attaches place claims to it;
- from **I1**: `backend/core/itinerary/compose.py`, `ComposerResult`, `ScheduleWarning` — Task 2
  below defines `ItineraryDraft` / `ItineraryValidation` contracts that must *match what the
  composer already produces*, not invent a parallel shape.

Building I2 on either branch alone guarantees a conflict or a duplicated contract.

**Required first step:** merge `feat/i0-evidence-hardening` and `feat/i1-safety` into `main`
(order does not matter; they touch disjoint files — I0 is `gateway/evidence/`, I1 is
`core/itinerary/` + `agents/planner.py`). Resolve any `DEVIATIONS.md` conflict by keeping both
sections. Then confirm on merged `main`:

```bash
cd backend
.venv/bin/pytest -q                                   # expect ~222 (196 + 159 - 133 shared baseline)
.venv/bin/mypy --strict core/ agents/ api/ gateway/   # expect clean, 44 files
```

Branch I2 from that merged commit. Record its sha in your final report. If the merged test count
or mypy result differs from the above, **stop and report** rather than proceeding — a surprise
there means the two branches interact in a way nobody predicted.

---

# PART 2 — CONTEXT YOU NEED

## 2.1 What this phase is for

The itinerary planner currently has **four seeded POIs**. That is a demo, not a product. Real
venue coverage arrives in phase **I3**, which ingests an open-data catalog (Overture Maps +
Wikivoyage/Wikidata + OSM) in offline batch.

I2 is the seam I3 plugs into. Get the types right here and I3 is an ingestion job; get them wrong
and I3 rewrites the planner. Nothing in I2 is user-visible.

## 2.2 Authoritative sources — read these, in this order

1. `docs/superpowers/specs/2026-08-02-itinerary-intelligence-design.md` — **§5** (normalized place
   evidence: stable identity, claim-level provenance, source authority by meaning, freshness
   classes), **§12** (failure and partial-result behavior), **§14 Phase I2**, **§9** (MCP and
   provider policy).
2. `docs/specs/16_data_gateway_and_adapters.md` — **§3** (`EvidenceMeta`), **§6** (adapter
   contract / `AdapterCapabilities`), **§7** (provider registry entry format + the ten-point
   student-profile activation checklist), **§13** (typed gateway errors), **§15** (deterministic
   provider selection order).
3. `CLAUDE.md` — the five non-negotiables and the decision tiers.

Do **not** read all 17 specs.

## 2.3 Conventions the last two phases established — match them

- Timestamps are `pydantic.AwareDatetime`. Never `str`. Naive datetimes are rejected at
  construction.
- Run ownership (`run_id` / `created_by_run`) is explicit and required. No defaults, no `"r1"`.
- Validation lives in **one** shared function reused by both the mutation path and the audit path
  (see `validate_edge_endpoints` in `gateway/evidence/edges.py`). Do not write a second copy.
- Money is integer minor units. No floats cross a boundary.
- Tests are typed: `def test_x() -> None:`.

---

# PART 3 — THE TASKS

**Restate these six task names in your first response before writing code.**

- Task 1 — Place identity and field-level claim provenance
- Task 2 — Search, candidate, and partial-result contracts
- Task 3 — Provider registry and activation-profile checks
- Task 4 — `SamplePlaceAdapter` and sanitized fixtures
- Task 5 — Evidence-graph integration for place claims
- Task 6 — Source/licence manifest, capability reporting, Gate I2, report

Suggested layout (Tier V — adjust if the repo argues otherwise, but say so):

```
backend/gateway/places/
  __init__.py
  identity.py        # PlaceId, external id namespaces
  contracts.py       # Place, PlaceClaim, PlaceSearchRequest, PlaceCandidate, PartialPlaceResult
  registry.py        # ProviderRegistry, AdapterCapabilities, activation checks
  protocol.py        # PlaceProviderAdapter Protocol
  manifest.py        # SourceManifest, licence/attribution, capability reporting
  adapters/
    __init__.py
    sample.py        # SamplePlaceAdapter
backend/gateway/places/fixtures/   # sanitized JSON/YAML place fixtures
backend/evals/
  test_place_contracts.py
  test_place_registry.py
  test_place_sample_adapter.py
  test_place_evidence_integration.py
  test_place_manifest.py
```

---

## Task 1 — Place identity and field-level claim provenance

**Design §5.1–§5.2 is the authority.** Two ideas drive everything:

**(a) Names are never primary keys.** Every place has an internal `PlaceId` plus a set of
namespaced external identifiers: `overture:...`, `osm:node/...`, `osm:way/...`,
`osm:relation/...`, `wikidata:Q...`. Identity resolution is deterministic and reversible. An
automatic merge requires an exact shared external identifier, or a named rule combining
normalized name + category + distance within a category-specific threshold. **Ambiguous matches
stay separate** and surface for review. No fuzzy-name-only merging, ever.

**(b) A place is assembled from claims, not one mutable blob.** Coordinates, category, opening
hours, description, accessibility and admission are **separate claims**, because the best source
and the freshness policy differ per field. Each claim carries:

`source_id`, `source_url`, `retrieved_at`, `source_release`, `last_verified`, `verified_by`,
`confidence`, `needs_verification`, `licence_id`, attribution requirements, and lifecycle state
(active / stale / superseded).

Freshness policy per field (design §5.4) — encode this, do not leave it to prose:

| Claim class | Policy |
|---|---|
| identity / coordinates | snapshot-versioned; revalidate on source refresh |
| category / basic tags | snapshot-versioned; warn on stale source release |
| editorial description | long-lived, but always attributed |
| opening hours / accessibility | time-sensitive; stale or absent becomes `verify_required` |
| admission / reservation | time-sensitive; official-source-only for trusted status |

**Unknown hours never become "open."** That rule already cost this project a round of rework in
I1 — see §5.4 and the I1 report.

Tests: external-id namespace validation; two places sharing an exact external id merge; two
places with similar names but no shared id do **not** merge; ambiguous match is retained as
ambiguous rather than silently resolved; each claim class carries full provenance; a claim with
missing `licence_id` is rejected.

**Commit:** `feat(gateway): add place identity and claim provenance contracts`

---

## Task 2 — Search, candidate, and partial-result contracts

`PlaceSearchRequest` is **bounded by construction** — it cannot express an unbounded query. Carry
at minimum: destination/area scope, category filters, an explicit `max_results` with a hard
ceiling, and the request's own budget context. Adapters may **never** broaden scope beyond the
explicit request (spec 16 §4).

`PlaceCandidate` is what leaves the gateway: stable `PlaceId`, the assembled claims with
provenance, completeness flags, and `EvidenceMeta`-equivalent status
(`live` / `cached` / `estimated` / `stale` / `verify_required`). **No raw provider object ever
escapes the adapter** — assert this in a test.

`ItineraryDraft` / `ItineraryValidation`: the design lists these as I2 contracts, but **I1 already
built `ComposerResult` and `ScheduleWarning` in `backend/core/itinerary/compose.py`.** Do not
invent a parallel shape. Read what I1 produced first, then define the gateway-side contract to
match it, or document precisely why it cannot. A duplicated itinerary type is a drift vector.

Partial results (design §12): when a budget is exhausted or evidence is missing, return a
**typed** partial result carrying unresolved needs and a stop reason. *"Partial results remain
structured. Fluent prose must never disguise missing evidence."*

Tests: request with `max_results` above the ceiling is rejected; adapter broadening scope is
rejected; `PlaceCandidate` round-trips through JSON with provenance intact; a raw provider dict
cannot be constructed as a `PlaceCandidate`; partial result carries a non-empty stop reason.

**Commit:** `feat(gateway): add place search and partial-result contracts`

---

## Task 3 — Provider registry and activation-profile checks

Registry entries are **static configuration reviewed in source control** (design §9). Format is
spec 16 §7. `AdapterCapabilities` already exists in spec 16 §6 with `"poi"` in its `domains`
literal — reuse that shape.

Non-negotiables, each needing its own test:

- **Every provider is `enabled: false` by default.** Installation never activates an adapter.
- Selection requires the entry's `allowed_profiles` to contain the **active** profile
  (`student_noncommercial`). A `commercial_production`-only entry is rejected under the active
  profile.
- Selection order is deterministic (spec 16 §15): enabled and eligible → supports requested
  domain/country → remaining quota/budget → configured priority → lexicographic `provider_id`.
- **The orchestrator never asks an LLM which provider to call.** No provider name, no raw
  provider tool, and no arbitrary URL ever enters model context.
- An adapter declaring a domain it does not implement returns a typed `unsupported_domain` error.

Typed errors come from spec 16 §13: `provider_unavailable`, `authentication_failed`,
`permission_denied`, `rate_limited`, `budget_exhausted`, `timeout`, `invalid_response`,
`no_results`, `unsupported_domain`, `region_restricted`, `terms_disabled`.

Tests: disabled entry is never selected; wrong-profile entry is rejected; selection order is
deterministic across shuffled registry input; unknown `provider_id` raises rather than falling
back silently; `SamplePlaceAdapter` is the only entry enabled by default.

**Commit:** `feat(gateway): add place provider registry and activation checks`

---

## Task 4 — `SamplePlaceAdapter` and sanitized fixtures

The complete, always-available fallback. Spec 16 §7 lists `SampleAdapter` as **required and
enabled by default**; this is its place-domain sibling.

- Implements the `PlaceProviderAdapter` protocol from Task 2.
- Reads local sanitized fixtures. **No network. No credential. No HTTP client import.**
- Every emitted candidate carries `status="estimated"`, `needs_verification=True`, and declared
  synthetic provenance. A sample must be impossible to mistake for live evidence — test that.
- **Deterministic:** the same request returns byte-identical results across two runs and across
  process restarts. Test it explicitly.
- Fixtures are hand-authored from the documented schema, small, and sanitized. Do not scrape
  anything. Do not commit a binary.

Tests: end-to-end sample search returns candidates with full provenance; empty result is a
success with zero results, not an error; malformed fixture raises `invalid_response`; two
identical requests produce byte-identical output; adapter makes no network call (assert via the
AST boundary test in Task 6).

**Commit:** `feat(gateway): add SamplePlaceAdapter and sanitized fixtures`

---

## Task 5 — Evidence-graph integration for place claims

Connect place evidence to the I0 graph so that every scheduled stop is mechanically traceable to
a claim.

**Decision you must implement (do not re-litigate):** I0's `EvidenceIdentity` discriminated union
has five kinds — `flight_quote`, `flight_price_observation`, `hotel_quote`, `award_quote`,
`reference_fact`. Add a **sixth**: `PlaceClaimIdentity`, with `kind: Literal["place_claim"]`,
`place_id`, and `field` (e.g. `"coordinates"`, `"opening_hours"`, `"category"`). Field-level
claims need field-level identity, otherwise two claims about *different attributes of the same
place* would resolve as duplicates of each other. Do not overload `ReferenceFactIdentity`.

Then:
- Each place claim becomes a `Claim` node with a `SUPPORTS` edge from its `Source`.
- Itinerary artifacts become `Artifact` nodes with `DERIVED_FROM` edges to the claims consumed.
- Every edge carries `created_by_run` (required since I0 Task 2).
- `check_invariants()` must pass on a graph populated purely from a sample place search.

Tests: a sample search populates a graph that passes `check_invariants()`; two claims about
different fields of the same place do **not** resolve as duplicates; two claims about the same
field of the same place from different sources **do** compare; the graph round-trips through
`SqliteEvidenceStore` with place claims intact; every scheduled stop resolves to a claim.

**Commit:** `feat(gateway): attach place claims to the evidence graph`

---

## Task 6 — Manifest, capability reporting, Gate I2, and report

**Source/licence manifest** (design §11 — *"Attribution is data, not footer prose added at the
end"*). The schema records, per input: URL, licence, release/revision, checksum, retrieval date,
geographic scope, allowed purpose, and attribution text. Preserve the original source partition
and licence metadata per record. Do **not** merge differently-licensed payloads into an opaque
export that makes attribution impossible.

**Capability reporting:** which regions and venue categories are actually covered, with honest
`unsupported` / `partial` states. A region with no catalog reports as unsupported — it never
silently falls back to Singapore assumptions.

**AST boundary test** (extend `backend/evals/test_evidence_boundary.py` or add a sibling): walk
`backend/gateway/places/**/*.py` and fail on imports of `requests`, `httpx`, `urllib.request`,
`socket`, MCP SDK modules, or project secret/config loaders. Parse with `ast`, do not grep.

### Gate I2 — run every command, paste every output

```bash
cd <worktree>/backend
.venv/bin/pytest -q
.venv/bin/pytest evals/test_place_*.py evals/test_registry_*.py -q
.venv/bin/mypy --strict core/ agents/ api/ gateway/
.venv/bin/ruff check gateway/places/ evals/test_place_*.py
cd ..
git diff --exit-code -- backend/evals/golden/ && echo "GOLDENS UNCHANGED"
git diff --exit-code -- contract/openapi.json && echo "CONTRACT UNCHANGED"
git diff --check
cmp AGENTS.md CLAUDE.md && echo "BRIEFS IDENTICAL"
git status --short
git log --oneline <merge-base>..HEAD
```

Gate I2 requires (design §14): contract/schema tests pass; registry-deny tests pass; a sample
end-to-end search works; provenance and lineage invariants hold; fixture replay is deterministic;
**no live network**; and **no imports from `backend/core/` to `backend/gateway/`**.

Plus: goldens and `contract/openapi.json` byte-unchanged; `AGENTS.md` and `CLAUDE.md` identical;
tree clean; test count strictly above the merged-main baseline.

### Report

`reports/itinerary_i2_contracts.md`: commit list and behavior per task; test count before/after;
**exact gate output quoted, not paraphrased**; confirmation that no dependency, credential, or
network call was added and `max_cost_minor` is still `0`; the merged-main sha you branched from;
deviations added (or "none"); and the next phase (**I3 — Singapore open-data catalog from
Overture/Wikivoyage/OSM**, the phase that finally replaces the four seeded POIs with real
coverage).

Add an I2-complete checkpoint bullet to **both** `AGENTS.md` and `CLAUDE.md`, identical text,
proven with `cmp`.

**Commit:** `test(gateway): close itinerary I2 contract gate`

---

# PART 4 — DEFINITION OF DONE

I2 is complete when a caller can issue a bounded `PlaceSearchRequest`, receive typed
`PlaceCandidate`s with field-level provenance from a disabled-by-default registry that selected
`SamplePlaceAdapter` deterministically, have those claims land in the evidence graph passing
`check_invariants()`, and get a structured partial result when budget or evidence runs out —
**with no network, no credential, and no change to the public API contract.**

Your final response must contain, in order:

1. The six task names, restated.
2. The merged-main sha you branched from, and the merged baseline test count you measured
   yourself.
3. Per task: what you implemented, commit sha, test count delta — **measured, not assumed.**
4. The full Gate I2 output, pasted raw.
5. One line each: test count increased every task? `git status --short` empty? goldens unchanged?
   `contract/openapi.json` unchanged? briefs identical? no network imports under
   `gateway/places/`?
6. Anything incomplete, stated plainly. **An honest "Task 5's identity union extension is not
   done" is far more useful than a false "complete." You will be checked.**

Do not push, merge, or open a PR. Leave the branch and report.

If a red test fails for a reason you did not predict, stop and diagnose before touching
production code. Do not edit the test to match whatever behavior you happened to get.
