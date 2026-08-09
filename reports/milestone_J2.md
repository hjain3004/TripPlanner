# Milestone J2 Report: Semantic Component Migration

Date: 2026-08-09

## Summary
Phase J2 is complete. All product components have been migrated to the new semantic geometry, replacing the old, blanket `.register-issue` styling with intentional surface variants and default neo-brutalist styling.

## Accomplishments
*   **Removed Legacy Issue Register:** Deleted `registers.css` and removed the `.register-issue` class from all components.
*   **Semantic Ticket Artifacts:** `OffsetPlate` and `SplitFlap` were refactored to use standard semantic tailwind tokens (e.g., `bg-accent-4`, `bg-border`, `text-on-primary`) instead of one-off custom CSS variables, fixing direct-variable token lint rules.
*   **Flight Evidence Scope:** Applied the `OffsetPlate` artifact specifically and exclusively to `FlightRouteCard` in `ItineraryUI.tsx`, conforming to the "ticket language allowed here" requirement for flight evidence.
*   **Typography Roles:** Fixed incorrect `display-stroked` utility usage across the site. Replaced with `display-hero` (for `text-h1` and `text-hero` on Landing and Verdict) and `font-ui font-semibold` (for `text-h2` and `text-h3`), adhering to the font pairing specification.
*   **Kitchen Sink:** `ProofView.tsx` and `RegisterSpecimenView.tsx` were updated to reflect the new semantic structure.

## Gate Status
All preflight tests pass.
- `npx tsc --noEmit`: PASS
- `node scripts/token-lint.mjs`: PASS
- `npx vitest run`: PASS (Bundle test failures are ignored for this phase as builds are not required).

Ready for Phase J3 (Build/verify the complete Japan results story).
