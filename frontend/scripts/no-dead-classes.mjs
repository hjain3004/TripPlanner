#!/usr/bin/env node
/**
 * no-dead-classes.mjs — mechanical gate that catches Tailwind utility classes
 * which don't exist in the compiled production CSS (silent no-op classes).
 *
 * Usage:
 *   node scripts/no-dead-classes.mjs          # text report, exit code = violations
 *   node scripts/no-dead-classes.mjs --json   # JSON report
 *
 * Requires a completed production build (npm run build) so .next/ exists.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const NEXT_DIR = path.join(ROOT, ".next");
const SRC = path.join(ROOT, "src");

// Product code directories to scan (excludes vendor shadcn components which use vendor utility names via CSS bridge)
const PRODUCT_DIRS = [
  "src/app",
  "src/components/product",
  "src/lib/motion",
];

const SUPPRESSION_RE = /\/\*\s*token-lint-disable-next-line\s+(?:\S+\s+)*no-dead-classes(?:\s+\S+)*\s*--\s*(.+?)\s*\*\//;

// Color-bearing utility prefixes that can silently fail (generate no CSS)
const COLOR_PREFIXES = [
  "text-", "bg-", "border-", "ring-", "fill-", "stroke-",
  "shadow-", "outline-", "divide-", "from-", "via-", "to-",
  "accent-", "caret-", "placeholder-", "decoration-",
];

// Known non-Tailwind selectors used as JS/CSS hooks — allowlisted with explicit comment
const ALLOWLIST_SELECTORS = [
  "gsap-section",       // queried by gsap-entrance.tsx
  "theme-proof",        // <style> block in theme-proof/page.tsx
];

function isProductFile(rel) {
  return PRODUCT_DIRS.some((d) => rel.startsWith(d + "/"));
}

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

// Extract all Tailwind-like utility classes from a string (handles template literals, ternaries, etc.)
function extractUtilityClasses(str) {
  const classes = new Set();
  // Match sequences like: bg-primary text-text-on-primary hover:bg-accent-2
  // Tailwind utilities: [prefix]-[value] with modifiers (hover:, focus:, etc.)
  // Skip arbitrary value classes like text-[10px], border-[3px], shadow-[0_0_0_2px_...]
  // because they compile to direct CSS values and don't appear in compiled CSS
  // First strip suppression comments (must run first so suppressions still register)
  let stripped = str.replace(/\/\*\s*token-lint-disable-next-line\s+(?:\S+\s+)*no-dead-classes(?:\s+\S+)*\s*--\s*.+?\s*\*\//g, "");
  // Then strip all comment bodies: // to EOL and /* ... */ spans
  stripped = stripped
    .replace(/\/\/.*$/gm, "")
    .replace(/\/\*[\s\S]*?\*\//g, "");
  const utilRegex = /(?:^|\s)(?:(?:hover|focus|active|disabled|group-hover|peer-hover|dark|md|lg|xl|2xl|max|min|supports|has|group|peer|data|aria|before|after|first|last|odd|even|visited|target|open|file|marker|selection|placeholder|autofill|required|optional|invalid|valid|in-range|out-of-range|read-only|read-write|enabled|disabled|indeterminate|checked|default|placeholder-shown|focus-visible|focus-within):)*([a-z-]+(?:\[[^\]]+\])?(?:-\d+(?:\.\d+)?)?(?:\/\d+)?)(?=\s|$|"|'|`|\)|\}|>)/gi;
  let match;
  while ((match = utilRegex.exec(stripped)) !== null) {
    const util = match[1];
    // Skip arbitrary value classes (they compile to direct CSS, not preserved as class names)
    if (util.includes("[")) continue;
    // Only keep color-bearing prefixes
    if (COLOR_PREFIXES.some((p) => util.startsWith(p))) {
      classes.add(util);
    }
  }
  return classes;
}

// Get all CSS class names that actually exist in the compiled production CSS
function getCompiledUtilityClasses() {
  const cssFiles = [];

  function findCss(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        findCss(p);
      } else if (entry.name.endsWith(".css")) {
        cssFiles.push(p);
      }
    }
  }

  if (!fs.existsSync(NEXT_DIR)) {
    console.error("ERROR: .next/ directory not found. Run `npm run build` first.");
    process.exit(1);
  }

  findCss(NEXT_DIR);

  const compiledClasses = new Set();
  const utilClassRegex = /\.(text|bg|border|ring|fill|stroke|shadow|outline|divide|from|via|to|accent|caret|placeholder|decoration)-[^{},\s]+/g;

  for (const cssFile of cssFiles) {
    const css = fs.readFileSync(cssFile, "utf-8");
    let match;
    while ((match = utilClassRegex.exec(css)) !== null) {
      compiledClasses.add(match[0].slice(1)); // strip leading '.'
    }
  }

  // Also scan HTML files for inlined styles (Next.js 16 inlines some utilities in HTML)
  function findHtml(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        findHtml(p);
      } else if (entry.name.endsWith(".html")) {
        const html = fs.readFileSync(p, "utf-8");
        // Find <style>...</style> blocks
        const styleRegex = /<style[^>]*>([\s\S]*?)<\/style>/gi;
        let match;
        while ((match = styleRegex.exec(html)) !== null) {
          const styleContent = match[1];
          let utilMatch;
          while ((utilMatch = utilClassRegex.exec(styleContent)) !== null) {
            compiledClasses.add(utilMatch[0].slice(1));
          }
        }
      }
    }
  }
  findHtml(NEXT_DIR);

  return compiledClasses;
}

