import { writeFileSync } from "fs";
import { resolve } from "path";
import {
  oklch,
  rgb,
  wcagContrast,
  toGamut,
} from "culori";

function parseRgb(spec) {
  const c = oklch(spec);
  const r = rgb(c);
  const clamped = toGamut("rgb", "oklch")(r);
  const a = r.alpha ?? clamped.alpha ?? 1;
  return { r: clamped.r, g: clamped.g, b: clamped.b, alpha: a < 1 ? a : 1 };
}

function ratio(a, b) {
  const ra = { mode: "rgb", r: a.r, g: a.g, b: a.b };
  const rb = { mode: "rgb", r: b.r, g: b.g, b: b.b };
  const raw = wcagContrast(ra, rb);
  return Math.round(raw * 100) / 100;
}

const tokens = [
  { key: "bg", label: "bg (limestone)", spec: "oklch(0.947 0.013 87)" },
  { key: "surface", label: "surface (paper)", spec: "oklch(0.979 0.008 91)" },
  { key: "border", label: "border", spec: "oklch(0.28 0.01 145 / 0.10)" },
  { key: "text", label: "text (ink)", spec: "oklch(0.281 0.007 145)" },
  { key: "textMuted", label: "text-muted", spec: "oklch(0.539 0.014 157)" },
  { key: "textFaint", label: "text-faint", spec: "oklch(0.660 0.014 157)" },
  { key: "onPrimary", label: "on-primary", spec: "oklch(0.979 0.008 91)" },
  { key: "primary", label: "primary (mangrove)", spec: "oklch(0.320 0.042 181)" },
  { key: "accent4", label: "accent-4 (lacquer)", spec: "oklch(0.536 0.135 30)" },
  { key: "success", label: "success", spec: "oklch(0.580 0.120 155)" },
  { key: "successText", label: "success-text", spec: "oklch(0.450 0.120 155)" },
  { key: "warning", label: "warning", spec: "oklch(0.700 0.130 75)" },
  { key: "warningText", label: "warning-text", spec: "oklch(0.450 0.130 75)" },
  { key: "danger", label: "danger", spec: "oklch(0.550 0.180 25)" },
  { key: "savings", label: "savings (brass)", spec: "oklch(0.660 0.097 82)" },
  { key: "savingsText", label: "savings-text", spec: "oklch(0.450 0.097 82)" },
];

const map = {};
for (const t of tokens) {
  map[t.key] = { label: t.label, rgb: parseRgb(t.spec) };
}

// border composited over bg
const borderComp = (() => {
  const fg = map.border.rgb;
  const bg = map.bg.rgb;
  const fa = fg.alpha;
  const ba = bg.alpha ?? 1;
  const ao = fa + ba * (1 - fa);
  return {
    r: (fg.r * fa + bg.r * ba * (1 - fa)) / ao,
    g: (fg.g * fa + bg.g * ba * (1 - fa)) / ao,
    b: (fg.b * fa + bg.b * ba * (1 - fa)) / ao,
  };
})();

const OUT = resolve(process.cwd(), "design/refs/f1/contrast-matrix.md");
const lines = [];

lines.push("# WCAG Contrast Matrix - Singapore Theme", "");
lines.push("Computed " + new Date().toISOString().split("T")[0] + " via culori.", "");
lines.push("## Key Pairs", "");
lines.push("| Pair | Ratio | WCAG AA | Note |");
lines.push("|---|---|---|---|");

const pairs = [
  ["text", "bg", ">=4.5:1", "body text on canvas"],
  ["text", "surface", ">=4.5:1", "body text on cards"],
  ["textMuted", "bg", ">=3:1", "secondary text"],
  ["textMuted", "surface", ">=3:1", "secondary text on cards"],
  ["onPrimary", "primary", ">=4.5:1", "button label"],
  ["successText", "bg", ">=3:1", "success message"],
  ["warningText", "bg", ">=3:1", "warning message"],
  ["savingsText", "bg", ">=3:1", "savings amount"],
  ["accent4", "bg", ">=3:1", "lacquer accent visibility"],
  ["primary", "bg", ">=3:1", "focus ring"],
  ["borderComposite", "bg", ">=1.2:1", "border on bg visual separation"],
];

for (const [f, b, threshold, note] of pairs) {
  let r;
  if (f === "borderComposite") {
    r = ratio(borderComp, map.bg.rgb);
  } else {
    r = ratio(map[f].rgb, map[b].rgb);
  }
  const pass = r >= parseFloat(threshold) ? "PASS" : "FAIL";
  lines.push("| " + map[f]?.label + " on " + (b === "bg" ? "bg" : map[b]?.label) + " | **" + r + ":1** | " + threshold + " | " + pass + " " + note + " |");
}

lines.push("");
lines.push("## Full Matrix", "");
const header = "| Token | " + tokens.map(t => t.label).join(" | ") + " |";
lines.push(header);
lines.push("|---|" + tokens.map(() => "---").join("|") + "|");

for (const f of tokens) {
  const row = "| **" + f.label + "** | " + tokens.map(b => ratio(map[f.key].rgb, map[b.key].rgb) + ":1").join(" | ") + " |";
  lines.push(row);
}

writeFileSync(OUT, lines.join("\n") + "\n");
console.log("Written " + OUT);
