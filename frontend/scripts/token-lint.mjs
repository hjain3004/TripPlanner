#!/usr/bin/env node
/**
 * token-lint.mjs — zero-dependency gate linter for F1 token discipline.
 *
 * Usage:
 *   node scripts/token-lint.mjs          # text report, exit code = violations
 *   node scripts/token-lint.mjs --json   # JSON report to stdout
 *
 * Suppress a false-positive on the next line:
 *   /* token-lint-disable-next-line <rule> -- <reason> *​/
 *   <offending code>
 *
 * The reason is required (non-empty).
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const SRC = path.join(ROOT, "src");

const EXCLUDED_DIRS = ["src/lib/api"];

const SUPPRESSION_RE = /\/\*\s*token-lint-disable-next-line\s+(\S+)\s*--\s*(.+?)\s*\*\//;

// ---- helpers -----------------------------------------------------------

function walk(dir, exts = [".tsx", ".ts", ".css", ".js", ".jsx", ".mjs"]) {
  const files = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory() && !entry.name.startsWith(".") && entry.name !== "node_modules") {
      files.push(...walk(p, exts));
    } else if (entry.isFile() && exts.some((e) => p.endsWith(e))) {
      files.push(p);
    }
  }
  return files;
}

function readLines(file) {
  return fs.readFileSync(file, "utf-8").split("\n");
}

function isSuppressed(lines, i, rule) {
  if (i === 0) return false;
  const prev = lines[i - 1].trim();
  const m = prev.match(SUPPRESSION_RE);
  if (!m) return false;
  if (m[1] !== rule) return false;
  if (m[2].trim().length < 1) {
    console.warn(`  ⚠ suppression at ${path.relative(ROOT, lines[i - 1])} has empty reason`);
    return false;
  }
  return true;
}

function isTheme(path) {
  return path.includes("themes/");
}

function isVendor(path) {
  return path.includes("components/ui/");
}

// ---- rules -------------------------------------------------------------

const rules = [];

function rule(name, description, check) {
  rules.push({ name, description, check });
}

// R1: No raw color literals in product code
rule(
  "no-color-literals",
  "Raw color literals forbidden in src/app/, src/components/, src/lib/motion/",
  ({ violations, lines, file, rel }) => {
    if (isTheme(rel)) return;
    const hexRGB = /#[0-9a-fA-F]{3,8}\b/;
    const oklch = /oklch\(/;
    const rgba = /rgba?\(/;
    const hsla = /hsla?\(/;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      // Strip SVG anchor, url(#), and HTML-entity contexts (&#...; — numeric entities contain #hex which false-matches as a color literal)
      const stripped = line.replace(/href\s*=\s*["'][#][^"']*["']/g, "").replace(/url\(\s*#[^)]*\)/g, "").replace(/&#\d+;/g, "");
      if (hexRGB.test(stripped) || oklch.test(stripped) || rgba.test(stripped) || hsla.test(stripped)) {
        if (!isSuppressed(lines, i, "no-color-literals")) {
          violations.push({ rule: "no-color-literals", file: rel, line: i + 1, text: line.trim() });
        }
      }
    }
  }
);

// R2: No inline <svg> outside components/ui/
rule(
  "no-inline-svg",
  "Inline <svg> forbidden outside components/ui/ (use Lucide icons)",
  ({ violations, lines, file, rel }) => {
    if (isVendor(rel)) return;
    for (let i = 0; i < lines.length; i++) {
      if (/<svg\b/.test(lines[i]) && !isSuppressed(lines, i, "no-inline-svg")) {
        violations.push({ rule: "no-inline-svg", file: rel, line: i + 1, text: lines[i].trim() });
      }
    }
  }
);

// R3: No radius logical-side utilities and no raw radius values
rule(
  "no-radius-violations",
  "rounded-s*/rounded-e* utilities and raw border-radius values forbidden in product code",
  ({ violations, lines, file, rel }) => {
    if (isVendor(rel) || isTheme(rel)) return;
    // Forbid logical-side radius utilities (shadow --radius-s)
    const logicalRadius = /\brounded-[se](?:[se]|-[me])?\b/;
    // Forbid bare border-radius in CSS/JSX style strings
    const rawBorderRadius = /border-radius\s*:/;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if ((logicalRadius.test(line) || rawBorderRadius.test(line)) && !isSuppressed(lines, i, "no-radius-violations")) {
        violations.push({ rule: "no-radius-violations", file: rel, line: i + 1, text: line.trim() });
      }
    }
  }
);

