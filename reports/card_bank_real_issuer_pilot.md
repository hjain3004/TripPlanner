# Card-bank real issuer pilot — one HDFC page through the operator workflow

Branch `codex/card-bank-real-issuer-pilot`, based on `main` @ `feec8c7` (origin had not advanced).
Decisions: `DEVIATIONS.md`, section "Card-bank real issuer pilot".

**Status: operator workflow demonstrated end to end on a real capture; nothing approved, nothing
applied to real seeds, no financial fact changed.** The page *confirms* values already in the seeds.
A human approval is still required for the freshly staged proposals (see section 4).
No issuer text is in this report, the repository, or any fixture.

## 1. Working operator behavior

All commands are `python -m ingestion.review_server <command>` from `backend/`, one process each,
state carried by SQLite files in `--data-dir`.

| Step | Command | Result on the real capture |
|---|---|---|
| validate local config | `check-config --source-policies P --watchlist W` | ok, `network_calls: 0` |
| stage | `stage-capture --capture F --source-policy P --watch-target W --extraction E --document-class card_page --captured-at T` | 2 proposals `pending`; `captured_at` recorded as `2026-10-31T05:40:00Z`; `llm_calls: 0`, `network_calls: 0` |
| refusals | same, with a probe extraction | typed, nothing stored: `value_unresolved` (a page value that is not an integer), `value_not_supported_by_quote` (a quote that states no figure) |
| inspect | `inspect --proposal-id ID` | exact quote offsets, every quote `verified`, one finding `manual_capture` |
| list after restart | **`status`** (new) | all 4 proposals, their decisions, and whether each approval still applies |
| bundle | `bundle --seeds-dir S --curator-id C --client-event-id E --proposal-id …` | `b55a245c…f267`, byte-identical to the bundle the 2026-10-31 pilot produced |
| dry-run (twice) | `dry-run --seeds-dir S --bundle-sha256 H` | both entries `confirmed_unchanged`, `kb_constructs: true`, `seed_files_unchanged: true`, outputs `cmp`-identical |
| apply (scratch) | `apply --seeds-dir S …` | `committed`, **ledger-only** (no seed file changes) |
| coverage | `coverage --seeds-dir S` | per row: evidenced, **`awaiting_origin_confirmation`** (new), missing |
| optimizer | `python -m evals.card_bank_optimizer_compare --baseline core/seeds --candidate S --card-id hdfc-infinia` (new) | identical result hash |
| rollback | `rollback --seeds-dir S --apply-id A …` | `rolled_back`; scratch seeds byte-identical (sha256 of every file) |

### Defects found by running the real workflow, and fixed (each with focused regressions)

1. **Capture date.** `stage-capture` stamped the snapshot with the staging time, so a capture saved
   days earlier looked current in the snapshot and `status`. (An applied row's `last_verified` is still the
   decision date, unchanged; `captured_at_source` is shown at staging time only, not stored.) New
   `--captured-at` (ISO-8601 with UTC offset); the outcome reports `captured_at_source`
   (`operator_supplied` / `staging_time` / `stored_snapshot`); naive or future times and claims that
   contradict a stored snapshot, or date a new snapshot before the target's latest, are refused and write nothing. Default unchanged (`staging_time`).
   `evals/test_card_bank_capture_date.py` (7).
2. **No way to find proposals or decisions after a restart** except SQL, and an unknown id printed a
   traceback. New read-only `status`; its `approval_applies` is answered by the existing
   `ActivationPlanner.entry_for` rule rather than a second statement of it. Unknown ids in
   `inspect`/`reopen` are a one-line refusal. `evals/test_card_bank_status.py` (5).
3. **`coverage` read as "nothing happened"** after a ledger-only apply (`evidenced: 0`) because
   evidence only counts once the capture's origin is confirmed (D2, settled policy, unchanged). It
   now lists `awaiting_origin_confirmation`. One test in `evals/test_card_bank_apply.py`.
4. **No way to show the financial consequence** of a change: `evals/card_bank_optimizer_compare.py`
   (no arithmetic of its own; a second test proves a changed fact is *detected*, so "identical" is
   not vacuous). 2 tests.

## 2. The real capture and its age

| | |
|---|---|
| source | one HDFC Infinia product page on the issuer's own domain, saved by the owner by hand in a browser |
| captured | **2026-10-30 22:40 PDT = 2026-10-31T05:40:00Z — five days old when staged (2026-11-04)**. Not current evidence. |
| format | a **plain-text copy** (`text/plain`, 10,280 bytes) of an HTML page. No HTML parser and no PDF library was exercised. |
| hashes | raw `6643d18f…eb3a6`, normalized `ce825ab3…d4d`; unchanged since the prior pilot |
| terms | owner's 2026-10-30 reading of the site's usage terms: personal, non-commercial, local-only, manual capture only. Stored locally; never committed. |
| provenance | `manual_capture`. A manual capture does **not** establish official provenance; no origin confirmation exists for it. |

