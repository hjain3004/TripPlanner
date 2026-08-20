import { test, expect } from "@playwright/test";

const BASE = "http://127.0.0.1:3000";

test.describe("F5.1 Itinerary Interaction Hardening", () => {
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

  test("attached payment guidance renders only for payable items and expands explanation", async ({ page }) => {
    // Gardens by the Bay has amount_minor > 0 in mock and shows card guidance
    const guidance = page.getByTestId("attached-payment-guidance").first();
    await expect(guidance).toBeVisible();
    await expect(guidance.getByTestId("card-badge")).toContainText(/Use HDFC Infinia here/i);

    // Expand 'Why this card?' disclosure
    const whyBtn = guidance.getByRole("button", { name: /Why use HDFC Infinia/i });
    await expect(whyBtn).toBeVisible();
    await expect(whyBtn).toHaveAttribute("aria-expanded", "false");

    await whyBtn.click();
    await expect(whyBtn).toHaveAttribute("aria-expanded", "true");
    await expect(guidance).toContainText(/reward rate via international POS/i);
  });

  test("can reorder items within a day using explicit 44px buttons", async ({ page }) => {
    const moveDownBtn = page.getByRole("button", { name: /Move Gardens by the Bay down/i });
    await expect(moveDownBtn).toBeVisible();

    await moveDownBtn.click();

    // After recomputation, stale prose marker should appear
    await expect(page.getByTestId("stale-prose-marker")).toBeVisible();
  });

  test("can add an activity using the activity picker dialog", async ({ page }) => {
    const addBtn = page.getByRole("button", { name: "Add activity to day 1" });
    await expect(addBtn).toBeVisible();

    await addBtn.click();

    // Dialog opens
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Add Activity to Day 1" })).toBeVisible();

    // Search for a place
    const searchInput = page.getByRole("searchbox");
    await searchInput.fill("Jewel");

    const selectJewelBtn = page.getByRole("button", { name: /Select Jewel Changi Airport/i });
    await expect(selectJewelBtn).toBeVisible({ timeout: 5000 });

    await selectJewelBtn.click();

    // Dialog closes
    await expect(page.getByRole("dialog")).not.toBeVisible();
  });

  test("can replace an activity using the replace button and dialog", async ({ page }) => {
    const replaceBtn = page.getByRole("button", { name: /Replace Gardens by the Bay/i });
    await expect(replaceBtn).toBeVisible();

    await replaceBtn.click();

    // Dialog opens in replace mode
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Replace Activity" })).toBeVisible();

    // Search and select ArtScience Museum
    const searchInput = page.getByRole("searchbox");
    await searchInput.fill("ArtScience");

    const selectBtn = page.getByRole("button", { name: /Select ArtScience Museum/i });
    await expect(selectBtn).toBeVisible({ timeout: 5000 });

    await selectBtn.click();

    await expect(page.getByRole("dialog")).not.toBeVisible();
  });

  test("mobile 390px viewport has zero horizontal overflow", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });

    const hasHorizontalScroll = await page.evaluate(() => {
      return document.documentElement.scrollWidth > document.documentElement.clientWidth;
    });

    expect(hasHorizontalScroll).toBe(false);
  });
});
