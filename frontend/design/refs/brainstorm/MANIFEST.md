# Brainstorm reference screenshots — MANIFEST

Captured 2026-07-26 via Playwright MCP at 390×844 / 768×1024 / 1440×900 from the four
brainstorm artifacts the user approved, out of the full set at
`.superpowers/brainstorm/87988-1785011410/content/`. These are durable references for
F1 implementation, not authoritative specs — the frozen contract is
`frontend/design/CONTRACT.md` (Phase 0.6) plus revised specs 10/11.

`.superpowers/` and `.playwright-mcp/` are gitignored after this capture; the source
HTML is not committed. If a screenshot needs re-derivation, the source lives at the
path above until someone deletes it — these PNGs are now the durable record.

## calm-route-hybrid-polish-{390,768,1440}.png

Source: `calm-route-hybrid-polish.html` ("Calm Route — Atlas × Peranakan hybrid").

**Approves:** grid and split-panel layout, route-line/station-node wayfinding
structure, the ledger's ruled numeric-list geometry (aligned columns, hairline row
rules, one dominant recommendation), provenance-footnote placement at the foot of
computed sections, overall spacing/hierarchy of the Atlas Editorial × Peranakan
Modernist hybrid.

**Does NOT approve:** its typography (Bricolage Grotesque headings) — rejected
per handover §3.5 as "barely legible" in the aggressively condensed treatment used
here. Do not carry this face, its tracking, or its sizing into F1. The exact palette
hex values shown are provisional (handover §3.3), superseded by the Phase 0.3 OKLCH
freeze in this same session.

## visual-reset-three-directions-{390,768,1440}.png

Source: `visual-reset-three-directions.html` ("Calm Route — three less-generic
directions").

**Approves:** the Atlas Editorial + Peranakan Modernist hybrid direction (the "A+B"
combination) as the chosen visual identity — sharper/more architectural geometry than
earlier rounds, rectangular panels, low-to-medium corner radii used intentionally,
asymmetrical editorial composition. This is the artifact where the hybrid direction
itself was selected.

**Does NOT approve:** the third direction shown alongside it (International
Wayfinding, evaluated but not chosen as primary), or any typography rendered in this
comparison — type was settled separately in `display-font-real-reset.html` and the
later Schibsted Grotesk approval.

## display-font-real-reset-{390,768,1440}.png

Source: `display-font-real-reset.html` ("Calm Route — genuinely distinct display
fonts").

**Approves:** this is the live artifact for the still-open typography decision.
Options 3 (Bodoni Moda) and 4 (Boska) were approved as good candidates (handover
§3.4); the user did not pick a final winner between them. Schibsted Grotesk is
confirmed as the settled UI/body face shown here.

**Does NOT approve:** options 1 and 2 in this same comparison, or any prior-round
face (Fraunces + Instrument Sans, Newsreader + Manrope, Georgia/Literata/DM Serif
Display/Petrona — all explicitly rejected, handover §3.5). This artifact is
superseded by the Phase 0.2 Bodoni-vs-Boska comparison built specifically to resolve
the remaining choice at realistic sizes with the approved hybrid geometry.

## motion-personality-{390,768,1440}.png

Source: `motion-personality.html`.

**Approves:** the Guided Reveal motion personality (handover §2.4) — ordinary
interaction quiet and fast, one orchestrated route-drawing moment, controlled-sequence
reveals, the interface settling and becoming still afterward, full content immediately
visible with no decorative movement under reduced-motion. This is the artifact that
led to the Guided Reveal approval.

**Does NOT approve:** any other motion direction shown in the same comparison, or any
literal timing/easing values as final — Phase 0.6's `CONTRACT.md` states the frozen
motion tokens (`--dur-fast/base/slow`, `--ease-brand`) that supersede whatever exact
values this artifact happens to render at.

## Rejected/superseded artifacts (not screenshotted — reference only)

Per handover §5, these remain on disk until `.superpowers/` is removed but are not
preserved as durable references: `calm-route-foundation.html` (generic AI/SaaS
composition, disliked), `typography-reset.html` (options A/C rejected),
`heading-font-round-two.html` (entire round rejected), `visual-direction.html`
(superseded by `visual-direction-v2.html`), `library-theme-research.html`
(documentation/research board, not a visual reference),
`waiting-development-approach.html` / `waiting-product-hierarchy.html` (process
scratch notes, not visual references).