// R4: No hardcoded duration or cubic-bezier
rule(
  "no-hardcoded-timing",
  "Hardcoded duration/cubic-bezier forbidden in product code — use --dur-* / --ease-brand tokens",
  ({ violations, lines, file, rel }) => {
    if (isVendor(rel) || isTheme(rel) || rel.includes("lib/motion/")) return;
    const durationMs = /\b\d+ms\b/;
    const durationS = /\b\d*\.?\d+s\b/;
    const bezier = /cubic-bezier\(/;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if ((durationMs.test(line) || durationS.test(line) || bezier.test(line)) && !isSuppressed(lines, i, "no-hardcoded-timing")) {
        violations.push({ rule: "no-hardcoded-timing", file: rel, line: i + 1, text: line.trim() });
      }
    }
  }
);

// R5: globals.css must equal the 4-line manifest
rule(
  "globals-manifest",
  "globals.css must equal the 4-line manifest",
  ({ violations, lines, file, rel }) => {
    if (!rel.endsWith("globals.css")) return;
    const expected = [
      '@import "tailwindcss"',
      '@import "tw-animate-css"',
      '@import "../themes/base.css"',
      '@import "../themes/singapore.css"',
    ];
    const actual = lines.map((l) => l.trim().replace(/;$/, "")).filter(Boolean);
    for (let i = 0; i < Math.max(expected.length, actual.length); i++) {
      if (expected[i] !== actual[i]) {
        violations.push({
          rule: "globals-manifest",
          file: rel,
          line: i + 1,
          text: `expected "${expected[i] ?? ""}", got "${actual[i] ?? ""}"`,
        });
      }
    }
  }
);

// R6: No shadcn vendor utility names outside components/ui/
rule(
  "no-vendor-utilities",
  "shadcn vendor utility names forbidden outside components/ui/",
  ({ violations, lines, file, rel }) => {
    if (isVendor(rel)) return;
    // These exact (non-semantic) shadcn vendor names must stay inside components/ui/.
    // Our own tokens (--color-accent-1..4 etc.) are fine — only match the plain vendor forms.
    const vendorPatterns = [
      /\bbg-background\b(?![\w-])/,
      /\btext-muted-foreground\b(?![\w-])/,
      /\bborder-input\b(?![\w-])/,
      /\bring-ring\b(?![\w-])/,
      /\bbg-card\b(?![\w-])/,
      /\btext-card-foreground\b(?![\w-])/,
      /\bbg-popover\b(?![\w-])/,
      /\btext-popover-foreground\b(?![\w-])/,
      /\bbg-secondary\b(?![\w-])/,
      /\btext-secondary-foreground\b(?![\w-])/,
      /\bbg-muted\b(?![\w-])/,
      /\bbg-accent\b(?![\w-])/,
      /\btext-accent-foreground\b(?![\w-])/,
      /\bbg-destructive\b(?![\w-])/,
      /\btext-destructive-foreground\b(?![\w-])/,
    ];
    for (let i = 0; i < lines.length; i++) {
      for (const pat of vendorPatterns) {
        if (pat.test(lines[i]) && !isSuppressed(lines, i, "no-vendor-utilities")) {
          violations.push({ rule: "no-vendor-utilities", file: rel, line: i + 1, text: lines[i].trim() });
        }
      }
    }
  }
);

// R7: No dark: variant or next-themes in product code (vendor exempted)
rule(
  "no-dark-mode",
  "No dark: variant or next-themes usage allowed",
  ({ violations, lines, file, rel }) => {
    if (isVendor(rel)) return;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if ((/\bdark:/.test(line) || /next-themes/.test(line) || /next\/themes/.test(line)) && !isSuppressed(lines, i, "no-dark-mode")) {
        violations.push({ rule: "no-dark-mode", file: rel, line: i + 1, text: line.trim() });
      }
    }
  }
);

