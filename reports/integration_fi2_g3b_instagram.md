# FI2, G3b, and Instagram integration

## Status

Integration development is complete pending the final exact-tree gate, CI, and
normal pull-request merge. FI2 and G3b remain offline-only; the Instagram work
is research documentation only. No live crawling, provider/model activation,
credentials, OAuth, spending, booking, deployment, or FI3 work occurred.

## Reconciliation

The integration branch was created from `origin/main` at `6428b78d173e8b191889c0d6cd3c8bd7ea9df21f`.
The three requested source worktrees were clean at their expected commits:

- FI2: `c925d98077dd94a1f24d7c312243bfcee78f2d3c`
- G3b: `3a9090b5cda1f838011b65d8a5f3828b2c83765b`
- Instagram: `df4e6ebb74d6bee075ccbf21199ce5a1f04fc16e`

They were merged in order with normal merge commits:

1. FI2: `12c48b4`
2. G3b: `ae3d648`
3. Instagram report: `81c8999`

The G3b merge conflicted only in `DEVIATIONS.md`; both FI2 and G3b decision
sections were retained. No source worktree or unrelated branch was changed.

## Integration correction: grouped money notation

The reported helper defect reproduced on this tree before correction:
`parse_money_minor("INR 1,2") == 1200` and
`parse_money_minor("INR 1 2") == 1200`. A proposal-validation regression
confirmed that the malformed value could otherwise reach `proposal_pending`.

The parser now validates grouping before removing separators. Recognized
international grouping (`1,250`, `1,234,567.89`), Indian grouping
(`12,50,000`), and unambiguous three-digit space grouping (`1 250`) remain
valid. Ambiguous or malformed grouping (`1,2`, `1 2`, `1,23,45`) remains
unresolved. No kernel arithmetic, financial golden, seed, or approved fact was
changed.

## Measured verification so far

All commands below ran in the isolated integration worktree using the existing
ignored local environment and catalogs; no credentials were copied.

| Check | Result |
|---|---|
| Seeded baseline from `backend/` | 2220 passed, 1 skipped, 3 warnings |
| Parser/proposal regressions before fix | 2 failures (expected reproductions) |
| FI2 extraction/replay after fix | 12 passed |
| Focused FI0/FI1/FI2 + G3b + gateway/registry/fallback | 453 passed, 3 warnings |
| Strict mypy/Ruff | Final exact gate pending; Ruff focused scopes clean; one combined exploratory mypy invocation hit the repository's configured Python 3.11/numpy stub compatibility issue and is not treated as gate evidence |

## Safety and scope retained

- FI2 stops at immutable evidence-backed draft proposals and human review;
  no approval/apply or FI3 activation path was added.
- G3b is not in the default registry and its live stdio transport requires a
  human `LiveActivationApproval`; its source permission, upstream robots
  fail-open behavior, third-party geocoding egress, retention, attribution,
  packaging, and live-schema gaps remain explicit unresolved limitations.
- FI1's four pre-live blockers remain open: connection-time DNS pinning,
  response-byte bounds before Crawl4AI materialization, durable cross-process
  throttling, and process isolation/hard termination for hostile PDF parsing.
- Instagram remains conditional feasibility research. No endpoint, credentials,
  implementation, experiment, or claim that development silence is negative
  evidence was added.
- Authoritative specs, seeds, financial goldens, Tier-F arithmetic, Kernel
  roles/stage order, OpenAPI, generated client, frontend, and live-provider
  defaults remain unchanged.

## Independent review and final evidence

The independent whole-integration review and final `make gate` results will be
added after review dispositions and final committed-tree verification. Any
verified Critical/Important finding will receive a regression test and a
separate fix before landing.
