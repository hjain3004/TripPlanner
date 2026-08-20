import { test, expect } from "@playwright/test";

const BASE = "http://127.0.0.1:3000";

test.describe("I6 Itinerary Evidence & Routing", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(BASE + "/plan");

    await page.fill("#origin", "DEL");
    await page.fill("#destination", "SIN");
    await page.fill("#start-date", "2026-08-01");
    await page.fill("#end-date", "2026-08-05");
    await page.fill("#travelers", "2");
    await page.locator("button").filter({ hasText: "Next" }).click();

    await page.fill("#card-ids", "hdfc-infinia");
    await page.fill("#points", "voyager-prime:140000");
    await page.locator("button").filter({ hasText: "Next" }).click();

    await page.fill("#interests", "nature, food");
    await page.locator("button").filter({ hasText: "Next" }).click();

    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Generate plan" }).click();

    await expect(page.getByTestId("results-view")).toBeVisible({ timeout: 15000 });
  });

  test("an estimated travel time is never labelled as routed", async ({ page }) => {
    await expect(page.getByTestId("travel-0").first()).toContainText(/estimated/i);
  });

  test("a verify-required venue shows its badge, not a silent gap", async ({ page }) => {
    await expect(page.getByTestId("evidence-badge").first()).toBeVisible();
  });

  test("a partial day states why, in structured terms", async ({ page }) => {
    await expect(page.getByTestId("day-unmet").first()).toContainText(/travel budget|no candidate/i);
  });

  test("no storage is written", async ({ page }) => {
    const n = await page.evaluate(() => localStorage.length + sessionStorage.length);
    expect(n).toBe(0);
  });
});
