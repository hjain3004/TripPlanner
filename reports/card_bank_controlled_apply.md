# Card-bank Phase 4 — controlled apply and rollback, exercised on scratch seeds

Branch `codex/card-bank-controlled-apply`, stacked on `codex/card-bank-insert-proposals`
(Milestone B), itself stacked on `codex/card-bank-phase2` (Milestone A). **Not independently
mergeable.** Decisions: `DEVIATIONS.md`, section "Card-bank Phase 4".

**Status: see "Verification" at the end; only that section claims a result.**

## Boundary (read first)

* **The repository's real seeds are never written.** `apply` refuses any destination inside the
  repository of the running code (`protected_seeds`) or under *any* git checkout/worktree
  (`inside_git_checkout`), and any seed file that is a symlink; every test and the demonstration
  use a scratch copy; an autouse test hashes the repository seed tree before and after every test.
* **No real financial fact is applied.** All documents are synthetic (`example.invalid`, "SYNTHETIC
  FIXTURE"); nothing says anything about any issuer.
* No credentials, paid service, network, live model call, deployment, booking or transfer. Every
  step is an explicit CLI call by a named curator with a reason; there is no scheduler, hook or
  background path.
* Applying is **not** the FI3 "activation authorized" bit: bundles still say
  `activation_authorized: false` with D1/D2 listed unresolved. The applier resolves D1 and D2 per
  the owner's decisions below, for scratch seeds only.

## Who can do what now

```text
confirm-origin  --seeds-dir S --proposal-id P --document-class C --curator-id U --statement T
apply           --seeds-dir S --bundle-sha256 H --curator-id U --reason R --client-event-id E
rollback        --seeds-dir S --apply-id A --curator-id U --reason R
recover         --seeds-dir S
coverage        --seeds-dir S
```

(plus every earlier command: `stage-capture`, `decision`, `bundle`, `dry-run`, `inspect`, …).

## Design

**D1 — field-level verification** (`verification.py`). `needs_verification` may be cleared only if
every non-identity field holding a value has valid quoted evidence from an approved, applied
decision: the current one, or an earlier *committed* apply whose evidence is still applicable.
Identity is `id` only; `provenance.*` is neither evidence nor required. Earlier evidence counts
only while the field still holds the value it supported; a changed value with no new quote is
reported **stale**; a rolled-back apply's evidence stops counting. Missing fields are listed. A
`None` value asserts nothing and needs no evidence (an interpretation, logged). Partially
evidenced rows stay `needs_verification=true`.

**D2 — manual-origin confirmation** (`verification.py`, `apply_store.py`). Persisted, immutable,
idempotent, by a registered curator, bound to the snapshot id and both content hashes, the target,
policy and document class. Re-checked at apply: issuer domain from the source policy, aggregators
refused, class allowed by the policy and matching the capture's format. A URL inside the captured
text confirms nothing. Without it the row keeps its manual provenance and `needs_verification=true`.

**Apply** (`applier.py`) holds an exclusive per-directory lock throughout and refuses, in order: destination in a repository / not a seed directory;
unknown curator; short reason; replay with different parameters; unfinished earlier operation;
unknown or tampered bundle (hash), non-v2 schema; stale seeds (bundle built against different
bytes); inconsistent dry-run (stale/conflicting/id-conflict/invalid rows, unknown references);
refused entries in the bundle; for each entry — decision no longer the latest attested approval,
unregistered approver, blocking finding (evidence integrity, superseded evidence, id now present),
any difference between the bundle entry and the entry rebuilt from the stored approval (row,
provenance candidate, reviewer, evidence, evidenced fields: a hash-valid forged bundle is refused),
a duplicate row; a resulting KnowledgeBase that does not load; and a rendered file that does not
load back to the approved rows. Only then are the ledger record and the writes made; the writer
re-checks the prior bytes under the lock.

**Safe multi-file write** (`seed_writer.py`): journal → verified backups → verified temp files →
renames one at a time → committed. **Not atomic across files and not claimed to be.** Interrupted
operations are resolved by `recover` (abort, complete, or restore from verified backups); a file
holding neither prior nor new bytes makes recovery refuse. Tested at every checkpoint, including a
crash after the journal committed but before the ledger.

**Rollback**: only a committed apply whose files still hold exactly what it wrote; backups
verified first; journaled and recoverable; history retained; idempotent.

## Demonstration (synthetic; separate processes; scratch seeds)

`python -m evals.card_bank_apply_demo` (also `evals/test_card_bank_apply_cli.py`). Actual output:

```text
== 3. bundle + dry-run (still no authorization to apply)
    entries=[('hdfc-infinia','would_update'), ('synthetic-voyager','would_insert'),
             ('synthetic-voyager-dining','would_insert')]   dry_run_consistent=True activation_authorized=False
== 4. the repository's own seeds are refused as a destination
    refused: protected_seeds: .../backend/core/seeds is inside the repository (...); controlled apply
    only writes to an explicit seed directory outside it (a scratch copy)
== 5. forex fees with hdfc-infinia (existing optimizer, scratch KB): 82600 minor units
== 6. apply apply-9dd416c039beb7d0: committed; files changed: ['cards.yaml', 'reward_rules.yaml']
    cards/hdfc-infinia (update): needs_verification=True, D1 satisfied=False (missing=11), D2=confirmed
    cards/synthetic-voyager (insert): needs_verification=False, D1 satisfied=True (missing=0), D2=confirmed
    reward_rules/synthetic-voyager-dining (insert): needs_verification=True, D1 satisfied=False (missing=5)
== 7. new card synthetic-voyager: dining line earns 2000 points   (Rs20,000 at 10 pts / Rs100)
    hdfc-infinia forex fees: 82600 -> 144550     (markup 2.00% -> 3.50%)
== 8. coverage from the ledger: synthetic-voyager d1_satisfied=True evidenced=11 missing=0 ...
== 9. refused: stale_bundle: the seed files changed since this bundle was built; ...
== 10. rollback: status=rolled_back; byte-identical to before apply: True (54c59974f2799dea == 54c59974f2799dea)
== 11. simulated power cut after the first seed file was replaced
    seeds are now a MIXED set: ['cards.yaml'] changed, the rest not
    refused: incomplete_apply: an earlier apply or rollback on this seed directory did not finish: run recover
    recover: [{'apply_id': 'apply-1318801195ad98e9', 'outcome': 'rolled_back_by_recovery'}]
    byte-identical after recovery: True ;  apply after recovery: committed
== repository seeds byte-identical: True
```

The power cut is injected in-process (the CLI has no way to crash itself); recovery is the real
CLI. A consequence worth stating: only the fully evidenced, origin-confirmed insert cleared
`needs_verification`; the update to an existing placeholder row and the rule with five unquoted
template values did not, which is the intended behavior.

## Tests

`evals/test_card_bank_seed_writer.py` (16): clean apply, exact-byte rollback, every interruption
point, a mixed set observed before recovery, rollback refusal after a later change, corrupt/missing
backups, interrupted rollback, foreign bytes, stacked applies.
`evals/test_card_bank_apply.py` (55): D1 matrix (missing/stale/partial/None/identity/provenance/
combination), D2 (capture, URL, issuer domain, aggregator, class/format, durability, immutability,
curator), apply (insert, update, card+rule+optimizer, partial/full evidence, combine earlier
evidence, stale evidence), refusals (protected seeds, curator, reason, stale, unapproved, forged
row, forged decision id, legacy schema, tampered artifact, id appeared, replay/conflict), rollback,
interruption (every point, via the applier, ledger reconciliation), coverage, reopen.
`evals/test_card_bank_apply_cli.py` (1): the demonstration above through the CLI.
Guard mutation checks (each reverted, each failed the suite): protected-root guard, stale
evidence, D2 requirement (current and earlier evidence), entry rebuild, rollback moved-file guard,
committed-only evidence, stale-seed guard, unfinished-operation guard, write-time prior check,
lock, ledger reconciliation, render check, git-checkout guard, symlink guard, blocking-finding
refusal, evidence scoping, rollback directory check. (The first of these briefly wrote the
real `cards.yaml` because the guard under test was disabled; the autouse test caught it and it
was restored with git before anything was committed.)

## Independent review

A read-only reviewer found no Critical issue and nothing that writes outside the seed directory,
and six Important findings, all reproduced and fixed with regressions: lost update (no write-time
check, no lock); a rolled-back apply's evidence still counting; D2 not following combined
evidence; unverified post-write content (U+0085); forged provenance/reviewer fields in a
hash-valid bundle; a repository guard tied to one checkout. Minor: stuck ledger record after a
crashed recover, evidence-only confirmations lost, evidence not scoped to a seed directory,
unhandled exceptions in the CLI, `rollback --seeds-dir` ignored. It also found overclaims in the
first draft of this report and DEVIATIONS, now corrected. See the last Phase 4 DEVIATIONS rows.

## Not done / limits

* Scratch seeds only; no real seed or fact was or may be applied. Real use needs the owner's
  go-ahead and a format-preserving YAML writer (this one drops in-row comments; the leading
  comment block, row order, ids and values are preserved; rollback restores the original bytes).
* Multi-file writes are recoverable, not atomic; the ledger and the journals are two stores
  reconciled by `recover`, not one transaction.
* One operation at a time per seed directory, enforced by a lock file; a process killed outright leaves it and an operator must remove it (the refusal names the file).
* The injected crashes are exceptions between steps, not power-loss simulation; directories are not fsynced after a rename.
* The non-manual provenance branch is unreachable through `stage-capture` (manual captures only) and untested.
* No UI for confirm/apply (CLI only). Offers are applied like any table but no offer demo exists.
* Synthetic documents only; the real-document demonstration is pending (laptop-only inputs).

## Verification

_To be filled in with the actual runs on the final committed tree._
