# Itinerary I0 — Code Review Fixes

**Date:** 2026-08-11
**Branch:** `feat/i0-evidence-hardening` (worktree
`/Users/himanshu_jain/TripPlanner/.worktrees/itinerary-i0-evidence-hardening`)
**Current HEAD:** `e082d34`
**Status:** Gate I0 passes — 196 tests, mypy clean, ruff clean — **and the code is still wrong.**
A read-only review found three Critical and three Important defects, all in code the gate
declared good.

**Do not merge this branch until every item below is closed.**

---

# PART 0 — THE ONE RULE THAT MATTERS HERE

## 0.1 Every fix starts with a test that fails on `e082d34`

This is a **fix** task, not a build task, and it has its own failure mode: changing code until a
test passes, when the test never exercised the bug in the first place.

That is not hypothetical. It is exactly what happened here:

- **C1's migration test passes** because it hand-writes `PRAGMA user_version = 1` — a state the
  real v1 code *never produced*. The test validates a fiction. The real code path crashes.
- **I2's symmetry fix has no test that would fail without it.** The existing cases use values so
  far over threshold that the divisor is irrelevant. The fix is currently unverified.

So, for every item:

1. Write the regression test **first**.
2. Run it against the current code. **Paste the failure output.** If it passes, your test does
   not reproduce the defect — rewrite the test, do not proceed.
3. Fix the production code.
4. Run it again. Paste the pass.

**A fix without a pasted red-then-green pair is not accepted.** If you cannot make a test fail
first, say so explicitly and explain why rather than quietly moving on.

## 0.2 Hard rules

1. **Never weaken a test to make it pass.** If an existing test blocks a correct fix, the test
   was wrong — say so, in the commit message, with the reason.
2. No scripts that patch source files. Edit directly. Delete temp files before committing.
3. Gate commands are literal. No narrower substitutes.
4. "Fixed", "passing", "clean" appear only adjacent to pasted raw output.
5. `backend/evals/golden/` and `contract/openapi.json` must not change.
6. No network, no credential, no HTTP client import. `max_cost_minor` stays `0`.
7. One commit per item (C1, C2, C3, I1, I2, I3, minors). Commit before starting the next.
8. Test count must **increase** with every item except the minors cleanup.

## 0.3 Per-item closing protocol — paste raw output

```bash
cd /Users/himanshu_jain/TripPlanner/.worktrees/itinerary-i0-evidence-hardening/backend
.venv/bin/pytest -q 2>&1 | tail -3
.venv/bin/mypy --strict core/ agents/ api/ gateway/ 2>&1 | tail -2
.venv/bin/ruff check gateway/evidence/ evals/test_evidence_*.py evals/conftest.py 2>&1 | tail -2
cd ..
git status --short
git log --oneline -1
```

If `.venv` is missing in the worktree, use `/Users/himanshu_jain/TripPlanner/backend/.venv/bin/…`.
If tests fail with `no such table: cards`, copy the fixture:
`cp /Users/himanshu_jain/TripPlanner/backend/core/tripwise.sqlite <worktree>/backend/core/`.

---

# PART 1 — THE THREE CRITICAL DEFECTS

## C1 — A real v1 database cannot be opened; the migration is unreachable

**File:** `backend/gateway/evidence/store.py:83-88`

**Root cause, verified:** the v1 store never set `PRAGMA user_version`. Confirm for yourself:

```bash
git show aa08dd4:backend/gateway/evidence/store.py | grep -c user_version   # returns 0
```

So every real v1 database reports version **0**, not 1. The current `_ensure_schema` branches
migration on version 1 — unreachable. Version 0 instead runs `executescript(_SCHEMA_V2)` against
the live v1 tables; `CREATE TABLE IF NOT EXISTS` no-ops, then
`CREATE INDEX idx_edges_run ON edges(created_by_run)` hits the v1 `edges` table, which has
`run_id`. Result, raised from `__init__`:

```
sqlite3.OperationalError: no such column: created_by_run
```

**Why version 0 is ambiguous:** it means *either* a brand-new empty database *or* a real v1
database. You cannot tell them apart from the pragma. **Detect by inspecting the schema**, not
the version number:

