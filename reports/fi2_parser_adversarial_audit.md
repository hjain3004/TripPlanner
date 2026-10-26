# FI2 Numeric/Date Parsing — Adversarial Offline Audit

**Type:** Review artifact (read-only audit). **NOT merge-ready, NOT gate-passing.**
The reproduction file `backend/evals/test_fi2_parser_adversarial_audit.py` contains
assertions that intentionally fail on the base commit; those failures are the findings.

- **Base commit:** `c925d98077dd94a1f24d7c312243bfcee78f2d3c`
  (`docs(fi2): correct focused regression count`)
- **Audit branch / worktree:** `codex/fi2-parser-adversarial-audit`, isolated worktree at
  `/Users/himanshu_jain/.codex/worktrees/fi2-parser-adversarial-audit/TripPlanner`,
  created from the exact base commit.
- **Files under audit:** `backend/ingestion/parsing.py`,
  `backend/ingestion/validation.py`, `backend/evals/test_fi2_extraction.py`.
- **Ownership boundary:** Luna owns the production parser fix. This audit changed **no**
  production code, did not modify Luna's FI2 source worktree
  (`codex/fi2-extraction-validation`, verified clean at the same base commit), and made no
  network/provider/credential/spend calls.
- **Runtime:** reproductions executed with the repo's existing offline Python 3.14 venv
  interpreter against **this worktree's** source via `PYTHONPATH`. No dependency changed.

## Grounding — what "correct" means here (not invented)

The audit does not invent financial semantics. The fail-closed expectation is taken
verbatim from existing project artifacts:

1. `reports/fi2_extraction_validation.md` → *"Unsupported or ambiguous notation fails
   closed; the extractor's claimed parsed value is ignored."* and *"Unsupported currencies,
   free-form dates, ambiguous ratios ... remain unresolved rather than guessed."*
2. `backend/evals/test_fi2_extraction.py::test_deterministic_parsers_reject_ambiguous_values`
   — ambiguous notation must raise `UnresolvedValueError`.
3. `backend/ingestion/parsing.py` → `class UnresolvedValueError: "The source notation is
   unsupported or ambiguous."`
4. `backend/ingestion/validation.py` — the only exception caught around
   `parse_field_value` is `UnresolvedValueError`; `FinancialExtractor.extract` catches only
   `ProposalValidationError`. Any other exception type is therefore an uncaught
   contract break, not a handled rejection.
5. Spec `docs/specs/05_ingestion_pipeline_phase2.md §Validator` — the pipeline terminates in
   a human review queue of `pending` proposals; FI2 explicitly stops before any KB write.

**Important scope note on severity.** FI2 produces only immutable, `VERIFY_REQUIRED`
draft proposals for later human review (FI3, unbuilt). No finding below is an end-to-end
knowledge-base write or an autonomous-promotion bypass, and none is claimed as one. The
demonstrated harm is narrower and real: the **deterministic parser's fail-closed guarantee
is defeated**, so a confidently-wrong or crash-inducing value reaches the human review
queue either (a) disguised as a cleanly-parsed number with zero validation findings, or
(b) as an unhandled server-side exception.

## Root cause (one line of code)

`parsing.py::_decimal`:

```python
text = text.replace(",", "").replace(" ", "")
if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
    raise UnresolvedValueError(...)
```

Thousands/space separators are **deleted unconditionally with no grouping validation**,
then the *residue* is checked. `"1,2"`, `"1 2"`, `"1,,234"`, `"100,00"` all collapse to a
bare digit run that trivially matches the regex. The regex validates the *stripped* string,
never the *grouping* of the original.

---

## Findings

### F1 — Malformed comma/space grouping parses to a confidently-wrong amount (HIGH)

- **Source:** commit `c925d98`, `backend/ingestion/parsing.py`, functions
  `_decimal` → `_scaled` → `parse_money_minor` (also reachable via `parse_rate_micro`,
  `parse_basis_points`, `parse_points` which share `_decimal`).
- **Minimal reproduction (helper-only), actual output:**

  | input | `parse_money_minor` returns | a correct parser should |
  |---|---|---|
  | `"INR 1,2"` | `1200` | raise `UnresolvedValueError` |
  | `"INR 1 2"` | `1200` | raise `UnresolvedValueError` |
  | `"12,34"` | `123400` | raise (2-digit group is not a thousands group) |
  | `"1,,234"` | `123400` | raise (double comma) |
  | `"1,2,3,4"` | `123400` | raise |
  | `"100,00"` | `1000000` | raise |
  | `"1 00 000"` | `10000000` | raise |

  Valid grouping is unaffected and still parses (`"INR 12,500"→1250000`,
  `"INR 1,23,456"→12345600` Indian grouping, `"INR 1,234,567"→123456700` international) —
  which is precisely why the bug is dangerous: the parser *looks* grouping-aware but is not.
