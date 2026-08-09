# Milestone J1 Report: Theme Contract and Japan Pack

Date: 2026-08-09

## Summary
Phase J1 is complete. The application now implements deterministic, hydration-safe theme resolution using a multi-pack architecture. The product default is Japan (the golden pack), with a quiet `theme-natural` fallback for unknown routes.

## Accomplishments
*   **Theme Packs:** Created `japan.css` and `natural.css` matching the design specification.
*   **Theme Resolution:** Implemented `lib/theme/resolver.ts` to deterministically return a valid theme class based on the golden destination rule (defaulting to Japan).
*   **Layout Integration:** Updated `RootLayout` to use the theme resolver, avoiding hydration mismatches and hardcoded region tokens.
*   **Neo-Brutalist Geometry:** Removed soft radius tokens (6px, 12px, 20px) from `base.css` shell defaults, setting them to `0px`. Updated shell default shadows to hard offsets without blur (`oklch(0.281 0.007 145 / 0.15)` and `0.20`).
*   **Display Stroke Roles:** Replaced the continuous clamp `display-stroked` utility with named roles (`display-hero` at 3px, `display-mark` at 1.5px) to strictly preserve Poiret One legibility at small sizes.
*   **Gate Validation:** Refactored `contrast.test.ts` to use `japan.css` as the golden token source. All token completeness and WCAG contrast assertions pass.
*   **Theme Proof Route:** Created `/theme-proof` route to visualize and switch between the `theme-japan` and `theme-natural` packs.

## Gate Status
All preflight tests pass.
- `npx tsc --noEmit`: PASS
- `node scripts/token-lint.mjs`: PASS
- `npx vitest run`: PASS

Ready for Phase J2 (Product primitive migration).
