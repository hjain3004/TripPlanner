# Independent discrepancy audit — Codex

**Date:** 2026-08-17  
**Scope:** Runtime behavior versus claims. No implementation work was performed.  
**Branch observed:** `feat/i8a-tripadvisor-offline-adapter`

## Method and independence note

I read `CLAUDE.md`, `DEVIATIONS.md`, the newest milestone reports, and the implementation protocol, then ran the gate and drove the real catalogs, planner fallback, estimator, recompute path, place search, and live API. I did not execute or read the R1 plan.

The project explicitly asked that `reports/audit_findings_claude.md` remain unopened until this report was written. I did not intentionally open that file. However, after the runtime probes below had already reproduced the live-model and fallback failures, one broad `rg` command accidentally included that path and exposed two short fragments: one containing “treating it as a fallback” and one saying the 8B planner fell back in every scenario. No surrounding finding, evidence, severity, or diagnosis was read. Findings below are based on commands I ran independently; the accidental exposure weakens strict independence only for the already-reproduced fallback observation and is disclosed rather than hidden.

## Baseline

I ran the complete backend gate with the environment loaded:

```text
$ cd backend && source .env && cd .. && PYTHONDONTWRITEBYTECODE=1 make gate
592 passed, 4 warnings in 64.52s
Success: no issues found in 92 source files
All checks passed!
GOLDENS_OK
CONTRACT_OK
BRIEFS_IDENTICAL
Uncommitted changes detected:
?? docs/superpowers/plans/2026-08-16-r1-interest-aware-retrieval.md
?? reports/audit_findings_claude.md
make: *** [gate] Error 1
```

The test/type/lint/contract portions pass. The final clean-tree check fails only because the two user-supplied audit inputs are untracked; that is an audit-environment condition, not a product defect.

The catalogs are genuinely substantial rather than four-row fixtures:

```text
$ du -sh backend/catalogs && ...count places and coordinates...
131M    backend/catalogs
bom places 21196 coord_claims 21196 unique_coords 20725
dxb places 15346 coord_claims 15346 unique_coords 14906
lon places 46502 coord_claims 46502 unique_coords 45989
nyc places 56172 coord_claims 56172 unique_coords 53382
par places 35157 coord_claims 35157 unique_coords 34854
sg  places 28540 coord_claims 28540 unique_coords 28112
```

The failures below are downstream behavior over those catalogs, not absent data.

## Findings

### C1 — The configured live product cannot pass intake, and the documented fallback model does not exist in the client

**What I ran**

I started the real API after explicitly sourcing `backend/.env`, confirmed health, submitted a DEL→LON request, and polled the job:

```text
$ curl http://127.0.0.1:8000/health
{"status":"ok"} HTTP 200 total=0.005826s

$ curl -X POST http://127.0.0.1:8000/plan ...
{"job_id":"<job id>"} HTTP 202

$ curl http://127.0.0.1:8000/plan/<job id>
{
  "status":"needs_clarification",
  "stage":"intake",
  "unresolved":[
    "intake failed: intake provider returned HTTP 404: model `llama-3.3-70b-versatile` does not exist or you do not have access to it ... model_not_found"
  ]
}
```

I then inspected configuration without printing the secret:

```text
model llama-3.3-70b-versatile
base_host api.groq.com
key_present True
```

**What the project claims instead**

`CLAUDE.md` says `HostedFreeTier` uses `llama-3.3-70b-versatile` on Groq with `llama-3.1-8b-instant` as a fallback. The runtime has one configured model and no fallback-model path. It retries selected transient failures, but a provider `404 model_not_found` becomes an intake failure. The API then presents infrastructure failure as user-facing `needs_clarification`, even though no user clarification can repair it.

**Severity: Critical.** With the checked-in/current local configuration, the live product produces no plan at all. The error state also asks the user to solve the wrong problem.

**Test that should have caught it**

