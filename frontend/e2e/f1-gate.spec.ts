import { test, expect } from "@playwright/test";

const BASE = "http://localhost:3000";

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

test.describe("F1 Gate: routes", () => {
  test("/ returns 200 and has current landing hero", async ({ page }) => {
    const res = await page.goto(BASE + "/");
    expect(res?.status()).toBe(200);
    await expect(page.locator("h1")).toContainText("One journey");
  });

  test("/kitchen-sink returns 200", async ({ page }) => {
    const res = await page.goto(BASE + "/kitchen-sink");
    expect(res?.status()).toBe(200);
    await expect(page.getByRole("heading", { name: "Source → Partner → Redemption" })).toBeVisible();
  });

  test("/theme-proof returns 200", async ({ page }) => {
    const res = await page.goto(BASE + "/theme-proof");
    expect(res?.status()).toBe(200);
    await expect(page.getByRole("heading", { name: /Theme Proof:/ })).toBeVisible();
  });
});

test.describe("F1 Gate: fonts", () => {
  test("Poiret One applies to display headings", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name === "reduced-motion", "font-family assertion is covered outside reduced-motion");
    await page.goto(BASE + "/kitchen-sink");
    await selectPreview(page, "explore");
    const h1 = page.locator("h1").first();
    const font = await h1.evaluate((el) => getComputedStyle(el).fontFamily);
    expect(font.toLowerCase()).toContain("poiret");
  });

  test("Roboto Mono applies to metadata elements", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink");
    const meta = page.locator(".font-mono").first();
    const font = await meta.evaluate((el) => getComputedStyle(el).fontFamily);
    expect(font.toLowerCase()).toContain("roboto");
  });
});

test.describe("F1 Gate: Japan preview shell", () => {
  test("desktop preview buttons switch approved surfaces", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "desktop buttons only");

    await page.goto(BASE + "/kitchen-sink");
    await expect(page.getByRole("button", { name: "Proof" })).toHaveAttribute("aria-pressed", "true");

    await selectPreview(page, "explore");
    await expect(page.getByRole("heading", { name: "Japan Highlights" })).toBeVisible();
    await expect(page.locator("[data-destination-stamp='japan-atlas-01']")).toHaveCount(1);

    await selectPreview(page, "register");
    await expect(page.getByRole("heading", { name: "Japan results preview" })).toBeVisible();
    await expect(page.getByText("Your 5-day TYO plan")).toBeVisible();
  });

  test("mobile preview select switches approved surfaces", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "mobile select only");

    await page.goto(BASE + "/kitchen-sink");
    const previewSelect = page.getByLabel("Preview section");
    await expect(previewSelect).toBeVisible();

    await previewSelect.selectOption("explore");
    await expect(page.getByRole("heading", { name: "Japan Highlights" })).toBeVisible();

    await previewSelect.selectOption("register");
    await expect(page.getByRole("heading", { name: "Japan results preview" })).toBeVisible();
  });

  test("proof view renders typed transfer chain", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink");
    await selectPreview(page, "proof");

    await expect(page.getByRole("heading", { name: "Source → Partner → Redemption" })).toBeVisible();
    await expect(page.getByText("Voyager Prime").first()).toBeVisible();
    await expect(page.getByText("sample-sakura-miles").first()).toBeVisible();
    await expect(page.getByText("Verify before transfer").first()).toBeVisible();
  });

  test("Wallet/Profile are visibly preview-only", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink");

    await selectPreview(page, "wallet");
    await expect(page.getByRole("heading", { name: /Wallet/i })).toBeVisible();
    await expect(page.getByText("Preview only · no accounts connected")).toBeVisible();

    await selectPreview(page, "profile");
    await expect(page.getByRole("heading", { name: /Profile/i })).toBeVisible();
    await expect(page.getByText("Preview only · specs 17/18 required")).toBeVisible();
  });
});

test.describe("F1 Gate: accessibility", () => {
  test("no aXe violations on current kitchen sink", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "aXe only in chromium");
    const AxeBuilder = (await import("@axe-core/playwright")).default;
    await page.goto(BASE + "/kitchen-sink");
    await selectPreview(page, "explore");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });
});

test.describe("F1 Gate: reduced motion", () => {
  test("page renders without animation artifacts when prefers-reduced-motion", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink");
    await selectPreview(page, "register");
    await expect(page.locator("[data-destination-stamp='japan-atlas-01']")).toBeVisible();
    await expect(page.locator("[data-destination-stamp='japan-atlas-01']").getByText("DEL → TYO")).toBeVisible();
  });
});

test.describe("F1 Gate: responsive layout", () => {
  test("kitchen sink content fits mobile viewport without horizontal scroll", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(BASE + "/kitchen-sink");
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const viewportWidth = await page.evaluate(() => window.innerWidth);
    expect(scrollWidth).toBeLessThanOrEqual(viewportWidth + 10);
  });
});