- **Proposal-path reproduction (with synthetic evidence):**
  `TestActualBehaviour::test_malformed_grouping_reaches_a_pending_proposal_end_to_end`
  drives `"INR 1,2"` through `validate_extraction` with an internally-consistent evidence
  span (exact quote, matching hash, verified artifacts). Result: a **`pending`
  `ChangeProposal` with `proposed_row["annual_fee_minor"] == 1200`, `parsed_value == 1200`,
  and `validation_findings == ()`.** The deterministic re-parse — the layer whose job is to
  ignore the extractor's claimed value — reproduces and blesses the wrong number.
- **Supported expected behaviour & rationale:** malformed grouping is "ambiguous notation"
  and must `raise UnresolvedValueError` (grounding 1–3). `validate_extraction` would then
  convert that to a `ProposalValidationError` ("unresolved value for annual_fee_minor"),
  i.e. `invalid_response`, exactly as it already does for `"12,500 / month"` in the existing
  suite.
- **Severity: HIGH.** Demonstrated effect: a wrong monetary figure enters the human review
  queue with **no finding flagging it**, presented identically to a correctly-parsed value.
  A reviewer clearing "20 proposals in 10 minutes" (spec 05 §6) has nothing to catch it on.
  It is not an autonomous KB write (FI2 stops at review), which is the only reason this is
  not Critical.

### F2 — Oversized numeric string raises an uncaught `decimal.InvalidOperation` (MEDIUM)

- **Source:** commit `c925d98`, `backend/ingestion/parsing.py`, `_scaled`
  (`(value * scale).quantize(...)`) via `parse_money_minor` / `parse_rate_micro` /
  `parse_basis_points`.
- **Minimal reproduction, actual output:** `parse_money_minor("1" * 27)` raises
  `decimal.InvalidOperation` (not `UnresolvedValueError`). The `*100` scale step exceeds the
  default `Decimal` context precision (`prec = 28`). Threshold scales with the multiplier:
  `parse_rate_micro` (`×1_000_000`) crashes at **23** digits; `%`-path basis points
  (`×100`) at **27**. `parse_points` does **not** crash (it never multiplies — uses
  `to_integral_value`), confirming the fault is localized to `_scaled`.
- **Proposal-path reproduction:**
  `TestActualBehaviour::test_long_digits_crash_escapes_validate_extraction` shows the raw
  `InvalidOperation` escaping `validate_extraction` (which catches only
  `UnresolvedValueError` around `parse_field_value`) and therefore `FinancialExtractor.
  extract` (which catches only `ProposalValidationError`).
- **Supported expected behaviour & rationale:** an unparseable/oversized amount must fail
  closed as `UnresolvedValueError` → `invalid_response`, never as an unhandled exception.
  The contract and both call sites only anticipate `UnresolvedValueError`.
- **Severity: MEDIUM.** Demonstrated effect: an uncaught exception from untrusted source
  text / untrusted extractor output — i.e. an availability/robustness defect (an extraction
  run aborts with a traceback instead of a typed `invalid_response`). Distinct from F1: this
  is a crash, not a wrong number. Bounded because inputs are source-page-derived and the
  pipeline is offline/batch.

### F3 — Non-ISO date notation silently accepted despite "ISO YYYY-MM-DD" contract (MEDIUM)

- **Source:** commit `c925d98`, `backend/ingestion/parsing.py`, `parse_date_value`
  (`date.fromisoformat(text)`); routed for fields `valid_from`, `valid_to`, `as_of` in
  `parse_field_value`.
- **Minimal reproduction, actual output:**

  | input | `parse_date_value` returns | note |
  |---|---|---|
  | `"20261026"` | `date(2026, 10, 26)` | basic format, no separators |
  | `"2026-W01-1"` | `date(2025, 12, 29)` | ISO **week-date** — lands in the prior year |
  | `"2026W011"` | `date(2025, 12, 29)` | compact ISO week-date |

  The raised error message itself claims *"dates must use ISO YYYY-MM-DD notation"*, yet
  Python 3.11+ `date.fromisoformat` accepts basic and week-date forms. Confirmed via field
  routing: `parse_field_value("valid_to", "2026-W01-1", expected=None) == date(2025,12,29)`.
- **Proposal-path reproduction:** helper-level and `parse_field_value`-level shown in
  `TestActualBehaviour::test_non_iso_date_notation_is_silently_accepted`. A full
  `validate_extraction` run on a `reward_rules`/`offers` `valid_to` would additionally
  interact with the `expired_value` sanity finding; not separately exercised because the
  helper + routing already demonstrate the confidently-wrong parse, and `cards` (the fixture
  table) has no date field.
- **Supported expected behaviour & rationale:** the parser documents and errors on exactly
  `YYYY-MM-DD`; week-dates and separator-less basic format should fail closed. A week-date
  silently resolving to a date in a *different calendar year* is a confidently-wrong value,
  not merely a lenient format.