// R8: No var(--color-*) or var(--th-*) in product code
rule(
  "no-direct-var",
  "var(--color-*) and var(--th-*) forbidden in product code — use Tailwind utilities",
  ({ violations, lines, file, rel }) => {
    if (isTheme(rel) || isVendor(rel)) return;
    const varPat = /var\(--(?:color|th)-/;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      // Allow through-var references in base.css bridge
      if (line.trim().startsWith("--color-") || line.trim().startsWith("--th-")) continue;
      if (varPat.test(line) && !isSuppressed(lines, i, "no-direct-var")) {
        violations.push({ rule: "no-direct-var", file: rel, line: i + 1, text: line.trim() });
      }
    }
  }
);

// R9: No arbitrary color values (bg-[#...] etc.)
rule(
  "no-arbitrary-color",
  "Arbitrary color values (bg-[#...]) forbidden",
  ({ violations, lines, file, rel }) => {
    if (isTheme(rel) || isVendor(rel)) return;
    const arbColor = /(?:bg|text|border|ring|outline|shadow|accent|caret|fill|stroke)-\[(?:#[^\]]+|oklch[^\]]+|rgb[^\]]+|hsl[^\]]+)\]/i;
    for (let i = 0; i < lines.length; i++) {
      if (arbColor.test(lines[i]) && !isSuppressed(lines, i, "no-arbitrary-color")) {
        violations.push({ rule: "no-arbitrary-color", file: rel, line: i + 1, text: lines[i].trim() });
      }
    }
  }
);

// R10: No localStorage/sessionStorage
rule(
  "no-web-storage",
  "localStorage and sessionStorage are forbidden",
  ({ violations, lines, file, rel }) => {
    for (let i = 0; i < lines.length; i++) {
      if (/(?:localStorage|sessionStorage)/.test(lines[i]) && !isSuppressed(lines, i, "no-web-storage")) {
        violations.push({ rule: "no-web-storage", file: rel, line: i + 1, text: lines[i].trim() });
      }
    }
  }
);

// R11: No tailwind.config.* file
rule(
  "no-tailwind-config",
  "tailwind.config.* must not exist (Tailwind v4 uses CSS-first config)",
  ({ violations }) => {
    const configFiles = ["tailwind.config.js", "tailwind.config.ts", "tailwind.config.mjs", "tailwind.config.cjs"];
    for (const cf of configFiles) {
      if (fs.existsSync(path.join(ROOT, cf))) {
        violations.push({ rule: "no-tailwind-config", file: cf, line: 1, text: `Forbidden file exists: ${cf} (Tailwind v4 uses CSS-first config)` });
      }
    }
  }
);

// R12: No framer-motion in package.json dependencies
rule(
  "no-framer-motion",
  "framer-motion must not be a direct dependency — use motion package (transitive framer-motion dep from motion is OK)",
  ({ violations }) => {
    const pkg = path.join(ROOT, "package.json");
    if (!fs.existsSync(pkg)) return;
    const p = JSON.parse(fs.readFileSync(pkg, "utf-8"));
    const allDeps = { ...(p.dependencies || {}), ...(p.devDependencies || {}) };
    if (allDeps["framer-motion"]) {
      violations.push({ rule: "no-framer-motion", file: "package.json", line: 1, text: "framer-motion is a direct dependency — should use motion package instead" });
    }
  }
);

// ---- runner ------------------------------------------------------------

function run() {
  const jsonMode = process.argv.includes("--json");
  const violations = [];

  for (const file of walk(SRC)) {
    const rel = path.relative(ROOT, file);
    if (EXCLUDED_DIRS.some((d) => rel.startsWith(d + "/"))) continue;
    const lines = readLines(file);
    for (const r of rules) {
      r.check({ violations, lines, file, rel });
    }
  }

  // Sort violations by file, then line
  violations.sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line);

  if (jsonMode) {
    process.stdout.write(JSON.stringify({ violations, ruleCount: rules.length }, null, 2) + "\n");
  } else {
    if (violations.length > 0) {
      console.log(`token-lint: ${violations.length} violation(s) across ${rules.length} rules\n`);
      let currentFile = "";
      for (const v of violations) {
        if (v.file !== currentFile) {
          console.log(`  ${v.file}`);
          currentFile = v.file;
        }
        console.log(`    L${v.line}:${v.rule} — ${v.text}`);
      }
    } else {
      console.log(`token-lint: 0 violations across ${rules.length} rules. PASS`);
    }
  }

  process.exit(violations.length > 0 ? 1 : 0);
}

run();
