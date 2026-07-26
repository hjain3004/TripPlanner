# 11 — Design System & Destination Theming

The visual identity is token-driven: one shared component library consuming **semantic tokens only**, with each destination shipping a theme pack that remaps primitives → semantics plus typography accents, imagery style, motion personality, and copy voice. Singapore is the reference implementation; future packs (Japan, USA, Europe) are created by copying `_template.css` and filling the same slots — no component changes allowed.

All themes are **light**. Dark mode is out of scope (Tier F for MVP): it halves the QA matrix and the product's premium register is built on light-surface depth.

## 1. Token architecture (Tailwind v4, CSS-first)

Three layers, defined in `src/themes/`:

- `base.css` — layer 1 (primitives shared by all themes: type scale, spacing, radii, shadow ramp, motion durations) + layer 3 (component tokens referencing semantics).
- `singapore.css` — layer 2: the primitive palette and the primitive→semantic mapping for Singapore, applied under `.theme-singapore`.
- `_template.css` — a commented copy of the Singapore pack with every value blanked and instructions inline; creating a new destination = copy, rename class, fill slots, register in the theme switcher. Nothing else.

Mechanics: static primitives (type scale, spacing, radii, shadow ramp, motion durations — no `var()` references) live in a plain `@theme` block in `base.css` (they emit utilities and are safe to resolve at `:root`). Destination-variable tokens are CSS custom properties scoped to `.theme-<destination>` on `<html>`, referenced via `--color-primary: var(--th-primary)` indirection — but that bridge **must** live in `@theme inline`, not plain `@theme`. Plain `@theme` substitutes `var()` at the *declaring* element (`:root`), not the consuming one: it renders correctly when `.theme-singapore` happens to sit on `<html>` (where `:root` and the theme class coincide), then silently renders transparent with no console error the moment a second destination theme is scoped to a subtree — exactly the scenario this pack architecture exists for. `@theme inline` emits `.bg-primary { background-color: var(--th-primary) }`, resolving at the consuming element via normal cascade instead. Colors in OKLCH.

## 2. Semantic token contract (components may use ONLY these — Tier F)

```
Surfaces:  --color-bg (page), --color-surface (card), --color-surface-raised,
           --color-surface-overlay (frosted: pair with --blur-overlay), --color-border (hairline)
Text:      --color-text, --color-text-muted, --color-text-faint, --color-text-on-primary
Brand:     --color-primary, --color-primary-hover, --color-accent-1..4 (destination personality set)
Meaning:   --color-success, --color-success-text, --color-warning (staleness/verify),
           --color-warning-text, --color-danger, --color-savings (the money moment;
           metallic/brass register), --color-savings-text. Each meaning color ships
           as a decorative/text pair: the base token is for fills, rules, and
           underlines only; the paired `-text` token (same hue, darker L) is the only
           one permitted on text, per the Gate F1 contrast matrix. Resolves the prior
           `--color-savings-highlight` (this section) vs `--color-savings` (Doc 13
           §4.1) naming split to one name: `--color-savings`.
Depth:     --shadow-1 (rest), --shadow-2 (hover), --shadow-3 (modal/overlay) — layered soft
           low-opacity shadows, never single hard shadows; --blur-overlay (16px)
Shape:     --radius-s (6px), --radius-m (12px), --radius-l (20px), --radius-full
Motion:    --dur-fast (180ms), --dur-base (320ms), --dur-slow (650ms), --ease-brand
Type:      --font-display, --font-ui, --text-hero…--text-caption (scale below)
```

Type scale (base.css, fluid via clamp): hero 56→96px display; h1 40→56; h2 28→36; h3 22→24; body 16/1.6; caption 13. Numbers everywhere use `font-variant-numeric: tabular-nums` (money columns must not wiggle during count-ups — Tier F).

Light-theme depth rules (Tier F): elevation = surface tint + layered shadow + hairline border together, never shadow alone; borders are 1px at ~8–10% text-color opacity; frosted overlays = `--color-surface-overlay` at ~72% alpha + backdrop blur. Contrast: all text/surface pairs ≥ WCAG AA (4.5:1 body, 3:1 large text) — verified programmatically at Gate F1; accent colors are decorative and never the sole carrier of meaning.

## 3. Singapore pack (reference values — Tier C: tune by eye at F1 within OKLCH ±0.03 L/C, hue fixed. This palette itself is the Tier-F design-change replacement for the rejected sorbet pack below — see `DEVIATIONS.md`; the ±0.03/hue-fixed bound applies to future fine-tuning of *these* values, not as a constraint on setting them.)

Identity: **Atlas Editorial × Peranakan Modernist hybrid** — limestone canvas and mangrove green carry the identity (not the primary Marina Bay teal previously specified); celadon (two tones) supplies the architectural Peranakan reference; brass marks savings/verified-value moments; lacquer red is capped at **<2% of any screen's surface** — accent rules, the wordmark slash, route-node markers — and is never a section fill or a large text run. Imagery: dawn/dusk Marina Bay skyline, shophouse facades, hawker detail shots — warm light, high dynamic range, no faces.

