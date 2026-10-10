import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(__dirname, "..");
const SCAN_ROOTS = ["src/app", "src/components/product"].map((part) => path.join(ROOT, part));
const SOURCE_EXTENSIONS = new Set([".ts", ".tsx"]);

type Violation = {
  rule: string;
  file: string;
  line: number;
  text: string;
};

function walk(dir: string): string[] {
  const files: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    const relative = path.relative(ROOT, fullPath);
    if (entry.isDirectory()) {
      if (relative.startsWith("src/components/ui")) continue;
      files.push(...walk(fullPath));
    } else if (entry.isFile() && SOURCE_EXTENSIONS.has(path.extname(entry.name))) {
      files.push(fullPath);
    }
  }
  return files;
}

function classStrings(line: string): string[] {
  return Array.from(line.matchAll(/className=(?:"([^"]+)"|'([^']+)'|`([^`]+)`)/g)).map(
    (match) => match[1] ?? match[2] ?? match[3] ?? ""
  );
}

function collectViolations(): Violation[] {
  const violations: Violation[] = [];

  for (const file of SCAN_ROOTS.flatMap(walk)) {
    const rel = path.relative(ROOT, file);
    const lines = fs.readFileSync(file, "utf-8").split("\n");

    lines.forEach((line, index) => {
      const report = (rule: string) =>
        violations.push({ rule, file: rel, line: index + 1, text: line.trim() });

      if (/\btransition-all\b/.test(line)) report("no-transition-all");
      if (/\binitial=\{\{\s*scale:\s*0\b/.test(line)) report("no-scale-zero-entrance");
      if (/canvas-confetti/.test(line)) report("no-canvas-confetti");
      if (/(?:#000(?:000)?\b|\b(?:bg|text|border)-black\b|\bblack\b)/i.test(line)) report("no-black");

      for (const className of classStrings(line)) {
        const usesDisplay = /\bfont-display\b/.test(className);
        const fauxDisplayWeight = /\b(?:font-bold|font-semibold)\b/.test(className);
        const numericDisplay =
          /\b(?:tabular-nums|font-mono|text-savings|text-savings-text)\b/.test(className) ||
          /(?:money|point|cost|saving|total|gross|effective)/i.test(className);

        if (usesDisplay && (fauxDisplayWeight || numericDisplay)) {
          report("no-faux-or-numeric-display");
        }
      }
    });
  }

  return violations.sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line || a.rule.localeCompare(b.rule));
}

describe("Japan design drift guardrails", () => {
  it("keeps app/product source inside the approved visual contract", () => {
    expect(collectViolations()).toEqual([]);
  });
});