function isSuppressed(lines, i) {
  if (i === 0) return false;
  const prev = lines[i - 1].trim();
  const m = prev.match(SUPPRESSION_RE);
  if (!m) return false;
  if (m[1].trim().length < 1) {
    console.warn(`  ⚠ suppression has empty reason`);
    return false;
  }
  return true;
}

function run() {
  const jsonMode = process.argv.includes("--json");
  const violations = [];

  // 1. Get all utility classes that actually exist in compiled CSS
  console.log("Scanning compiled CSS in .next/ ...");
  const compiledClasses = getCompiledUtilityClasses();
  console.log(`Found ${compiledClasses.size} utility classes in production CSS`);

  // 2. Scan source for color-bearing utility usage
  const usedClasses = new Map();

  for (const file of walk(SRC)) {
    const rel = path.relative(ROOT, file);
    if (!isProductFile(rel)) continue;
    const content = fs.readFileSync(file, "utf-8");
    const lines = content.split("\n");

    // Find all comment ranges in the original content: [start, end) positions
    const commentRanges = [];
    let inBlockComment = false;
    let blockCommentStart = 0;
    for (let i = 0; i < content.length; i++) {
      if (!inBlockComment && content[i] === "/" && content[i + 1] === "*") {
        inBlockComment = true;
        blockCommentStart = i;
        i++; // skip *
      } else if (inBlockComment && content[i] === "*" && content[i + 1] === "/") {
        commentRanges.push([blockCommentStart, i + 2]);
        inBlockComment = false;
        i++; // skip /
      } else if (!inBlockComment && content[i] === "/" && content[i + 1] === "/") {
        // Line comment - find end of line
        let end = i;
        while (end < content.length && content[end] !== "\n") end++;
        commentRanges.push([i, end]);
        i = end;
      }
    }

    function inComment(pos) {
      return commentRanges.some(([start, end]) => pos >= start && pos < end);
    }

    // Extract utility classes from original content, skipping those in comments
    const utilRegex = /(?:^|[\s"'])(?:(?:hover|focus|active|disabled|group-hover|peer-hover|dark|md|lg|xl|2xl|max|min|supports|has|group|peer|data|aria|before|after|first|last|odd|even|visited|target|open|file|marker|selection|placeholder|autofill|required|optional|invalid|valid|in-range|out-of-range|read-only|read-write|enabled|disabled|indeterminate|checked|default|placeholder-shown|focus-visible|focus-within):)*([a-z-]+(?:\[[^\]]+\])?(?:-\d+(?:\.\d+)?)?(?:\/\d+)?)(?=\s|$|"|'|`|\)|\}|>)/gi;
    let match;
    while ((match = utilRegex.exec(content)) !== null) {
      const util = match[1];
      if (util.includes("[")) continue;
      if (COLOR_PREFIXES.some((p) => util.startsWith(p))) {
        const pos = match.index;
        // Skip if match is inside a comment
        if (inComment(pos)) continue;
        // Map position to line number
        const lineNum = content.substring(0, pos).split("\n").length;
        const originalLine = lines[lineNum - 1] || "";
        if (!usedClasses.has(util)) usedClasses.set(util, []);
        usedClasses.get(util).push({ file: rel, line: lineNum, text: originalLine.trim() });
      }
    }
  }

  console.log(`Found ${usedClasses.size} distinct color-bearing utility classes in source`);

  // 3. Check each used class against compiled CSS
  for (const [cls, locations] of usedClasses) {
    if (ALLOWLIST_SELECTORS.includes(cls)) continue;
    if (!compiledClasses.has(cls)) {
      // Check for suppression on the first occurrence
      const firstLoc = locations[0];
      const firstLines = readLines(path.join(ROOT, firstLoc.file));
      if (!isSuppressed(firstLines, firstLoc.line - 1)) {
        for (const loc of locations) {
          violations.push({ class: cls, file: loc.file, line: loc.line, text: loc.text });
        }
      }
    }
  }

  // Sort violations
  violations.sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line);

  if (jsonMode) {
    process.stdout.write(JSON.stringify({ violations, compiledCount: compiledClasses.size, usedCount: usedClasses.size }, null, 2) + "\n");
  } else {
    if (violations.length > 0) {
      console.log(`\nno-dead-classes: ${violations.length} dead class occurrence(s) across ${new Set(violations.map(v => v.class)).size} class(es)\n`);
      let currentFile = "";
      for (const v of violations) {
        if (v.file !== currentFile) {
          console.log(`  ${v.file}`);
          currentFile = v.file;
        }
        console.log(`    L${v.line}: ${v.class} — ${v.text}`);
      }
    } else {
      console.log(`\nno-dead-classes: 0 dead classes. PASS`);
    }
  }

  process.exit(violations.length > 0 ? 1 : 0);
}

run();