```css
.theme-singapore {
  --th-bg:             oklch(0.947 0.013 87);   /* limestone #F1EDE4 */
  --th-surface:        oklch(0.979 0.008 91);   /* paper #FAF8F2 */
  --th-surface-raised: oklch(0.990 0.005 91);
  --th-overlay:        oklch(0.979 0.008 91 / 0.72);
  --th-border:         oklch(0.28 0.01 145 / 0.10);
  --th-text:           oklch(0.281 0.007 145);  /* ink #272A27 */
  --th-text-muted:     oklch(0.539 0.014 157);  /* #68716B */
  --th-text-faint:     oklch(0.660 0.014 157);  /* decorative/hint text only, never sole carrier of required content */
  --th-primary:        oklch(0.320 0.042 181);  /* mangrove #173A34 */
  --th-primary-hover:  oklch(0.270 0.042 181);
  --th-on-primary:     oklch(0.979 0.008 91);
  --th-accent-1:       oklch(0.848 0.027 167);  /* celadon-1 #BDD3C9 */
  --th-accent-2:       oklch(0.917 0.016 161);  /* celadon-2 #DBE7E0 */
  --th-accent-3:       oklch(0.660 0.097 82);   /* brass #B08C48 */
  --th-accent-4:       oklch(0.536 0.135 30);   /* lacquer #AE493B, <2% surface budget */
  --th-success:        oklch(0.580 0.120 155);
  --th-success-text:   oklch(0.450 0.120 155);  /* AA pair, 6.52:1 on paper */
  --th-warning:        oklch(0.700 0.130 75);
  --th-warning-text:   oklch(0.450 0.130 75);   /* AA pair, 7.09:1 on paper */
  --th-danger:         oklch(0.550 0.180 25);   /* unchanged; already 5.00:1 on paper, no pair needed */
  --th-savings:        oklch(0.660 0.097 82);   /* brass, same value as accent-3 */
  --th-savings-text:   oklch(0.450 0.097 82);   /* AA pair, 7.04:1 on paper */
}
```

`--th-warning` intentionally keeps the amber hue (75) rather than reassigning to lacquer: the design thesis's "warning nodes" line refers to the `RouteNode` component's warning-state marker specifically (which may use `--color-accent-4` directly, a component-level styling choice, per `frontend/design/CONTRACT.md`), not a semantic-token hue change. Collapsing `--color-warning` onto lacquer's hue would put it within a few degrees of `--color-danger` (hue 25 vs. 30) and make the two meanings visually indistinguishable — a regression this revision does not introduce.

Contrast pairs verified via sRGB→OKLab→OKLCH round-trip + WCAG relative luminance (not eyeballed); source render at `frontend/design/refs/palette/celadon-mangrove-forward.html` and its MANIFEST.

Typography voice: Bodoni Moda (display; variable `opsz 6..96` axis, used per Doc 10 §2 and the type-scale allowed-contexts table in `frontend/design/CONTRACT.md` — hero/h1/h2 only, never dense functional headings or money) + Schibsted Grotesk (UI/body/money) + Roboto Mono (metadata, airport codes, provenance). Boska was evaluated and rejected: Fontshare's own site labels its ITF-FFL license page "Closed Source License," and the license prohibits sharing font files publicly — incompatible with self-hosting in this public repository. Future packs may swap the *display* font only (slot in the template); the UI and mono fonts are global.

Motion personality: `--ease-brand: cubic-bezier(0.22, 1, 0.36, 1)` (confident settle), durations as base. The template documents personality as three adjectives + easing + duration bias; e.g. a future Japan pack might bias faster/crisper. Components read motion tokens — they never hardcode curves (Tier F).

Copy voice (used by Doc 15 and all microcopy): warm, precise, lightly playful; hawker-culture and MRT references welcome; never mocking, never slang-dense; money sentences always plain and exact.

## 4. Imagery & asset pipeline

Curated set self-hosted in `public/img/<destination>/` with a `MANIFEST.md` per destination recording: source URL, platform, license (Pexels/Pixabay preferred; Unsplash general-license downloads acceptable; **never** the Unsplash API), and the crop intent. All heroes exported AVIF+WebP at 3 sizes; LCP hero gets `priority` + preload. Icons: Lucide only. No stock that shows recognizable faces; no brand logos (bank/card art is rendered as abstract gradient cards with issuer *text*, not logos — trademark safety).

## 5. Theme pack definition of done (checklist inside _template.css)

A new destination ships when: all `--th-*` slots filled; contrast pairs pass AA programmatically; imagery manifest has ≥ 6 licensed assets; display-font slot decided (keep or swap); motion personality line filled; quip pack exists (Doc 15) with ≥ 30 approved lines (the pack-floor minimum for any destination; Singapore as the reference pack targets ≥ 40 per Doc 15 §3's MVP inventory line); kitchen-sink screenshot reviewed at 3 viewports under the new class. Estimated effort per pack after Singapore: ~1 day.
