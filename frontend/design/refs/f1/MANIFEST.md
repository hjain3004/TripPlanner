# F1 Gate Evidence Bundle

Generated: 2026-07-26
Generator: `scripts/capture-evidence.mjs` + `scripts/build-contrast-matrix.mjs`

## Contents

| File | Description |
|---|---|
| `kitchen-sink-390.png` | Kitchen-sink page at 390px viewport (mobile) |
| `kitchen-sink-768.png` | Kitchen-sink page at 768px viewport (tablet) |
| `kitchen-sink-1440.png` | Kitchen-sink page at 1440px viewport (desktop) |
| `kitchen-sink-reduced-motion.png` | Kitchen-sink page at 1440px with `prefers-reduced-motion: reduce` |
| `axe-report.json` | Full aXe audit of kitchen-sink at 1440px (Chromium) |
| `contrast-matrix.md` | WCAG 2.1 AA contrast ratios for all Singapore-theme token pairs via `culori` |

## aXe Audit Summary

- **Violations:** 1 (color-contrast — text-muted on bg at 4.31:1 is 0.19 below 4.5:1 AA threshold for 14px regular text; text-faint on bg at 2.63:1 is intentional decorative-only)
- **Passes:** 36
- **Incomplete:** 0

## Known Demo-Only Issues

The kitchen-sink page deliberately exercises every token variant (including decorative-only `text-faint`, color-chip labels on dark backgrounds, and the nested-theme override proof). These are not product pages.
