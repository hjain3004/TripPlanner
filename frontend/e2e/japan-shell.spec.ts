import { expect, test } from "@playwright/test";

const BASE = "http://localhost:3000";

async function htmlClassList(page: import("@playwright/test").Page): Promise<string[]> {
  return page.locator("html").evaluate((el) => Array.from(el.classList));
}

test.describe("Japan shell theme scope", () => {
  test("/ starts with the natural fallback theme", async ({ page }) => {
    await page.goto(BASE + "/");

    await expect.poll(() => htmlClassList(page)).toContain("theme-natural");
    expect(await htmlClassList(page)).not.toContain("theme-japan");
  });

  test("/theme-proof?theme=japan applies explicit Japan tokens", async ({ page }) => {
    await page.goto(BASE + "/theme-proof?theme=japan");

    await expect(page.getByRole("heading", { name: /Theme Proof: japan/i })).toBeVisible();
    await expect(page.locator(".theme-japan").first()).toBeVisible();
  });

  test("/kitchen-sink uses Japan, not Singapore", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink");

    await expect(page.locator(".theme-japan").first()).toBeVisible();
    await expect(page.locator(".theme-singapore")).toHaveCount(0);
  });

  test("mobile preview navigation changes from Proof to Explore without horizontal overflow", async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "mobile shell assertion only");

    await page.goto(BASE + "/kitchen-sink");

    const previewSelect = page.getByLabel("Preview section");
    await expect(previewSelect).toBeVisible();
    await expect(previewSelect).toHaveValue("proof");

    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const viewportWidth = await page.evaluate(() => window.innerWidth);
    expect(scrollWidth).toBeLessThanOrEqual(viewportWidth);

    await previewSelect.selectOption("explore");
    await expect(page.getByRole("heading", { name: "Japan Highlights" })).toBeVisible();
  });

  test("desktop preview buttons expose selected state", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "desktop shell assertion only");

    await page.goto(BASE + "/kitchen-sink");

    await expect(page.getByRole("button", { name: "Proof" })).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: "Explore" }).click();
    await expect(page.getByRole("button", { name: "Explore" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: "Proof" })).toHaveAttribute("aria-pressed", "false");
  });
});
