import { afterEach, expect, test } from "vitest";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });

function scan(source: string, css: string) {
  const root = mkdtempSync(join(tmpdir(), "tripplanner-css-gate-"));
  roots.push(root);
  for (const dir of ["scripts", "src/app", ".next/static/css"]) mkdirSync(join(root, dir), { recursive: true });
  const script = join(root, "scripts/no-dead-classes.mjs");
  copyFileSync(resolve("scripts/no-dead-classes.mjs"), script);
  writeFileSync(join(root, "src/app/page.tsx"), `export default () => <div className="${source}" />;`);
  writeFileSync(join(root, ".next/static/css/output.css"), css);
  return spawnSync(process.execPath, [script], { encoding: "utf8" });
}

test("emitted opacity and state-modified utilities are not reported as dead", () => {
  const result = scan(
    "bg-accent-2/60 hover:border-primary/60 focus-visible:ring-3 focus-visible:ring-primary/50",
    String.raw`.bg-accent-2\/60{background:paper}.hover\:border-primary\/60:hover{border-color:ink}.focus-visible\:ring-3:focus-visible{outline:ink}.focus-visible\:ring-primary\/50:focus-visible{outline-color:ink}`,
  );
  expect(result.status, result.stdout + result.stderr).toBe(0);
});

test("a genuinely absent utility still fails the emitted-class gate", () => {
  const result = scan("bg-invented", ".bg-surface{background:paper}");
  expect(result.status).toBe(1);
  expect(result.stdout + result.stderr).toContain("bg-invented");
});
