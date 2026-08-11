import { expect, test } from "@playwright/test";

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
});
