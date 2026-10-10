import { expect, test } from "@playwright/test";

const BASE = "http://localhost:3000";
const TABS = ["Explore", "Deals", "Itinerary", "Proof", "Wallet Preview", "Profile Preview"] as const;

async function selectPreview(page: import("@playwright/test").Page, tab: (typeof TABS)[number]) {
  const select = page.getByLabel("Preview section");
  if (await select.isVisible()) {
    await select.selectOption({ label: tab });
    return;
  }
  await page.getByRole("button", { name: tab }).click();
}

async function expectNoOverflow(page: import("@playwright/test").Page) {
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const viewportWidth = await page.evaluate(() => window.innerWidth);
  expect(scrollWidth).toBeLessThanOrEqual(viewportWidth);
}

test.describe("Figma reconciliation previews", () => {
  test("Explore keeps three destination compositions without fake deal claims", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink");
    await selectPreview(page, "Explore");

    await expect(page.getByText("Mount Fuji")).toBeVisible();
    await expect(page.getByText("Senso-ji Temple")).toBeVisible();
    await expect(page.getByText("Tokyo Tower")).toBeVisible();
    await expect(page.getByText(/Premium Redemptions|Best value|UR points/i)).toHaveCount(0);
  });

  test("Deals is sample evidence and contains no live-monitoring or invented expiry claims", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink");
    await selectPreview(page, "Deals");

    await expect(page.getByText("Sample evidence", { exact: true })).toBeVisible();
    await expect(page.getByText(/constantly monitor|active bonus|active multipliers|ends in|offering a \d+%/i)).toHaveCount(0);
  });

  test("Itinerary uses Japan fixture values and visible sample provenance", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink");
    await selectPreview(page, "Itinerary");

    await expect(page.getByText("DEL", { exact: true })).toBeVisible();
    await expect(page.getByText("TYO", { exact: true })).toBeVisible();
    await expect(page.getByText(/Frontend visual fixture|sample data/i).first()).toBeVisible();
    await expect(page.getByText(/AwardHacker API|Amex FHR|live hotel prices/i)).toHaveCount(0);
  });

  test("Proof renders a typed source to partner to redemption chain", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink");
    await selectPreview(page, "Proof");

    await expect(page.getByRole("heading", { name: "Voyager Prime" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "sample-sakura-miles" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "DEL → TYO" })).toBeVisible();
    await expect(page.getByText(/Chase Ultimate Rewards|Amex Membership Rewards|ANA First Class|JFK → HND/i)).toHaveCount(0);
  });

  test("Wallet and Profile are visibly quarantined previews", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink");

    await selectPreview(page, "Wallet Preview");
    await expect(page.getByText("Preview only", { exact: true })).toBeVisible();
    await expect(page.getByText(/4092|9011|Sync:|184,200|215,000|Global Entry|unused this year/i)).toHaveCount(0);

    await selectPreview(page, "Profile Preview");
    await expect(page.getByText("Preview only", { exact: true })).toBeVisible();
    await expect(page.getByText(/Expires 2031|TSA PreCheck|Delta SkyMiles|Marriott Bonvoy|42,500|118,000/i)).toHaveCount(0);
  });

  test("all reconciled previews fit the 390px viewport", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "mobile overflow check");

    await page.goto(BASE + "/kitchen-sink");
    for (const tab of TABS) {
      await selectPreview(page, tab);
      await expectNoOverflow(page);
    }
  });
});