## 3. Human-authored versus automated

* Human (owner `himanshu`, 2026-10-30/31): saved the page; the source policy and its terms review;
  **approved the two original proposals** (decisions `pilot-card-approve-20261030`,
  `pilot-val-approve-20261030`, curator confidence 0.9).
* Assistant (this task): wrote the extraction file (quotes copied from the capture, **authored by
  the assistant, not model output and not by the owner**), staged it, listed, bundled, dry-ran,
  applied to scratch seeds, rolled back, compared optimizer results. All under the registered
  identity `claude-operator` (in the task-local data copy only), which **never ran `decision` or
  `confirm-origin`**. Nothing was run as `himanshu`.
* The new source policy `hdfc-bank-in-manual-card-page` is the assistant's copy of the owner's policy
  with only the id and allowed class changed. It asserts the owner's review for that class; **the
  owner must confirm** it before relying on anything staged under it.

## 4. Reused approvals versus approval still required

The prior pilot's approvals cover exactly two proposals, identified by policy `hdfc-bank-in-manual`,
target `hdfc-infinia-product-page`, extractor `curator-authored-2026-10-30`. `status` shows both still
apply (base rows unchanged), so the bundle, scratch apply, optimizer run and rollback above used
**those approvals only**.

They do **not** carry to the proposals staged through the reusable CLI. `stage-capture` needs a policy
that allows `card_page`; the old one allows only `manual_capture`, and stored policies/targets are
immutable. The CLI therefore necessarily uses a new policy id, target id, snapshot id (it embeds the
target id), proposal ids and extractor version. Same values, same document hashes, **different
identity, so no approval**. Mechanically: those proposals are `pending` with no decisions.
Origin confirmation (`confirm-origin`) on the original identity is refused
(`origin_not_confirmable: the source policy does not allow page class 'card_page'`).

### Exactly what the human would need to do (not done here)

1. Confirm the policy copy (section 3).
2. `inspect` each new proposal and, only if the quotes are right, `decision … --action approve
   --expected-version 1 --curator-id himanshu` for
   `proposal:hdfc-infinia:snapshot:hdfc-infinia-card-page:…` and
   `proposal:infinia-portal-val:snapshot:hdfc-infinia-card-page:…` (list them with `status`).
3. If they want the capture treated as official: `confirm-origin --document-class card_page` with their
   own statement. Even then the rows stay `needs_verification=true` (section 7).

## 5. Proposed changes versus scratch-applied changes

* **Proposed (staged, pending):** card `hdfc-infinia` — `annual_fee_minor` 1,250,000, `base_earn.points` 5,
  `base_earn.per_amount_minor` 15,000; valuation `infinia-portal-val` — `value_micro_major_per_point`
  1,000,000. Each equals the current seed value (`changed: false`): **no fact changes**.
* **Scratch-applied (original approvals):** the same four values, confirmed unchanged. The apply wrote
  no seed file; it recorded 4 evidence rows in the apply ledger. After rollback the scratch seeds are
  byte-identical (they were also unchanged during the apply). Repository seeds were never written.

## 6. Optimizer result (existing `optimize`, demo trip DEL→SIN, wallet `hdfc-infinia`)

Repository seeds and applied scratch seeds give an **identical** result (full-result SHA-256
`b7e813fc…b52a`): gross 15,300,000; rewards value 1,201,500; forex fees 82,600; effective cost
14,131,100; savings 763 bp (minor units / basis points). Confidence stays 0.5 because provenance is
unchanged. The capture confirms existing numbers; the consequence is none.

## 7. Unresolved fields and blockers

Card `hdfc-infinia` has 12 non-identity fields; evidence exists for 3. Valuation: 1 of 6.