- **Severity: MEDIUM.** Demonstrated effect: a wrong effective/expiry date enters the review
  queue; `"2026-W01-1"` differs from any plausible human reading by ~days-to-a-year. Lower
  than F1 only because date fields are less common in the seed tables than money fields.

### F4 — Negative sub-minor amount silently rounds to a non-negative `0` (LOW)

- **Source:** commit `c925d98`, `_scaled` + `_decimal`. `parse_money_minor("-0.004")`
  returns `0` (not a rejection): `_decimal` keeps the sign, `×100 = -0.4`, `ROUND_HALF_UP`
  → `-0` → `int(0)`, and the `result < 0` guard never fires because the rounded result is
  `0`. Genuinely-negative source values `>= -0.005` major units are swallowed as `0`.
- **Supported expected behaviour & rationale:** the code *intends* to reject negatives
  (`_scaled` raises "financial values cannot be negative" for `-100`, `-0.005`). A negative
  value that rounds to zero defeats that intent. Conservative fix direction: check the sign
  of the parsed `Decimal` **before** scaling/rounding.
- **Severity: LOW.** Narrow input window (`(-0.005, 0)` major units) and the outcome is `0`,
  not a large wrong figure; still a correctness gap in the negative-rejection guard.

## Behaviours verified **correct** (fail-closed as intended) — not findings

To distinguish "unsupported-but-rejected" from "confidently-wrong", the following were
probed and correctly raise `UnresolvedValueError`: exponent notation (`"1e3"`, `"1e-2"`),
`"nan"`/`"inf"`/`"Infinity"`, hex (`"0x10"`), Python underscores (`"1_000"`), multi-token
currency (`"INR 100 USD"`, `"USD INR 100"`), bare symbols (`"$100"`, `"100 rupees"`),
Unicode minus `U+2212` (`"−100"`), zero-width/BOM-contaminated digits, `"two percent"`,
`"%5"`/`"bp5"` (missing unit position), non-integer points (`"1000.5"`), and ambiguous
ratios (`"0:1"`, `"1:0"`, `"1:2:3"`, `"1:2.5"`). Booleans/None/`list`/`dict` are rejected by
`_text`. NFKC digit folding (`"١٢٣"`, `"１２３" → 12300`) is intentional per `_text`'s
`unicodedata.normalize("NFKC", ...)` and is **not** flagged as a defect, though it widens the
accepted-input surface and is noted for Luna's awareness.

## Reproduction file

`backend/evals/test_fi2_parser_adversarial_audit.py` (the one allowed test file). Two
classes, **no `xfail`, no weakened assertions**:

- `TestActualBehaviour` — **14 passed**: pins the observed defects (F1–F3), including two
  end-to-end `validate_extraction` reproductions with synthetic evidence.
- `TestSupportedBehaviour` — **10 failed**: each failure encodes the FI2-contracted
  fail-closed behaviour and is a finding a Luna fix must turn green.

### Exact measured outcomes (base commit `c925d98`, offline)

```
backend/evals/test_fi2_extraction.py ...................... 11 passed            # unchanged existing suite
test_fi2_parser_adversarial_audit.py::TestActualBehaviour ... 14 passed          # reproductions confirmed
test_fi2_parser_adversarial_audit.py::TestSupportedBehaviour  10 failed          # the findings:
  test_malformed_grouping_should_fail_closed[INR 1,2 | INR 1 2 | 12,34 | 1,,234 | 100,00]   (F1 ×5)
  test_oversized_number_should_fail_closed_not_crash                                        (F2)
  test_non_iso_dates_should_fail_closed[20261026 | 2026-W01-1 | 2026W011]                   (F3 ×3)
  test_malformed_grouping_should_be_rejected_end_to_end                                     (F1 e2e)
```

## Limitations & honesty notes

- **Not an end-to-end bypass.** All findings stop at `VERIFY_REQUIRED` draft proposals /
  uncaught exceptions. No KB write, activation, or autonomous promotion was demonstrated or
  claimed; FI2 has no such path.
- **No fix proposed/applied.** Per the ownership boundary, remediation is Luna's. The root
  cause (unvalidated separator stripping in `_decimal`; unbounded `Decimal` scale in
  `_scaled`; over-permissive `date.fromisoformat`) is documented to aid, not pre-empt, that
  fix.
- F3's dedicated full-`validate_extraction` run on a date field was not executed (the `cards`
  fixture has no date field and it would entangle the separate `expired_value` sanity rule);
  helper + `parse_field_value` routing already demonstrate the confidently-wrong parse.
- Environment: the shared offline venv *interpreter* was reused read-only; all imports were
  forced to this worktree's source via `PYTHONPATH`. No package was installed or changed.
