# Display font decision — MANIFEST

**No rendered Bodoni-vs-Boska comparison exists in this folder.** The plan's Phase
0.2 instruction was conditional: build the comparison only if Boska is SIL OFL-licensed
(self-hosting permitted); if it's ITF-FFL (closed source), Bodoni Moda wins by default
and that default gets stated plainly rather than silently substituted. This is that
statement.

## What was checked

Fontshare's own site titles Boska's license page **"Closed Source License"** (page
title, not a third-party summary — confirmed via WebSearch of `fontshare.com/licenses/itf-ffl`).
The ITF Free Font License terms: users get a non-exclusive, non-transferrable license
to *use* the font, but **"may not share the original font files publicly or with
third parties."** Self-hosting `.woff2` binaries in this public GitHub repository —
which is exactly what `next/font/local` would require — is sharing the font files
publicly. This is incompatible with the license, independent of any aesthetic
judgment between the two faces.

## Decision

**Bodoni Moda**, loaded via `next/font/google` (Google Fonts hosts it under a license
that permits this). No comparison render was built because there was nothing left to
compare — the alternative was disqualified on a licensing fact, not a taste call.

## Where the decision lives going forward

`frontend/design/CONTRACT.md` §1 (font families and delivery), `docs/specs/11_design_system_and_theming.md`
§3 (typography voice), `DEVIATIONS.md` (Tier-F design-change row, full citation of the
license language).

## Reference artifact that remains relevant

`frontend/design/refs/brainstorm/display-font-real-reset-{390,768,1440}.png` — the
brainstorm-round artifact where Bodoni Moda and Boska were both approved as
candidates (options 3 and 4) before this session resolved which one ships. See that
folder's `MANIFEST.md` for what it does and doesn't approve.
