import { test, expect } from "@playwright/test";

const BASE = "http://localhost:3000";

test("nested theme scope — @theme inline resolves correctly inside overridden subtree", async ({ page }) => {
  await page.goto(BASE + "/theme-proof");

  const outside = page.locator("[data-testid='outside-primary']");
  const inside = page.locator("[data-testid='inside-primary']");

  const outsideColor = await outside.evaluate((el) => getComputedStyle(el).backgroundColor);
  const insideColor = await inside.evaluate((el) => getComputedStyle(el).backgroundColor);

  expect(outsideColor).not.toBe("rgba(0, 0, 0, 0)");
  expect(insideColor).not.toBe("rgba(0, 0, 0, 0)");
  expect(outsideColor).not.toBe(insideColor);
});
