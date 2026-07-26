import { chromium } from "@playwright/test";
import { writeFileSync, mkdirSync } from "fs";
import { resolve } from "path";

const BASE = process.env.BASE_URL || "http://localhost:3000";
const REFS = resolve(process.cwd(), "design/refs/f1");

mkdirSync(REFS, { recursive: true });

const widths = [390, 768, 1440];

const browser = await chromium.launch({ headless: true });

for (const w of widths) {
  const ctx = await browser.newContext({ viewport: { width: w, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" });
  await page.screenshot({ path: resolve(REFS, `kitchen-sink-${w}.png`), fullPage: true });
  console.log(`Captured kitchen-sink-${w}.png`);
  await ctx.close();
}

// Reduced-motion screenshot at 1440
{
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    reducedMotion: "reduce",
  });
  const page = await ctx.newPage();
  await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" });
  await page.screenshot({
    path: resolve(REFS, "kitchen-sink-reduced-motion.png"),
    fullPage: true,
  });
  console.log("Captured kitchen-sink-reduced-motion.png");
  await ctx.close();
}

// Axe report on kitchen-sink (Chromium desktop)
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" });
  const AxeBuilder = (await import("@axe-core/playwright")).default;
  const results = await new AxeBuilder({ page }).analyze();
  writeFileSync(resolve(REFS, "axe-report.json"), JSON.stringify(results, null, 2));
  console.log(`Axe: ${results.violations.length} violations, ${results.passes.length} passes`);
  await ctx.close();
}

await browser.close();