An API smoke test using the configured model list, or a provider-contract test for `404 model_not_found -> configured fallback`, should fail. `test_hosted_llm_client.py` mocks a successful single model plus generic HTTP/timeout errors; it never tests model selection, model availability, fallback, or API error-state semantics. Replay tests deliberately cannot detect provider model retirement.

**Classification:** genuine defect and claim–reality mismatch.

---

### H1 — Interests are effectively a no-op for five of six real catalogs, and fallback itineraries are identical across incompatible interests

**What I ran**

I retrieved against each active catalog with `food` and `architecture`, recording exact tag overlap and the first five IDs:

```text
SIN same_top5=False
  food overlap=1; architecture overlap=0
BOM same_top5=True
  food overlap=0; architecture overlap=0
DXB same_top5=True
  food overlap=0; architecture overlap=0
NYC same_top5=True
  food overlap=0; architecture overlap=0
LON same_top5=True
  food overlap=0; architecture overlap=0
PAR same_top5=True
  food overlap=0; architecture overlap=0
```

For example, London returned the same IDs and tags for both requests:

```text
food         ['pl_0823...', 'pl_0880...', 'pl_0ff3...', 'pl_122a...', 'pl_1542...']
             ['park', 'restaurant', 'restaurant', 'attraction', 'attraction']
architecture ['pl_0823...', 'pl_0880...', 'pl_0ff3...', 'pl_122a...', 'pl_1542...']
             ['park', 'restaurant', 'restaurant', 'attraction', 'attraction']
```

I then forced the documented deterministic fallback with the same London trip:

```text
food fallback True hotel_area unknown items 32
  first8 ['pl_f7d4...', 'pl_e72f...', 'pl_156d...', 'pl_0823...', ...]
architecture fallback True hotel_area unknown items 32
  first8 ['pl_f7d4...', 'pl_e72f...', 'pl_156d...', 'pl_0823...', ...]
same_itinerary True
```

The mechanism matches the observation: the snapshot adapter selects and truncates the 40 nearest-to-centroid rows before `retrieve_candidates` performs exact tag-overlap sorting. The user vocabulary (`food`, `architecture`, `culture`, `nature`) does not match the real catalog vocabulary (`restaurant`, `cafe`, `food_court`, `attraction`, `museum`, `park`). Singapore appears slightly better only because its four hand-written seed POIs still carry the old user-facing tags.

**What the project claims instead**

Spec 08 describes an itinerary curator that builds realistic days around “location, time, and interests.” The intake and UI collect interests as meaningful planning input. For five real regions, changing a trip from food to architecture does not change retrieval or fallback output.

**Severity: High.** This is a central personalization promise, and the product returns plausible-looking but semantically unchanged plans.

**Test that should have caught it**

A real-catalog metamorphic test should assert that materially different interests alter relevant candidates and itinerary composition, with minimum semantic relevance. The current retrieval tests assert seeded Singapore IDs, non-empty output, provenance, and regional separation. The autouse test fixture disables real catalogs unless a test opts in, and the real-catalog tests do not assert interest relevance. Therefore the test named for retrieval can pass while retrieval ignores the user’s interests.

**Classification:** genuine defect; scaffolding that outlived its use.

---

### H2 — “Sub-second” recomputation is 4.8 seconds for only three retained London items

**What I ran**

I built a four-item itinerary from actual London catalog IDs, removed one item, and called the deterministic recompute function:

```text
ids ['pl_0823eccfbd9a7d15', 'pl_0880896b676635c6',
     'pl_0ff3c81505cbe793', 'pl_122a7ae35f9a9f02']
recompute_seconds 4.803 remaining_items 3 gross_minor 0 budget_supported False
```

Direct lookup showed why:

```text
lookup 1 seconds=1.273 Statue of King Charles I
lookup 2 seconds=1.158 Statue of King Charles I
lookup 3 seconds=1.302 Statue of King Charles I
```

