import { expect, test } from "@playwright/test";

const STAMP_ASSET_NAME = "japan-atlas-stamp-01.webp";

async function selectPreview(page: import("@playwright/test").Page, tab: string) {
  const mobileSelect = page.getByLabel("Preview section");
  if (await mobileSelect.isVisible()) {
    await mobileSelect.selectOption(tab);
    return;
  }
  const labels: Record<string, string> = {
    explore: "Explore",
    deals: "Deals",
    proof: "Proof",
    itinerary: "Itinerary",
    register: "Register",
    wallet: "Wallet Preview",
    profile: "Profile Preview",
  };
  await page.getByRole("button", { name: labels[tab] }).click();
}

test.describe("Japan philatelic product placement", () => {
  test("Explore has exactly one integrated decorative stamp thumbnail", async ({ page }) => {
    await page.goto("/kitchen-sink");
    await selectPreview(page, "explore");

    const stamps = page.locator("[data-destination-stamp='japan-atlas-01']");
    await expect(stamps).toHaveCount(1);

    const firstCard = page.getByRole("article").filter({ hasText: "Mount Fuji" });
    await expect(firstCard.locator("[data-destination-stamp='japan-atlas-01']")).toHaveCount(1);
    await expect(firstCard.locator("img[alt='']")).toHaveCount(1);
  });

  test("Japan results have exactly one feature stamp with fixture route and date", async ({ page }) => {
    await page.goto("/kitchen-sink");
    await selectPreview(page, "register");

    const stamps = page.locator("[data-destination-stamp='japan-atlas-01']");
    await expect(stamps).toHaveCount(1);
    await expect(stamps.first().getByRole("img", { name: "Fictional Atlas Japan travel stamp" })).toBeVisible();
    await expect(stamps.first().getByText("DEL → TYO")).toBeVisible();
    await expect(stamps.first().getByText("2026-11-03")).toBeVisible();
  });

  test("stamp does not appear on unapproved preview surfaces", async ({ page }) => {
    await page.goto("/kitchen-sink");

    for (const tab of ["deals", "proof", "itinerary", "wallet", "profile"] as const) {
      await selectPreview(page, tab);
      await expect(page.locator("[data-destination-stamp='japan-atlas-01']")).toHaveCount(0);
    }
  });

  test("ordinary landing remains stamp-free", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("[data-destination-stamp='japan-atlas-01']")).toHaveCount(0);
  });

  test("keyboard navigation reaches the approved stamp surfaces", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "desktop keyboard path only");

    await page.goto("/kitchen-sink");
    await page.getByRole("button", { name: "Explore" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Japan Highlights" })).toBeVisible();

    await page.getByRole("button", { name: "Register" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Japan results preview" })).toBeVisible();
    await expect(page.locator("[data-destination-stamp='japan-atlas-01']")).toHaveCount(1);
  });

  test("landing, Explore, and Japan results have no blocking axe violations", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "axe checks run once on desktop");
    const AxeBuilder = (await import("@axe-core/playwright")).default;

    for (const route of ["/", "/kitchen-sink?preview=explore", "/kitchen-sink?preview=register"]) {
      await page.goto(route);
      if (route.includes("explore")) await selectPreview(page, "explore");
      if (route.includes("register")) await selectPreview(page, "register");

      const results = await new AxeBuilder({ page }).analyze();
      expect(results.violations).toEqual([]);
    }
  });

  test("philatelic asset is budgeted and absent from the natural landing route", async ({ page }) => {
    const landingAssets: string[] = [];
    page.on("response", (response) => {
      if (response.url().includes(STAMP_ASSET_NAME)) landingAssets.push(response.url());
    });

    await page.goto("/");
    await page.waitForLoadState("networkidle");
    expect(landingAssets).toEqual([]);

    const responses: { url: string; bytes: number }[] = [];
    page.on("response", async (response) => {
      if (!response.url().includes(STAMP_ASSET_NAME)) return;
      responses.push({ url: response.url(), bytes: (await response.body()).byteLength });
    });

    await page.goto("/kitchen-sink");
    await selectPreview(page, "register");
    await expect(page.locator("[data-destination-stamp='japan-atlas-01']")).toHaveCount(1);
    await page.waitForLoadState("networkidle");

    expect(responses.length).toBeGreaterThanOrEqual(1);
    const uniqueBytes = new Map(responses.map((response) => [response.url, response.bytes]));
    const totalBytes = Array.from(uniqueBytes.values()).reduce((sum, bytes) => sum + bytes, 0);
    expect(totalBytes).toBeLessThan(250 * 1024);
  });

  test("approved stamp routes produce no console errors or failed asset requests", async ({ page }) => {
    const consoleErrors: string[] = [];
    const failedRequests: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("requestfailed", (request) => failedRequests.push(request.url()));

    for (const tab of ["explore", "register"] as const) {
      await page.goto("/kitchen-sink");
      await selectPreview(page, tab);
      await page.waitForLoadState("networkidle");
    }

    expect(consoleErrors.filter((message) => !message.includes("Failed to load resource"))).toEqual([]);
    expect(failedRequests).toEqual([]);
  });
});
