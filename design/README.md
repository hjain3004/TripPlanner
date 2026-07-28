# design/ — frozen visual template

`Premium Travel Itinerary Planner/` is a Figma Make export, adopted on 2026-07-28 as the
**visual template for the TripPlanner frontend**.

## Do not build this

It is a standalone Vite + React 18 project with its own `package.json`, `vite.config.ts`
and `node_modules` expectations. It is **reference material, not a workspace member**:

- It is not part of the `frontend/` Next.js build.
- It is not linted, typechecked, or tested by any repo gate.
- Do not `npm install` it, add it to a workspace, or import from it at runtime.
- Its own `README.md` is Figma boilerplate telling you to run `npm i`. Ignore that.

Read it, copy compositions out of it, and reimplement them in `frontend/` under the
repo's own token and typing rules.

## Why it is here

The in-repo F1–F4 frontend passed every gate it defined and was still a catalogue of
tokens and primitives that never showed what the product looked like. This bundle composes
actual product screens — Explore, Deals, Proof, Wallet, Profile, Itinerary — and was judged
the better deliverable despite failing most of those gates.

The palette is **not** a departure: the bundle's `src/styles/theme.css` defines
`--th-accent-4: oklch(0.536 0.135 30)`, identical to `frontend/src/themes/singapore.css`.
It was built on the approved celadon/mangrove palette. Only the composition is new.

## Current state

The integration of this bundle into `frontend/` (PR #4, `0a41492`) is **broken** —
`origin/main` has 44 TypeScript errors and 160 token-lint violations, both zero before the
merge. The bundle itself is fine; the port moved the views a directory deeper without
updating relative imports and never copied `theme.css`.

The fix plan is `docs/superpowers/plans/2026-07-28-figma-template-reconciliation.md`.
Frontend work is paused; start there if it resumes.

## Licensing

`Premium Travel Itinerary Planner/ATTRIBUTIONS.md` declares shadcn/ui (MIT) and Unsplash
photos. No Unsplash binaries are bundled — images are fetched by URL via
`src/components/figma/ImageWithFallback.tsx`.

The three PNGs in `src/imports/` are our own design-direction renders. They were checked
against the CC BY-SA Wikimedia derivatives in `frontend/design/probes/` (which are
gitignored pending attribution) and are unrelated: the traced probe SVG carries 4,182 paths
with a longest path of 41k characters, while `Illustrations.tsx` contains four hand-authored
shapes whose longest path is 117 characters.

Export archives (`design/*.zip`) are gitignored as redundant with this extracted copy.
