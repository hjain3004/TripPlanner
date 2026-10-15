import { expect, test } from "@playwright/test";

const ASSET_PATH = "/img/japan/philatelic/japan-atlas-stamp-01.webp";

test.describe("typed DestinationStamp boundary", () => {
  test("natural landing route does not fetch the philatelic asset", async ({ page }) => {
    const fetched: string[] = [];
    page.on("response", (response) => {
      const url = response.url();
      if (url.includes(ASSET_PATH)) fetched.push(url);
    });

    await page.goto("/");
    await page.waitForLoadState("networkidle");

    expect(fetched).toEqual([]);
  });

  test("theme proof exposes diagnostic decorative and informative stamp specimens", async ({ page }) => {
    await page.goto("/theme-proof?theme=japan");

    await expect(page.getByRole("heading", { name: "Philatelic artifact proof" })).toBeVisible();

    const decorative = page.getByTestId("stamp-proof-decorative");
    await expect(decorative.locator("img")).toHaveAttribute("alt", "");
    await expect(decorative).not.toContainText("DEL → TYO");

    const informative = page.getByTestId("stamp-proof-informative");
    const image = informative.getByRole("img", { name: "Fictional Atlas Japan travel stamp" });
    await expect(image).toBeVisible();
    await expect(image).not.toHaveAttribute("alt", /DEL|TYO|2026-11-03/);

    await expect(informative.getByText("DEL → TYO")).toBeVisible();
    await expect(informative.getByText("2026-11-03")).toBeVisible();
  });

  test("route and date remain readable at 200 percent zoom", async ({ page }) => {
    await page.goto("/theme-proof?theme=japan");
    await page.evaluate(() => {
      document.documentElement.style.zoom = "2";
    });

    const stamp = page.getByTestId("stamp-proof-informative");
    const route = stamp.getByText("DEL → TYO");
    const date = stamp.getByText("2026-11-03");
    const postmark = stamp.getByTestId("destination-stamp-postmark");

    await expect(route).toBeVisible();
    await expect(date).toBeVisible();

    const [routeBox, dateBox, postmarkBox] = await Promise.all([
      route.boundingBox(),
      date.boundingBox(),
      postmark.boundingBox(),
    ]);

    expect(routeBox).not.toBeNull();
    expect(dateBox).not.toBeNull();
    expect(postmarkBox).not.toBeNull();

    if (routeBox && dateBox && postmarkBox) {
      expect(postmarkBox.x).toBeGreaterThan(routeBox.x + routeBox.width);
      expect(postmarkBox.x).toBeGreaterThan(dateBox.x + dateBox.width);
    }
  });

  test("reduced motion leaves the full artifact visible", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "reduced-motion", "reduced motion assertion only");

    await page.goto("/theme-proof?theme=japan");

    const stamp = page.getByTestId("stamp-proof-informative");
    await expect(stamp.getByRole("img", { name: "Fictional Atlas Japan travel stamp" })).toBeVisible();
    await expect(stamp.getByText("DEL → TYO")).toBeVisible();
    await expect(stamp.getByText("2026-11-03")).toBeVisible();
    await expect(stamp.getByTestId("destination-stamp-postmark")).toBeVisible();
  });
});
