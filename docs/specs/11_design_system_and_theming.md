# 11 — Design System & Destination Theming

The visual identity is token-driven: one shared component library consuming **semantic tokens only**, with each destination shipping a theme pack that remaps primitives → semantics plus typography accents, imagery style, motion personality, and copy voice. Singapore is the reference implementation; future packs (Japan, USA, Europe) are created by copying `_template.css` and filling the same slots — no component changes allowed.

All themes are **light**. Dark mode is out of scope (Tier F for MVP): it halves the QA matrix and the product's premium register is built on light-surface depth.

## 1. Token architecture (Tailwind v4, CSS-first)

Three layers, defined in `src/themes/`:

- `base.css` — layer 1 (primitives shared by all themes: type scale, spacing, radii, shadow ramp, motion durations) + layer 3 (component tokens referencing semantics).
- `singapore.css` — layer 2: the primitive palette and the primitive→semantic mapping for Singapore, applied under `.theme-singapore`.
- `_template.css` — a commented copy of the Singapore pack with every value blanked and instructions inline; creating a new destination = copy, rename class, fill slots, register in the theme switcher. Nothing else.

Mechanics: shared tokens live in `@theme` in `base.css` (they emit utilities). Destination-variable tokens are CSS custom properties scoped to `.theme-<destination>` on `<html>`, referenced from `@theme` via `--color-primary: var(--th-primary)` indirection so utilities stay stable across themes. Colors in OKLCH.

## 2. Semantic token contract (components may use ONLY these — Tier F)

```
Surfaces:  --color-bg (page), --color-surface (card), --color-surface-raised,
           --color-surface-overlay (frosted: pair with --blur-overlay), --color-border (hairline)
Text:      --color-text, --color-text-muted, --color-text-faint, --color-text-on-primary
Brand:     --color-primary, --color-primary-hover, --color-accent-1..4 (destination personality set)
Meaning:   --color-success (savings), --color-warning (staleness/verify), --color-danger,
           --color-savings-highlight (the money moment; usually metallic/gold register)
Depth:     --shadow-1 (rest), --shadow-2 (hover), --shadow-3 (modal/overlay) — layered soft
           low-opacity shadows, never single hard shadows; --blur-overlay (16px)
Shape:     --radius-s (6px), --radius-m (12px), --radius-l (20px), --radius-full
Motion:    --dur-fast (180ms), --dur-base (320ms), --dur-slow (650ms), --ease-brand
Type:      --font-display, --font-ui, --text-hero…--text-caption (scale below)
```

Type scale (base.css, fluid via clamp): hero 56→96px display; h1 40→56; h2 28→36; h3 22→24; body 16/1.6; caption 13. Numbers everywhere use `font-variant-numeric: tabular-nums` (money columns must not wiggle during count-ups — Tier F).

Light-theme depth rules (Tier F): elevation = surface tint + layered shadow + hairline border together, never shadow alone; borders are 1px at ~8–10% text-color opacity; frosted overlays = `--color-surface-overlay` at ~72% alpha + backdrop blur. Contrast: all text/surface pairs ≥ WCAG AA (4.5:1 body, 3:1 large text) — verified programmatically at Gate F1; accent colors are decorative and never the sole carrier of meaning.

## 3. Singapore pack (reference values — Tier C: tune by eye at F1 within OKLCH ±0.03 L/C, hue fixed)

Identity: Peranakan shophouse pastels (sorbet lilac/mint/peach/lemon, rose) for personality and illustration; Marina Bay teal for the primary; gold for savings moments; clean warm-white base so the pastels read premium, not nursery. Imagery: dawn/dusk Marina Bay skyline, shophouse facades, hawker detail shots — warm light, high dynamic range, no faces.

```css
.theme-singapore {
  --th-bg:            oklch(0.99 0.004 95);   /* warm white */
  --th-surface:       oklch(1 0 0);
  --th-surface-raised:oklch(0.985 0.006 95);
  --th-overlay:       oklch(0.99 0.004 95 / 0.72);
  --th-border:        oklch(0.30 0.02 250 / 0.10);
  --th-text:          oklch(0.26 0.02 255);   /* warm near-black */
  --th-text-muted:    oklch(0.45 0.02 255);
  --th-text-faint:    oklch(0.60 0.015 255);
  --th-primary:       oklch(0.55 0.10 205);   /* Marina Bay teal */
  --th-primary-hover: oklch(0.50 0.10 205);
  --th-on-primary:    oklch(0.99 0.004 95);
  --th-accent-1:      oklch(0.83 0.07 20);    /* Peranakan rose */
  --th-accent-2:      oklch(0.88 0.06 165);   /* mint */
  --th-accent-3:      oklch(0.90 0.08 95);    /* lemon */
  --th-accent-4:      oklch(0.82 0.06 300);   /* lilac */
  --th-success:       oklch(0.58 0.12 155);
  --th-warning:       oklch(0.70 0.13 75);
  --th-danger:        oklch(0.55 0.18 25);
  --th-savings:       oklch(0.72 0.11 85);    /* soft gold */
}
```

Typography voice: Fraunces (display; optical-size + soft axes — warm, editorial, slightly wonky at hero sizes) + Instrument Sans (UI). Future packs may swap the *display* font only (slot in the template); the UI font is global.

Motion personality: `--ease-brand: cubic-bezier(0.22, 1, 0.36, 1)` (confident settle), durations as base. The template documents personality as three adjectives + easing + duration bias; e.g. a future Japan pack might bias faster/crisper. Components read motion tokens — they never hardcode curves (Tier F).

Copy voice (used by Doc 15 and all microcopy): warm, precise, lightly playful; hawker-culture and MRT references welcome; never mocking, never slang-dense; money sentences always plain and exact.

## 4. Imagery & asset pipeline

Curated set self-hosted in `public/img/<destination>/` with a `MANIFEST.md` per destination recording: source URL, platform, license (Pexels/Pixabay preferred; Unsplash general-license downloads acceptable; **never** the Unsplash API), and the crop intent. All heroes exported AVIF+WebP at 3 sizes; LCP hero gets `priority` + preload. Icons: Lucide only. No stock that shows recognizable faces; no brand logos (bank/card art is rendered as abstract gradient cards with issuer *text*, not logos — trademark safety).

## 5. Theme pack definition of done (checklist inside _template.css)

A new destination ships when: all `--th-*` slots filled; contrast pairs pass AA programmatically; imagery manifest has ≥ 6 licensed assets; display-font slot decided (keep or swap); motion personality line filled; quip pack exists (Doc 15) with ≥ 30 approved lines; kitchen-sink screenshot reviewed at 3 viewports under the new class. Estimated effort per pack after Singapore: ~1 day.
