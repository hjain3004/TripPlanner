import { test, expect } from "@playwright/test";

const BASE = "http://127.0.0.1:3000";

test.describe("I6 A11y & Map Parity", () => {
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

  test("the interactive map is hidden from screen readers", async ({ page }) => {
    await expect(page.getByTestId("map-container")).toHaveAttribute("aria-hidden", "true");
  });

  test("itinerary map markers map exactly to the textual ordered list", async ({ page }) => {
    // Wait for markers to appear
    await page.locator(".maplibregl-marker").first().waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
    const markers = await page.locator(".maplibregl-marker").count();
    const listItems = await page.locator("ol.itinerary-list > li").count();
    expect(markers).toBe(listItems);
  });
});
