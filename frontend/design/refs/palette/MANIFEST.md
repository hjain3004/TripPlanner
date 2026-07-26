# Palette freeze render — MANIFEST

`celadon-mangrove-forward-{390,768,1440}.png`, rendered 2026-07-26 from
`celadon-mangrove-forward.html` (kept alongside as source, not gitignored — this one
is durable, unlike the brainstorm scratch HTML).

This is the **confirmation render of the already-settled direction**, not a live
lacquer-forward-vs-celadon-forward choice. `F1_IMPLEMENTATION_PLAN.md`'s "Decisions
already made — do not reopen" table fixes the palette as "celadon/mangrove-forward;
lacquer red capped <2% of surface" — that decision predates this session. This render
exists so the user can see the *rendered* result of that decision (per Phase 0.3's
instruction to judge "rendered rather than described") and the corrected contrast
tokens, not to relitigate the direction.

One self-caught fix during authoring: the first pass colored the entire "Every
advantage." hero emphasis line in lacquer red — a much larger surface than the
thesis's own examples (accent rules, the wordmark slash, warning nodes). Corrected to
mangrove before this screenshot; lacquer now appears only at the wordmark slash, the
origin route-dot, and the "Recommended" notch label.

Full OKLCH token values are the canonical record in `frontend/design/CONTRACT.md`
(Phase 0.6) and `docs/specs/11_design_system_and_theming.md` §3 (Phase 0.4) — this
render is evidence, not the source of truth for exact values.

Contrast fixes proven by the swatch strip at the foot of the render (computed via
sRGB→OKLab→OKLCH round-trip + WCAG relative luminance, not eyeballed):

| Token | Decorative (fills/rules) | Paired `-text` (L≈0.45, hue held) |
|---|---|---|
| `--th-savings` (brass) | `oklch(0.660 0.097 82)` — 2.96:1 on paper, fails AA | `oklch(0.450 0.097 82)` — 7.04:1, passes AA |
| `--th-warning` (amber) | `oklch(0.700 0.130 75)` — 2.57:1 on paper, fails AA | `oklch(0.450 0.130 75)` — 7.09:1, passes AA |
| `--th-success` (green) | `oklch(0.580 0.120 155)` — 3.80:1 on paper, large-text only | `oklch(0.450 0.120 155)` — 6.52:1, passes AA |

`--th-danger` (`oklch(0.550 0.180 25)`, unchanged from the old sorbet spec) already
clears AA at 5.00:1 on paper and needed no pairing.
