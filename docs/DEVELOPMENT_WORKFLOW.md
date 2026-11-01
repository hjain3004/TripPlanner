# Development workflow: deliver usable behavior

Human-directed process update: **2026-10-27**. Progress means a demonstrated capability,
not a larger test suite or another report. This guide supplements the
[implementation protocol](specs/06_implementation_protocol.md); it does not edit authoritative
specs, remove required checks, authorize new features, or change financial/security boundaries.

## Define the outcome before expanding the task

For each approved task, name the traveler or operator, their input, the action they can take,
and the observable result. Choose the smallest useful end-to-end path through existing code.
Wire it into its intended application, API, or CLI instead of repeatedly delivering disconnected
helpers. A backend-only task can demonstrate an API/CLI workflow without inventing a frontend.

For example, a review milestone could demonstrate an operator opening a draft, inspecting its
source evidence, making a validated decision, reopening the stored decision after restart, and
exporting a deterministic dry-run bundle. That is an example acceptance path, not a claim that
it exists or permission to apply financial facts to the KB.

Keep the approved scope fixed. Do not add speculative infrastructure, a second framework, or a
new service unless the current workflow requires it. Identify internal/operator benefits
separately from traveler-facing improvements.

## Exercise the integration early

Run a minimal representative input through the real local dependency and the actual integration
entry point early, where available. Check storage reopen, errors, cancellation, or approval
behavior when they are relevant to the feature, not after expanding a large mock corpus.

Fixtures and replay remain essential for deterministic offline tests, but label evidence honestly:

| Evidence | What it establishes |
|---|---|
| Synthetic fixture or test double | Behavior against an authored example, not the upstream service |
| Recorded replay | Behavior against a particular captured response/version, not current availability |
| Real-library local execution | Compatibility for the exercised library/version/input/platform |
| Approved live exercise | The observed provider behavior within that exercise's recorded scope |

Missing access or permission is a blocker to that live claim, not permission to scrape, spend,
invent data, or silently replace the intended integration with a mock. Exercise the complete
permitted fallback and state what the unavailable dependency prevents. Normal tests stay offline.

## Test risks, not totals

Add focused regressions for changed behavior and plausible failures that affect the outcome.
Prioritize financial units and parsing, grounded claims, ownership/privacy, evidence integrity,
approval, concurrency/idempotency, data loss, and real dependency boundaries where applicable.
Do not weaken assertions, hide unexpected failures with skips, or remove useful coverage for speed.

No target number of tests, coverage percentage, commits, reviews, or mutations defines progress.
Use mutation checks for a specific guard whose test strength is uncertain, not as a blanket quota.
Reopen completed work for a reproduced defect, changed dependency, relevant new evidence, or
explicit user request; do not initiate another broad audit merely because agents are available.

Run focused checks during implementation and the existing complete milestone gate at acceptance.
Do not duplicate expensive full runs for unchanged inputs without a requirement or reason.
Existing exact-commit/clean-tree and CI requirements still apply; changed code requires appropriate
reverification. A passing gate never substitutes for demonstrating the agreed workflow.

## Review and parallel work

Default to one implementation owner and one independent review of the completed change. Use
earlier targeted review when a concrete high-risk decision warrants it, not automatically after
every small task. Fix reproduced findings and document reasoned rejections.

Parallelize only independent, approved deliverables with explicit ownership and stable interfaces.
Do not assign several agents the same production files, create competing implementations, or
manufacture supporting reports to keep all agents occupied. Other agents may remain idle.
Review and verify the combined tree when independent changes are integrated.

A separate compatibility check or future activation requirement is not automatically a blocker
to an unrelated feature. State the demonstrated risk or actual dependency if it blocks delivery.
Financial correctness, data-loss/security defects in the affected path, required gates, and
source/credential/spend/deployment permissions cannot be waived to claim completion.

Check disk capacity before large installs/builds. Reuse suitable existing environments and
worktrees where safe; do not duplicate full repositories or install browser runtimes for a narrow
library test. Never alter a shared environment or delete another task's files without authority.

## Report the capability first

Keep progress updates short and reproducible:

1. **Working now:** who can do what, through which entry point.
2. **Demonstrated:** the input/action/result, branch/commit, and execution mode.
3. **Unavailable or deferred:** wiring, permissions, environment, unsupported inputs, or next scope.
4. **Verification:** required checks and relevant regressions; detailed counts belong in evidence.

Distinguish implementation from integration and demonstrated use. An unwired/disabled adapter is
not a live inventory feature. An offline milestone may be complete on its explicit terms, but
its remaining activation work must remain visible. A research report is not product delivery;
test counts are not completion percentages or evidence of user adoption.

Maintain one concise milestone report as work progresses. Preserve historical evidence and scope
limitations; prepare documentation before final verification where practical instead of creating
unnecessary report-only commit/gate cycles. Never pre-write a successful result or claim an
unexecuted test. Record the actual tested revision and do not imply an older review covers later code.

## Boundaries unchanged

All existing frozen arithmetic/goldens, kernel isolation, provenance, human approval, typed bounded
workflows, account privacy, API synchronization, source permission, zero-out-of-pocket constraints,
and no-booking/no-transfer-execution rules remain in force. Live calls, credentials, paid services,
legal wording, verified seed replacements, and public deployment still require the applicable
explicit approvals. This process update is not a production-hardening or activation authorization.
