# Hotel selection and deterministic budgeting

Status: **ACCEPTED — OFFLINE DEVELOPMENT COMPLETE**

This milestone adds an authenticated, owner-scoped hotel-selection path to the
existing CP4 workspace. A traveler can list the retained server-owned hotel
evidence, submit either an admissible retained inventory quote or an explicitly
labeled user-provided stay total, preview the deterministic budget and payment
strategy effect, and approve the proposal through the existing CP4 reservation,
CAS, and idempotency boundary. Approved results become the workspace's current
result and can be saved as a new immutable trip revision. The focused workflow
also reopens SQLite and verifies that the accepted report and revision remain
unchanged.

User-provided totals are planning assertions, not provider evidence or
knowledge-base facts. They require explicit currency, coverage, payment-channel
assumptions, and retain limitations in the report. Retained inventory quotes are
admitted only when their existing price scope is cost-eligible, fresh, and has
supported payment channels. Sample nightly pricing preserves the frozen
per-night FX conversion followed by nights multiplication; external party-total
quotes are converted once.

## Demonstration

Offline demonstration (seeded sample data; no provider or model calls):

```text
make seed PY=/private/tmp/tripwise-gondola-finish/venv/bin/python
cd backend
/private/tmp/tripwise-gondola-finish/venv/bin/pytest -q \
  evals/test_hotel_selection_budgeting.py
```

The regression exercises: retained inventory listing, user-total preview,
missing payment-channel refusal, deterministic inventory-quote preview,
idempotent replay and conflicting event rejection, explicit approval, stale
approval refusal, first save plus append revision, SQLite reopen, and owner
isolation. The fixture uses synthetic/sample inputs and is labeled as such; it
does not claim live hotel availability.

## Review and limitations

An independent whole-branch review found two Important issues. Both were fixed
and covered by regressions: sample nightly FX rounding now matches the existing
gateway order, and MSW preview fixtures now match the generated contract.

The existing sample corridor currently retains one style-matching hotel, so the
options response may have no alternative rows. The API exposes the selected
retained quote and any available alternatives without manufacturing additional
hotels. No frontend screen is added in this backend milestone; the generated
client, facade exports, and MSW behavior are synchronized for a later UI.

Live provider traffic, OAuth, bookings, spending, and ongoing activation remain
disabled. This milestone does not alter flight inventory or frozen Kernel
arithmetic, seeds, or goldens.

## Verification evidence

Before the final clean-tree gate:

- Backend: `3104 passed, 79 skipped, 3 warnings`.
- Exact committed-tree gate backend: `3150 passed, 53 skipped, 3 warnings`.
- Focused hotel-selection regressions: `2 passed`.
- Strict mypy over `planning`, `api`, and `agents`: 49 source files, no issues;
  exact gate all source packages: 245 source files, no issues.
- Focused Ruff scope: clean.
- Exact gate Ruff zero-tolerance scopes: clean; core/api legacy count 6 under
  the ceiling of 12.
- OpenAPI export twice and generated-client drift check: clean.
- Frontend TypeScript, ESLint, token lint, contrast, contract tests (28), and
  production build: clean; ESLint retained 14 existing warnings and no errors.
- Offline browser suite: `492 passed, 76 skipped`; live integration tests were
  skipped by their normal environment guards.

The exact committed-tree `make gate` passed on implementation commit `5db6a21`.
The documentation-only follow-up commit will be gated again before handoff.
