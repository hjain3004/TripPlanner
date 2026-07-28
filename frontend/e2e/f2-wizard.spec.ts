import { test, expect } from "@playwright/test";

const BASE = "http://localhost:3000";
const PLAN_URL = BASE + "/plan";

test.describe("F2 wizard: happy path", () => {
  test("full 5-step flow submits and renders report", async ({ page }) => {
    await page.goto(PLAN_URL);

    // Step 1 — Trip basics
    await expect(page.locator("h1")).toContainText("Where are you going?");
    await page.fill("#origin", "DEL");
    await page.fill("#destination", "SIN");
    await page.fill("#start-date", "2026-08-01");
    await page.fill("#end-date", "2026-08-05");
    await page.fill("#travelers", "2");
    await page.locator("button").filter({ hasText: "Next" }).click();

    // Step 2 — Wallet
    await expect(page.locator("h1")).toContainText("Your cards and points");
    await page.fill("#card-ids", "hdfc-infinia");
    await page.fill("#points", "voyager-prime:140000");
    await page.locator("button").filter({ hasText: "Next" }).click();

    // Step 3 — Preferences
    await expect(page.locator("h1")).toContainText("Trip preferences");
    await page.fill("#interests", "nature, food");
    await page.locator("button").filter({ hasText: "Next" }).click();

    // Step 4 — Review
    await expect(page.locator("h1")).toContainText("Review your trip");
    await expect(page.locator("#raw-preview")).toBeVisible();
    await expect(page.locator("#raw-preview")).not.toBeEmpty();
    await page.locator("button").filter({ hasText: "Next" }).click();

    // Step 5 — Submit
    await expect(page.locator("h1")).toContainText("Ready to generate");
    await page.locator("button").filter({ hasText: "Generate plan" }).click();

    // Wait for report to render (MSW mock returns quickly in production)
    await expect(page.getByTestId("results-view")).toBeVisible({ timeout: 15000 });
    await expect(page.locator("h1")).toContainText(/Your.*plan/);
  });
});

test.describe("F2 wizard: clarification loop", () => {
  test("intercepted clarification returns user to step 4", async ({ page }) => {
    await page.goto(PLAN_URL);

    // Override MSW's GET /plan/:jobId to return clarification instead of completing
    await page.waitForFunction(() => !!(globalThis as unknown as Record<string, unknown>).__msw);
    await page.evaluate(() => {
      const msw = (globalThis as unknown as Record<string, unknown>).__msw as {
        worker: { use: (...h: unknown[]) => void };
        http: { get: (p: string, h: () => unknown) => unknown };
        HttpResponse: { json: (d: unknown, s?: { status?: number }) => unknown };
      };
      msw.worker.use(
        msw.http.get("http://localhost:8000/plan/:jobId", () => {
          return msw.HttpResponse.json({
            job_id: "clarify-001",
            status: "needs_clarification",
            stage: null,
            stage_index: null,
            stages_total: 6,
            unresolved: ["origin city unclear", "travel dates needed"],
          });
        })
      );
    });

    // Fill steps 1-4 quickly
    await page.fill("#origin", "DEL");
    await page.fill("#destination", "SIN");
    await page.fill("#start-date", "2026-08-01");
    await page.fill("#end-date", "2026-08-05");
    await page.fill("#travelers", "1");
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();

    // Submit
    await page.locator("button").filter({ hasText: "Generate plan" }).click();

    // Clarification UI
    await expect(page.getByText("A few details needed")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("origin city unclear")).toBeVisible();
    await expect(page.getByText("travel dates needed")).toBeVisible();

    // Return to review
    await page.locator("button").filter({ hasText: "Return to review" }).click();
    await expect(page.locator("h1")).toContainText("Review & fix details");
  });
});

test.describe("F2 wizard: focus management", () => {
  test("focus moves to heading on step transition", async ({ page }) => {
    await page.goto(PLAN_URL);
    await page.fill("#origin", "DEL");
    await page.fill("#destination", "SIN");
    await page.fill("#start-date", "2026-08-01");
    await page.fill("#end-date", "2026-08-05");
    await page.fill("#travelers", "2");
    await page.locator("button").filter({ hasText: "Next" }).click();

    const focused = page.locator("h1:focus");
    await expect(focused).toHaveText("Your cards and points");
  });
});

test.describe("F2 wizard: accessibility", () => {
  test("no aXe violations on wizard plan page", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "aXe only in chromium");
    const AxeBuilder = (await import("@axe-core/playwright")).default;
    await page.goto(PLAN_URL);
    await page.fill("#origin", "DEL");
    await page.fill("#destination", "SIN");
    await page.fill("#start-date", "2026-08-01");
    await page.fill("#end-date", "2026-08-05");
    await page.fill("#travelers", "2");
    await page.locator("button").filter({ hasText: "Next" }).click();

    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });
});