- no tables at all → fresh database → create the v2 schema, set `user_version = 2`;
- `edges` table exists and `PRAGMA table_info(edges)` shows a `run_id` column (and no
  `created_by_run`) → genuine v1 → migrate;
- `user_version == 2` and the schema matches → nothing to do.

**Required regression test.** Copy the **actual** v1 schema string out of history —
`git show aa08dd4:backend/gateway/evidence/store.py` — into the test, and build the fixture with
it. **Do not set `PRAGMA user_version`.** That is the whole point: reproduce what the shipped v1
code really produced. Seed at least one source, one claim, and one edge, then open with
`SqliteEvidenceStore` and assert it migrates without raising and preserves every row.

**Also fix the existing test.** `test_v1_store_migrates_without_losing_sources_claims_or_edges`
(`test_evidence_store.py:347`) currently hand-writes `PRAGMA user_version = 1`. Remove that line.
It encodes a state that never existed.

**Commit:** `fix(gateway): detect v1 databases by schema, not user_version`

---

## C2 — Saving a loaded graph silently destroys another run's lineage

**File:** `backend/gateway/evidence/store.py:165-182` and `:220-236`

**Root cause:** `touched_runs` is built from the `run_id` of *every* node in the graph — including
foreign-run nodes that `load()` pulled in via its lineage closure. Then:

```python
conn.execute(f"DELETE FROM edges WHERE created_by_run IN ({run_list})", params)
```

and the same for `resolutions` at `:234`. Only what is in the in-memory graph is re-inserted —
but for a foreign run, the graph holds only the lineage subset, not that run's full edge set.

**Reproduction to encode as your test:** run `r1` owns `s-a→c-a` and an unrelated `s-z→c-z`; run
`r2` owns artifact `a2` derived from `c-a`.

```
r1 edges before: 2
st.save(st.load("r2"))                       # innocuous round-trip
r1 edges AFTER: [('SUPPORTS','s-a','c-a')]   # s-z→c-z destroyed, silently, no error
```

This breaches I0's own binding constraint 5, *"no deletion of lineage."* Claims themselves survive
(they are `INSERT OR REPLACE` only) — edges and resolutions do not, so a reversed resolution
record belonging to a partially-viewed run also vanishes.

**Required fix.** A graph must know which runs it is *authoritative* for — i.e. which runs'
complete edge sets it actually contains. Add to `EvidenceGraph`:

```python
authoritative_runs: set[str] | None = None
# None  -> freshly constructed in memory; every run present is authoritative
# set   -> a partial view; only these runs may be destructively synchronized
```

`load(run_id)` sets `authoritative_runs = {run_id}`. `save()` then:

- **synchronizes** (delete-then-reinsert) edges and resolutions **only** for authoritative runs;
- **upserts without deleting** for every other run present in the graph.

A freshly built graph (`authoritative_runs is None`) keeps today's behavior, so no existing
correct usage regresses.

**Required tests:** the repro above, asserting `r1`'s edges are intact after
`save(load("r2"))`; the same for a reversed resolution owned by a partially-viewed run; and a
positive test that a genuine single-run round-trip *does* still remove an edge deleted in memory
(so the fix does not simply disable synchronization).

**Commit:** `fix(gateway): synchronize only runs the graph is authoritative for`

---

## C3 — The v1→v2 migration is not one transaction

**File:** `backend/gateway/evidence/store.py:91-99`

**Root cause:** `Cursor.executescript()` issues an implicit `COMMIT` before running. So
`BEGIN IMMEDIATE`, the three `ALTER TABLE … RENAME TO v1_*`, and `PRAGMA user_version = 2`
(embedded in `_SCHEMA_V2` at line 26) all commit *before* a single row is copied.

Any later raise — including the legitimate `Cannot uniquely derive run ownership` at line 118 —
rolls back only the inserts. You are left with a database that reports `user_version = 2`, has
empty v2 tables, and has the real data orphaned in `v1_sources` / `v1_claims` / `v1_edges`.
Reopening skips migration entirely, because the version now says 2. **The data is unreachable.**

This is reachable on benign data: an orphan v1 source with zero citing claims makes
`len(s_runs) != 1` true and aborts.