Every `get_catalog_poi` call constructs a fresh snapshot adapter and parses the full catalog. The estimator calls it for itinerary items, producing linear repeated full-file loads. A broader multi-city estimator probe exceeded one minute and was interrupted inside `PlaceClaim.model_validate` during another catalog load.

**What the project claims instead**

`reports/f5_editable_itinerary.md` records approximately 350 ms and `CLAUDE.md` calls `POST /plan/recompute` “sub-second.”

**Severity: High.** An edit interaction designed as instant recomputation is already roughly 9.6× over the `<500 ms` test target for just three remaining real POIs; realistic 20–30-item plans amplify the problem.

**Test that should have caught it**

`test_recompute_latency_under_500ms` should have caught exactly this. It uses synthetic `poi:*` IDs while the global autouse fixture says “Prevent tests from loading the real 161MB catalog by default” and replaces `active_catalog_path` with `FileNotFoundError`. The latency gate consequently measures the old seed-only path, not the production catalog path.

**Classification:** genuine defect and claim–reality mismatch.

---

### H3 — A schema-valid empty-card wallet crashes recomputation

**What I ran**

I repeated the real London recompute with `UserWallet(card_ids=[])`, which the Pydantic model accepts and other itinerary tests use:

```text
Traceback (most recent call last):
  ... recompute_itinerary -> run_kernel -> optimize -> allocate
  ... core/optimizer/allocate.py, line 277, in _allocate_core
    best_full = min(full_opts, key=lambda o: rank_key(o, prefs))
ValueError: min() iterable argument is empty
```

Adding `hdfc-infinia` makes the same call complete (in 4.803 seconds), proving the crash is the empty-wallet path rather than the itinerary.

**What the project claims instead**

Spec 08 says users select cards they own and enter balances optionally; the public `UserWallet` contract permits an empty list. The system’s cash-travel planning path should not become an unhandled error merely because a user owns or selects no supported reward card.

**Severity: High.** A valid request reaches an unhandled exception in the deterministic kernel/recompute API.

**Test that should have caught it**

An optimizer property test and recompute endpoint test with `card_ids=[]` should assert either a cash/default allocation or a typed validation response. It did not because optimizer/recompute tests use at least one card; tests with empty wallets stop at itinerary composition and never execute allocation.

**Classification:** genuine defect.

---

### M1 — Most activity-picker category chips are no-ops against the real taxonomy

**What I ran**

I drove the actual local place search over the Singapore catalog using both UI vocabulary and catalog vocabulary:

```text
all         5 ['restaurant', 'cafe', 'cafe', 'restaurant', 'restaurant']
attractions 0 []
attraction  5 ['attraction', 'attraction', 'attraction', 'attraction', 'attraction']
nature      2 ['nature', 'kids']
park        5 ['park', 'park', 'park', 'park', 'park']
landmark    2 ['nature', 'landmark']
food        1 ['food']
restaurant  5 ['restaurant', 'restaurant', 'restaurant', 'restaurant', 'restaurant']
culture     0 []
museum      5 ['museum', 'museum', 'museum', 'museum', 'museum']
other       0 []
```

The UI offers exactly `all`, `attractions`, `nature`, `landmark`, `food`, `culture`, and `other`. Thus `attractions`, `culture`, and `other` return nothing; `food`, `nature`, and `landmark` expose only legacy seed rows while hiding the relevant real catalog categories.

**What the project claims instead**

F5.1 reports a category-filtered activity picker. The controls render and requests succeed, but most filters either empty the picker or omit nearly all matching real venues.

**Severity: Medium.** The feature visibly fails but can be bypassed using “all” and text search.

**Test that should have caught it**

Each rendered chip should have an integration test over an activated catalog asserting relevant non-empty results. The sole backend filter test requests legacy `food` and only checks that every returned row equals `food`; it does not assert the result set is non-empty, so even `[]` passes. Frontend E2E tests do not exercise the chips’ result branches.