| Field | State |
|---|---|
| `annual_fee_minor` | supported; unchanged. The page states a joining fee and an annual renewal fee (same amount, plus tax); the fee-waiver-on-spend condition is not modeled. |
| `base_earn.points` / `per_amount_minor` | supported; unchanged. The page marks the rate with an asterisk; the exclusions are not in the capture, so which spends earn 5 is **unresolved**. |
| `value_micro_major_per_point` | supported; unchanged (stated for flights and hotels on the page's redemption table). A monthly redemption cap on the page is not modeled by the row. |
| `lounge_intl_visits_per_year` (seed: 12) | **human judgment**: the page says unlimited, an integer field cannot hold it. Staging refuses it (`value_unresolved`). The seed value 12 is therefore contradicted by the page and still unevidenced. |
| `forex_markup_bp`, `forex_markup_tax_bp` | **missing**: the page names a forex-rates link but states no figure. |
| `network` | **missing** from the page. |
| `issuer`, `name`, `country`, `fee_currency`, `base_earn.currency` | not proposed (the page plausibly names several); left unresolved for the human to decide whether to evidence them. |
| valuation `card_id`, `path`, `currency`, `min_points`, `conditions` | not proposed; the stored `conditions` ("assumes SmartBuy portal flights") is not evidenced here. |

Blockers: (1) the capture is 5 days old and manual, with no origin confirmation; (2) D1 requires
evidence for every non-identity field, which this one page cannot supply, so **neither row can be
marked verified from this capture**; (3) real seeds may be written only with the owner's go-ahead and
a format-preserving YAML writer (Phase 4 limit, unchanged); (4) the policy copy awaits owner
confirmation.

## 8. Reproducing it

Real inputs stay outside Git. The script that produced the evidence is local
(`~/tripwise-ingestion-data/real-issuer-pilot-20261104/run-pilot.sh`; not committed because it names
the owner and the page). Its command sequence, with placeholders:

```bash
cd backend
D=/path/to/data-copy          # a COPY of the pilot database directory, never the original
S=/path/to/scratch-seeds      # a COPY of backend/core/seeds, outside any git checkout
python -m ingestion.review_server check-config --source-policies P.yaml --watchlist W.yaml
python -m ingestion.review_server add-curator --data-dir $D --curator-id OPERATOR --display-name "…"
python -m ingestion.review_server stage-capture --data-dir $D --capture FILE.txt \
  --source-policy P.yaml --watch-target W.yaml --extraction E.json \
  --document-class card_page --captured-at 2026-10-31T05:40:00+00:00
python -m ingestion.review_server status --data-dir $D
python -m ingestion.review_server bundle  --data-dir $D --seeds-dir $S --curator-id OPERATOR \
  --client-event-id EVENT --proposal-id ID …
python -m ingestion.review_server dry-run --data-dir $D --seeds-dir $S --bundle-sha256 H
python -m ingestion.review_server apply   --data-dir $D --seeds-dir $S --bundle-sha256 H \
  --curator-id OPERATOR --reason "…" --client-event-id EVENT2
python -m ingestion.review_server coverage --data-dir $D --seeds-dir $S
python -m evals.card_bank_optimizer_compare --baseline core/seeds --candidate $S --card-id hdfc-infinia
python -m ingestion.review_server rollback --data-dir $D --seeds-dir $S --apply-id A \
  --curator-id OPERATOR --reason "…"
```

`TRIPWISE_DATA_DIR` is a *root* (the database is `$TRIPWISE_DATA_DIR/ingestion`); use `--data-dir`
to point at an existing database directory.

Config templates: a policy needs `policy_id, name, owner, domain, source_url, terms_url,
terms_read_on, automated_access_permitted: false, manual_only: true, allowed_page_classes: [card_page],
retention_policy, reviewed_on, reviewed_by`; a watch target `target_id, url, kind: manual_capture,
target: [row ids], source_policy_id, check_frequency_days, backend: manual, manual_only: true`; an
extraction `schema: tripwise.curator-extraction/v1, curator_id, records: [{table, id, field_path,
raw_value, quote}]`. The quote must be an exact substring of the stored text.

## 9. Verification

Execution mode: real SQLite, real CLI processes, real stored data; no network, model call,
credential or spend. Full backend suite on the working tree: **3070 passed, 53 skipped** (3055 baseline +
15 new; the 53 skips are the known optional-PDF-library cases and the CP1 merge-base guard, none
regional-catalog). The unchanged `make gate` result on the exact committed tree is recorded in the task's final response.

**Independent review** (one read-only reviewer; code and facts only, no issuer text): no Critical or
Important findings; it reproduced the idempotent/refusal paths of `--captured-at`, that `status` does
not write (database bytes identical before and after), and that `approval_applies` is false for a
changed base row, no decision, and a different target identity. Four Minor findings: (1) the
`--captured-at` claims overstated reach: an applied row's `last_verified` is the decision date, so the
docstring, DEVIATIONS and this report were reworded; (2) a new snapshot could be dated before the
target's latest one: now refused (`captured_at_conflict`) with a test; (3) `captured_at_source` is
reported at staging time but not stored: documented, not changed; (4) `approval_applies` uses the
existing bundling rule, which checks row hashes and does not re-hash stored snapshots, so someone with
direct database write access could alter stored evidence text after approval without `status`
noticing: documented in the module docstring, not changed (not a regression; a hardening candidate).

The task's first working directory under `/private/tmp` (including the lockfile-pinned venv and the
first pilot copy) disappeared mid-task. The venv was rebuilt from the hashed lockfile (mypy 2.4.0,
ruff 0.17.1) and the pilot re-run from the untouched originals; the second run reproduced the same
bundle hash. The originals were re-hashed afterwards and are unchanged.

## 10. Not done / limits

No origin confirmation, approval, or seed write was made by the assistant. One page, one issuer, two
rows: nothing here says anything about other issuers or pages. The extraction is assistant-authored
from a plain-text copy; HTML parsing and PDF handling were not exercised on real input in this task.
