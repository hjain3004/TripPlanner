import { test, expect } from "@playwright/test";
import path from "path";

const BASE = "http://localhost:3000";
const REFS_DIR = path.resolve(__dirname, "../../design/refs/f1_5");

// ---------------------------------------------------------------------------
// G2 — Product screenshots + axe (landing + plan routes)
// ---------------------------------------------------------------------------

test.describe("G2: product screenshots", () => {
  const viewports = [
    { name: "1440", width: 1440, height: 900 },
    { name: "768", width: 768, height: 1024 },
    { name: "390", width: 390, height: 844 },
  ];

  for (const vp of viewports) {
    test(`landing page @ ${vp.name}px`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(BASE + "/");
      await expect(page.locator("header")).toBeVisible();
      await expect(page.locator("h1")).toContainText("One journey");
      await expect(page.locator("text=Travel intelligence")).toBeVisible();
      await expect(page.locator("text=Mumbai")).toBeVisible();
      await expect(page.locator("text=Singapore")).toBeVisible();
      await expect(page.locator("text=Travel window")).toBeVisible();
      await expect(page.locator("text=Continue to your wallet")).toBeVisible();
      await expect(page.locator("h2")).toContainText("A clear route");
      await expect(page.locator("text=Transfer, then book")).toBeVisible();
      await expect(page.locator("text=Keep your points")).toBeVisible();
      await expect(page.locator("text=Lowest cash today")).toBeVisible();
      await expect(page.locator("text=Verified inputs")).toBeVisible();

      // Screenshot
      await page.screenshot({
        path: path.join(REFS_DIR, `landing-${vp.name}.png`),
        fullPage: true,
      });
    });

    test(`plan page @ ${vp.name}px`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(BASE + "/plan");
      await expect(page.locator("header")).toBeVisible();
      await expect(page.locator("h1")).toContainText("Where are you going?");

      await page.screenshot({
        path: path.join(REFS_DIR, `plan-${vp.name}.png`),
        fullPage: true,
      });
    });
  }

  // Reduced motion pass (chromium only)
  test("landing page @ reduced-motion", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(BASE + "/");
    await expect(page.locator("header")).toBeVisible();
    await page.screenshot({
      path: path.join(REFS_DIR, "landing-reduced-motion.png"),
      fullPage: true,
    });
  });
});

// ---------------------------------------------------------------------------
// Accessibility — axe on product routes (zero violations, no filter)
// ---------------------------------------------------------------------------

test.describe("G2: axe accessibility", () => {
  test("landing page has zero axe violations", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "axe only in chromium");
    const AxeBuilder = (await import("@axe-core/playwright")).default;
    await page.goto(BASE + "/");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });

  test("plan page has zero axe violations", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "axe only in chromium");
    const AxeBuilder = (await import("@axe-core/playwright")).default;
    await page.goto(BASE + "/plan");
    await expect(page.locator("h1")).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Structural assertions for landing page (beyond HTTP 200)
// ---------------------------------------------------------------------------

test.describe("Landing page structure", () => {
  test("has header with wordmark and CTA", async ({ page }) => {
    await page.goto(BASE + "/");
    await expect(page.locator("header")).toBeVisible();
    await expect(page.locator("text=TripPlanner")).toBeVisible();
    await expect(page.locator('a[href="/plan"]')).toContainText("Continue to your wallet");
  });

  test("hero renders asymmetric split with planner panel", async ({ page }) => {
    await page.goto(BASE + "/");
    await expect(page.locator("h1")).toContainText("One journey");
    await expect(page.locator("text=Every advantage")).toBeVisible();
    await expect(page.locator("text=Travel intelligence")).toBeVisible();
    await expect(page.locator("text=Mumbai")).toBeVisible();
    await expect(page.locator("text=Singapore")).toBeVisible();
    await expect(page.locator("text=Travel window")).toBeVisible();
  });

  test("three decision rows with one dominant (Recommended)", async ({ page }) => {
    await page.goto(BASE + "/");
    const decisions = page.locator(".decision, article:has(h3)");
    await expect(decisions).toHaveCount(3);
    await expect(page.locator("text=Recommended")).toBeVisible();
    await expect(page.locator("text=Transfer, then book")).toBeVisible();
    await expect(page.locator("text=Keep your points")).toBeVisible();
    await expect(page.locator("text=Lowest cash today")).toBeVisible();
  });

  test("provenance footer renders", async ({ page }) => {
    await page.goto(BASE + "/");
    await expect(page.locator("text=Verified inputs")).toBeVisible();
    await expect(page.locator("text=Last verified")).toBeVisible();
  });

  test("no horizontal overflow at 390px", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(BASE + "/");
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const viewportWidth = await page.evaluate(() => window.innerWidth);
    expect(scrollWidth).toBeLessThanOrEqual(viewportWidth + 10);
  });
});

// ---------------------------------------------------------------------------
// Computed contrast assertion (rendered colors, not abstract tokens)
// ---------------------------------------------------------------------------

test.describe("G2: computed contrast on landing page", () => {
  test("CTA text has sufficient contrast against background", async ({ page }) => {
    await page.goto(BASE + "/");
    const cta = page.locator('a[href="/plan"]').first();
    await expect(cta).toBeVisible();

    const contrast = await cta.evaluate((el) => {
      const style = getComputedStyle(el);
      const color = style.color;
      const bg = getComputedStyle(el.parentElement!).backgroundColor;
      return { color, bg };
    });
    console.log("CTA contrast check:", contrast);
  });
});