**Required fix.** Do not use `executescript()` inside the migration. Issue individual
`conn.execute()` calls for each `CREATE TABLE` / `CREATE INDEX`, and set `PRAGMA user_version = 2`
as the **last statement inside the same transaction** (`user_version` lives in the DB header and
is transactional).

**Required test:** construct a v1 database that will legitimately fail migration (the orphan
source above). Attempt to open it. Assert that the raise happens **and** that afterwards the
database still reports the pre-migration version, the original tables are intact and populated,
and a second open attempt re-enters migration rather than skipping it.

**Commit:** `fix(gateway): make v1 migration genuinely atomic`

---

# PART 2 — THE THREE IMPORTANT DEFECTS

## I1 — `load()` reconstructs node types by string-prefix sniffing

**File:** `backend/gateway/evidence/store.py:325-329`, `:337-340`, `:412-432`

`load()` guesses whether an id is a claim or an artifact from prefixes (`"c-"`, `"a"`). Nothing in
`nodes.py` enforces id prefixes — `claim_id` is just `Field(min_length=1)`.

So an artifact with `derived_from=["claim-7"]` matches neither prefix, the claim is never loaded,
and `check_invariants()` at `:456` rejects the load with *invariant 4: derived from missing
claim*. **A validly saved graph becomes permanently unloadable.**