**Classification:** genuine no-op feature; scaffolding that outlived its use.

---

### M2 — Exact venue search exposes unresolved duplicates and can rank the wrong venue first

**What I ran**

I searched prominent real venues through the same search function used by the picker:

```text
LON Buckingham Palace count 5
  Buckingham Palace | attraction | 51.472943 -0.205135 | verify_required
  Buckingham Palace | museum     | 51.4995091 -0.12493841 | verify_required
  Buckingham palace | cafe       | 51.49287773 -0.1937894 | verify_required
  Buckingham Palace | attraction | 51.49486233 -0.14622707 | verify_required
  Buckingham Palace | attraction | 51.507191160113116 -0.1285437347862065 | verify_required

NYC Metropolitan Museum count 5
  Metropolitan Museum | museum | 40.648457767665946 -73.79085586122585 | verify_required
  Metropolitan Museum | museum | 40.79431193891246 -73.94302017001124 | verify_required
  Metropolitan Museum Historic District | museum | 40.779091 -73.962703 | verify_required
  Metropolitan Museum of Art | museum | 40.77002154344195 -73.96007699900005 | verify_required
  Metropolitan Museum-Art Store | museum | 40.864927 -73.931353 | verify_required
```

The first New York result is near JFK rather than the Metropolitan Museum of Art. Buckingham Palace appears five times, including a café and disparate coordinates. Mumbai “Gateway of India,” Dubai “Burj Khalifa,” and Paris “Louvre” showed the same duplicate/variant pattern in the broader probe.

**What the project claims instead**

Spec 08 says external candidates are normalized and de-duplicated. The identity-resolution milestone report claims identity resolution, but the active search surface still returns multiple unresolved real-world identities for an exact venue request.

**Severity: Medium.** The wrong venue can be selected, but every affected result is honestly labeled `verify_required`; that trust state prevents this from being High/Critical.

**Test that should have caught it**

A real-catalog exact-search benchmark should pin canonical prominent venues, distance plausibility, and duplicate clusters. Existing identity tests use constructed claims and retrieval tests merely require unique internal place IDs. Different IDs for the same venue therefore satisfy the tests.

**Classification:** genuine defect and claim–reality mismatch.

---

### M3 — Five regional catalogs have no planning areas; every mapped catalog POI is `Unknown`

**What I ran**

I printed retrieval-area counts and unique mapped POI areas from every active region:

```text
SIN areas 4 unique_poi_areas ['Unknown', 'chinatown']
BOM areas 0 unique_poi_areas ['Unknown']
DXB areas 0 unique_poi_areas ['Unknown']
NYC areas 0 unique_poi_areas ['Unknown']
LON areas 0 unique_poi_areas ['Unknown']
PAR areas 0 unique_poi_areas ['Unknown']
```

The fallback run correspondingly returned `hotel_area unknown` for London. Catalog candidate mapping assigns `area="Unknown"` unconditionally; only the old Singapore database seeds contribute actual area rows.

**What the project claims instead**

Spec 08 says days are built around location, time, and interests. Six-region catalog rollout is complete, but location grouping still depends on Singapore-only seed scaffolding rather than catalog geography or regional areas.

**Severity: Medium.** Coordinates still allow geodesic routing, so the itinerary is not completely location-blind; however area selection, area prompts, and hotel-area semantics are absent for five regions.

**Test that should have caught it**

A rollout test should require non-empty area context and non-`Unknown` area coverage per region. Current regional tests assert non-empty candidates, city isolation, IDs, and provenance, but do not assert area semantics.

**Classification:** scaffolding that outlived its use and claim–reality mismatch.

---

### M4 — Every real-catalog restaurant/café is costed as an attraction

**What I ran**

I selected a restaurant/café candidate from each real retrieval result and passed it through the estimator’s category mapping:

```text
SIN ('Astons Specialties', ['restaurant'], 'attractions')
BOM ('Lower Parel', ['restaurant'], 'attractions')
DXB ('24th Street World Street Food', ['restaurant'], 'attractions')
NYC ('Variety Coffee Roasters', ['cafe'], 'attractions')
LON ('Gaardz Chicken & Dessert', ['restaurant'], 'attractions')
PAR ('Sushi Shop BHV', ['restaurant'], 'attractions')
```

The estimator recognizes only the legacy tag `food`; the regional catalogs use `restaurant`, `cafe`, and `food_court`.

**What the project claims instead**

The deterministic kernel’s role is correct card/offer/payment optimization by spend category. Treating restaurant spend as attractions would apply the wrong earning/offer rules once real POI price evidence is attached.

**Severity: Medium.** Current catalog POI amounts are zero, so today’s totals are not numerically changed. It is a dormant but certain correctness failure as soon as paid venue/meal evidence is populated.

**Test that should have caught it**

An estimator taxonomy contract test should cover every supported catalog category and assert `restaurant/cafe/food_court -> dining`. Current estimator tests use the old four seeded POIs, including a literal `food` tag, so they preserve the obsolete vocabulary.

**Classification:** genuine defect; scaffolding that outlived its use.

---

### L1 — `CLAUDE.md` reports a dirty pre-commit checkpoint that is no longer true

**What I ran**

```text
$ git branch --show-current && git status --short && git log -5 --oneline
feat/i8a-tripadvisor-offline-adapter
?? docs/superpowers/plans/2026-08-16-r1-interest-aware-retrieval.md
?? reports/audit_findings_claude.md
a898d16 docs: record F5.1 and Tripadvisor adapter milestones
f2fc910 feat(frontend): harden editable itinerary interactions
8247521 feat(backend): add hardened itinerary place discovery
...
```

**What the project claims instead**

The current checkpoint says the worktree contains uncommitted F5.1/I8A/I8A.1/I8A.2/I8A.2.1 work. Those changes are now in three commits; only the audit inputs are untracked.

**Severity: Low.** It misleads the mandatory session-start recovery process but does not affect runtime behavior.

**Test that should have caught it**

No product test should inspect prose about Git. The brief needs a release/checkpoint update step when milestone commits are created.

**Classification:** claim–reality mismatch.

## Items audited and found intentional-and-fine

1. **Unsupported non-Singapore budgets.** Mumbai/Dubai/New York/London/Paris produce explicit `budget_supported=False`, known gaps, and zero-valued POI lines rather than invented FX/per-diem prices. I7 documents that behavior. It is incomplete product coverage, but it is honest and safer than manufacturing financial facts. Do not “fix” it by adding guessed numbers.
2. **Single-file active catalogs.** The tiled format exists while active catalogs remain compacted single files. `CLAUDE.md` already lists this as an open finding. The performance consequence is real (H2), but the existence of single files is not an undisclosed discrepancy by itself.
3. **Missing opening hours and broad `attraction` taxonomy.** I7 explicitly discloses both limitations. They need future data-quality work, but repeating them as newly discovered audit defects would pad this report.
4. **Trust state on ambiguous open-data venues.** M2’s search quality is poor, but the system does not falsely label those records live: every reproduced duplicate was `verify_required`. Provenance/trust rendering is doing useful work here.

## Recommended priority before reconciliation

1. Restore an actually usable live model path and distinguish provider failure from user clarification (C1).
2. Make retrieval and fallback semantically interest-aware over the real taxonomy (H1); this should include the vocabulary contract implicated by M1 and M4.
3. Remove repeated full-catalog parsing from recompute and place lookup, then enforce latency with real-catalog tests (H2).
4. Define and test empty-wallet behavior at the optimizer boundary (H3).
5. Resolve UI category vocabulary, regional area semantics, and exact-venue ranking/deduplication (M1–M3).
6. Refresh the checkpoint prose (L1).

No production files were changed and no plan was executed as part of this audit.