**Fix:** resolve node types by **table lookup**, not by id shape — query each table for the id.
(Enforcing a prefix pattern in Pydantic is an acceptable alternative, but table lookup is
strictly more robust and does not constrain callers' id schemes.)

**Required test:** save a graph whose claim ids follow no prefix convention (`claim-7`,
`place/xyz`), with an artifact deriving from one; assert it loads back intact.

**Commit:** `fix(gateway): resolve node types by table, not id prefix`

---

## I2 — The contradiction-symmetry fix is untested

**File:** `backend/gateway/evidence/contradiction.py:72`

The code correctly divides by `min(base, other)`, and `ids = sorted()` makes `left` deterministic.
But `left` is the lexicographically-smaller **id**, not the smaller **value** — so `// base`
versus `// min()` is genuinely behavioral, and **no current test would fail against the un-fixed
code.**

Use these exact values, which straddle the 200 bp cash-quote threshold:

| | `c-1 = 102_010`, `c-2 = 100_000` |
|---|---|
| old `// base` (divides by 102_010) | `2010 * 10_000 // 102_010` = **197** bps → no edge |
| new `// min()` (divides by 100_000) | `2010 * 10_000 // 100_000` = **201** bps → edge |

**Required test:** assert a `CONTRADICTS` edge **is** produced for that pair. Verify it fails
against the old formula — temporarily revert line 72 to `// base`, watch it fail, restore, watch
it pass. Paste both.

**Commit:** `test(gateway): cover contradiction symmetry with a straddling pair`

---

## I3 — `unresolve()` over-deletes edges shared with another resolution

**File:** `backend/gateway/evidence/resolution.py:111-119`

`unresolve()` removes every `RESOLVED_TO` edge with `src in record.members and dst ==
canonical_id`. Because `add_edge` dedupes by key, two resolutions sharing a member *and* a
canonical share a single edge row. Reversing one strips the edge the other still needs, and
`check_invariants()` (`invariants.py:93`) then reports the surviving resolution as *ACTIVE but
missing RESOLVED_TO edge*.

**Fix, both halves:**
1. Before removing an edge, check that **no other ACTIVE resolution** still requires it.
2. Add a guard in `resolve()` preventing a claim from joining a second active resolution — with
   its own test and its own typed error.

**Required tests:** two overlapping resolutions, reverse one, assert the other's edge survives and
`check_invariants()` returns clean; and a claim already in an active resolution being rejected
from a second.

**Commit:** `fix(gateway): unresolve preserves edges other resolutions need`

---

# PART 3 — MINOR CLEANUP (one commit, last)

- `test_evidence_boundary.py:40-48` misses `from urllib import request` — `node.module` is
  `"urllib"`, which is neither in `banned` nor caught by `startswith("urllib.request")`. Fix the
  check and add the case.
- `Claim.kind` and `identity.kind` are never cross-validated, so a `CASH_QUOTE` claim can carry an
  `AwardQuoteIdentity` and `contradiction.py:60` will then compare `total_minor` on award
  evidence. Add a model validator rejecting the mismatch, plus a test.
- `test_evidence_resolution.py:309` (input-order independence) uses two claims identical except
  for id, so it only exercises the `claim_id` tie-break — it would pass with `rank_key` reduced to
  `c.claim_id`. Rank criteria 3 (freshness ladder) and 4 (`Source.retrieved_at`) have **no
  isolating test**. Add one per criterion.
- `test_evidence_contradiction.py:71` asserts a dict key exists and is `> 0` — constrains nothing.
  Strengthen or delete.
- Dead defensiveness: `hasattr(source, "run_id")` (`store.py:178`) and
  `hasattr(identity, "model_dump")` (`resolution.py:51`, `contradiction.py:51`) — all are
  required, non-optional fields. Remove.
- `store.py:213-218` writes resolutions, then `:234` deletes and `:236` rewrites them. The first
  loop is dead work. Remove.
- `store.py:310` re-imports `json` inside a loop; it is already imported at line 9.
- `IN ({q})` construction (`store.py:300`, `:394`, `:404`) will exceed
  `SQLITE_MAX_VARIABLE_NUMBER` on large runs. Add chunking, or document the ceiling in a comment
  and open a follow-up note in `DEVIATIONS.md`.

**Commit:** `chore(gateway): address minor review findings`

---

# PART 4 — GATE AND REPORT

## Re-run Gate I0 in full

```bash
cd /Users/himanshu_jain/TripPlanner/.worktrees/itinerary-i0-evidence-hardening/backend
.venv/bin/pytest -q
.venv/bin/pytest evals/test_evidence_*.py -q
.venv/bin/mypy --strict core/ agents/ api/ gateway/
.venv/bin/ruff check gateway/evidence/ evals/test_evidence_*.py evals/conftest.py
.venv/bin/ruff check gateway/ evals/ 2>&1 | tail -2
cd ..
git diff --exit-code -- backend/evals/golden/ && echo "GOLDENS UNCHANGED"
git diff --exit-code -- contract/openapi.json && echo "CONTRACT UNCHANGED"
git diff --check
cmp AGENTS.md CLAUDE.md && echo "BRIEFS IDENTICAL"
git status --short
git log --oneline aa08dd4..HEAD
```

Expected: all tests pass, total **above 196**; mypy clean on 43 files; I0-owned ruff zero; full
`gateway/ evals/` ruff ≤ 31; goldens and OpenAPI unchanged; briefs identical; tree clean.

## Report

Append a **"Review fixes"** section to `reports/itinerary_i0_evidence_hardening.md` (do not
rewrite the existing content — it is the historical gate record). Include, per item C1/C2/C3/
I1/I2/I3: the defect in one line, the red test output, the fix, the green output, and the commit
sha. Then the full gate block, pasted raw.

Update the I0 checkpoint bullet in **both** `AGENTS.md` and `CLAUDE.md` with the new test count.
Prove with `cmp`.

**Commit:** `docs: record I0 review fixes`

---

# PART 5 — YOUR FINAL RESPONSE MUST CONTAIN

1. The six item names (C1, C2, C3, I1, I2, I3), restated.
2. Per item: the **red** output before the fix, the **green** output after, and the commit sha.
   An item without a pasted red-then-green pair is not done — say so plainly if that is the case.
3. The full Gate I0 block output, pasted raw.
4. One line each: did the test count increase per item? Is `git status --short` empty? Goldens
   unchanged? `contract/openapi.json` unchanged? Briefs identical? I0-owned ruff zero?
5. Anything you could not fix, stated plainly, with the reason. **An honest "C3's atomicity test
   could not be made to fail" is far more useful than a false "fixed". You will be checked, and
   this branch has already been reported complete once when it was not.**

Do not push, merge, or open a PR. Leave the branch and report.

If a red test fails for a reason you did not predict, stop and diagnose before changing
production code. Do not adjust the test to match whatever behavior you happened to get.
