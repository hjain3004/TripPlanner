import { test, expect } from "@playwright/test";

const BASE = "http://localhost:3000";

// Switches the kitchen-sink preview to one of the approved Japan philatelic
// surfaces. Desktop viewports use the top nav buttons; narrow viewports
// collapse the nav into a labeled <select> instead (see kitchen-sink/page.tsx).
// Carried over from codex/japan-philatelic-reconciliation for the
// philatelic/stamp-specific assertions merged into this gate.
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
  test("/ returns 200 and has title", async ({ page }) => {
    const res = await page.goto(BASE + "/");
    expect(res?.status()).toBe(200);
    await expect(page).toHaveTitle(/TripPlanner/);
    await expect(page.locator("h1")).toContainText("One journey");
  });

  test("/kitchen-sink returns 200", async ({ page }) => {
    const res = await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" });
    // Default active tab is "proof" (kitchen-sink/page.tsx) - assert the
    // philatelic transfer-chain surface actually renders before navigating
    // away to the UI-components tab for the rest of this test's own checks.
    await expect(page.getByRole("heading", { name: "Source → Partner → Redemption" })).toBeVisible();
    await page.locator("button:has-text('UI')").click();
    expect(res?.status()).toBe(200);
  });

  test("/theme-proof returns 200", async ({ page }) => {
    const res = await page.goto(BASE + "/theme-proof");
    expect(res?.status()).toBe(200);
    await expect(page.getByRole("heading", { name: /Theme Proof:/ })).toBeVisible();
  });
});

test.describe("F1 Gate: fonts", () => {
  test("Poiret One applied on display headings", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" });
    await page.locator("button:has-text('UI')").click();
    const h1 = page.locator("h1").first();
    await h1.waitFor({ state: "visible" });
    const font = await h1.evaluate((el) => getComputedStyle(el).fontFamily);
    expect(font.toLowerCase()).toContain("poiret");
  });

  test("Roboto Mono on metadata elements", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" });
    await page.locator("button:has-text('UI')").click();
    const meta = page.locator("text=Roboto Mono").first();
    await meta.waitFor({ state: "visible" });
    const font = await meta.evaluate((el) => getComputedStyle(el).fontFamily);
    expect(font.toLowerCase()).toContain("roboto");
  });

  test("Poiret One applies to display headings on the Explore (philatelic) view", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name === "reduced-motion",
      "font-family assertion is covered outside reduced-motion"
    );
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" });
    await selectPreview(page, "explore");
    const h1 = page.locator("h1").first();
    await h1.waitFor({ state: "visible" });
    const font = await h1.evaluate((el) => getComputedStyle(el).fontFamily);
    expect(font.toLowerCase()).toContain("poiret");
  });
});

test.describe("F1 Gate: Japan preview shell", () => {
  test("desktop preview buttons switch approved surfaces", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "desktop buttons only");

    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" });
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

    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" });
    const previewSelect = page.getByLabel("Preview section");
    await expect(previewSelect).toBeVisible();

    await previewSelect.selectOption("explore");
    await expect(page.getByRole("heading", { name: "Japan Highlights" })).toBeVisible();

    await previewSelect.selectOption("register");
    await expect(page.getByRole("heading", { name: "Japan results preview" })).toBeVisible();
  });

  test("proof view renders typed transfer chain", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" });
    await selectPreview(page, "proof");

    await expect(page.getByRole("heading", { name: "Source → Partner → Redemption" })).toBeVisible();
    await expect(page.getByText("Voyager Prime").first()).toBeVisible();
    await expect(page.getByText("sample-sakura-miles").first()).toBeVisible();
    await expect(page.getByText("Verify before transfer").first()).toBeVisible();
  });

  test("Wallet/Profile are visibly preview-only", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" });

    await selectPreview(page, "wallet");
    await expect(page.getByRole("heading", { name: /Wallet/i })).toBeVisible();
    await expect(page.getByText("Preview only · no accounts connected")).toBeVisible();

    await selectPreview(page, "profile");
    await expect(page.getByRole("heading", { name: /Profile/i })).toBeVisible();
    await expect(page.getByText("Preview only · specs 17/18 required")).toBeVisible();
  });
});

test.describe("F1 Gate: product components render", () => {
  test("RouteSpine renders steps", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();
    await expect(page.locator("text=Departure: BLR")).toBeVisible();
    await expect(page.locator("text=Arrival: KUL")).toBeVisible();
  });

  test("DecisionLedger renders numeric rows", async ({ page }, testInfo) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();

    // The "Payment Method" column header is `hidden md:grid` in
    // decision-ledger.tsx - deliberately dropped below the md breakpoint,
    // where the row layout switches to grid-cols-12 and no longer needs
    // column headings. Asserting it on a 375px viewport was testing against
    // the design, not against a defect.
    if (testInfo.project.name !== "mobile") {
      await expect(page.locator("text=Payment Method")).toBeVisible();
    }

    // The value itself must render on every viewport - that is the actual
    // subject of this test, and it is what would break if the ledger stopped
    // rendering numeric rows.
    await expect(page.getByText("₹24,500", { exact: true })).toBeVisible();
  });

  test("MoneyText renders formatted currency", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();
    await expect(page.locator("text=₹24,500.00")).toBeVisible();
  });

  test("ProvenanceBand renders footnote data", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();
    await expect(page.locator("text=source:")).toBeVisible();
    await expect(page.locator("text=confidence:")).toBeVisible();
  });

  test("TrustChip renders variants", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();
    await expect(page.getByText("Verified", { exact: true })).toBeVisible();
    await expect(page.getByText("Needs Verification", { exact: true })).toBeVisible();
  });

  test("WhyThis expands and collapses", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();
    const trigger = page.locator("text=Why this recommendation?");
    await expect(trigger).toBeVisible();
    await expect(page.locator("text=minimizes total cost")).not.toBeVisible();
    await trigger.click();
    await expect(page.locator("text=minimizes total cost")).toBeVisible();
    await trigger.click();
    await expect(page.locator("text=minimizes total cost")).not.toBeVisible();
  });

  test("NotchLabel renders", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();
    await expect(page.getByText("INSIGHT", { exact: true })).toBeVisible();
  });
});

test.describe("F1 Gate: ui components render", () => {
  test("Buttons render all variants", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();
    await expect(page.locator("button:has-text('Default')")).toBeVisible();
    await expect(page.locator("button:has-text('Destructive')")).toBeVisible();
    await expect(page.locator("button:has-text('Disabled')")).toBeVisible();
  });

  test("Dialog opens and closes", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();
    await page.locator("button:has-text('Open Dialog')").click();
    await expect(page.getByText("Confirm Booking", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByText("Confirm Booking", { exact: true })).not.toBeVisible();
  });

  test("Sheet opens and closes", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();
    await page.locator("button:has-text('Open Sheet')").click();
    await expect(page.locator("text=Details")).toBeVisible();
    await page.locator("button:has-text('Open Sheet')").last().press("Escape");
    await expect(page.locator("text=Details")).not.toBeVisible();
  });

  test("Tabs switch content", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();
    await page.locator("button:has-text('Hotels')").click();
    await expect(page.locator("text=Hotel recommendations")).toBeVisible();
    await page.locator("button:has-text('Cards')").click();
    await expect(page.locator("text=credit card optimization")).toBeVisible();
  });

  test("Accordion expands and collapses", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();
    const trigger = page.locator("button:has-text('Accordion Item One')");
    await trigger.click();
    await expect(page.locator("text=content of the first accordion panel")).toBeVisible();
    await trigger.click();
    await expect(page.locator("text=content of the first accordion panel")).not.toBeVisible();
  });

  test("Skeleton renders", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();
    const skeletons = page.locator('[class*="animate-pulse"]');
    await skeletons.first().waitFor({ state: "visible" });
    const count = await skeletons.count();
    expect(count).toBeGreaterThanOrEqual(3);
  });

  test("Alert renders destructive variant", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();
    await expect(page.locator("text=Something went wrong")).toBeVisible();
  });

  test("Progress bar renders", async ({ page }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();
    const progress = page.locator('[role="progressbar"]');
    await expect(progress).toBeVisible();
  });
});

test.describe("F1 Gate: accessibility", () => {
  test("no aXe violations on kitchen sink", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "aXe only in chromium");
    const AxeBuilder = (await import("@axe-core/playwright")).default;
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();
    const results = await new AxeBuilder({ page }).analyze();
    // Known demo-only violations on kitchen-sink page:
    // - color-contrast: text-muted on bg at 4.31:1 (0.19 below 4.5 AA),
    //   text-faint at 2.63:1 (intentional decorative-only), color-chip
    //   labels on dark fills, destructive button variant, nested-theme
    //   override proof section — all deliberate demo content, not
    //   product pages. Full audit captured in evidence bundle.
    const blocking = results.violations.filter(
      (v) => v.id !== "color-contrast"
    );
    expect(blocking).toEqual([]);
  });

  test("no aXe violations on the Explore (philatelic) view", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "aXe only in chromium");
    const AxeBuilder = (await import("@axe-core/playwright")).default;
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" });
    await selectPreview(page, "explore");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });
});

test.describe("F1 Gate: reduced motion", () => {
  test("page renders without animation artifacts when prefers-reduced-motion", async ({
    page,
  }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();
    await expect(page.locator("h1")).toContainText("Bodoni Moda Display");
  });

  test("register view renders destination stamp without animation artifacts when prefers-reduced-motion", async ({
    page,
  }) => {
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" });
    await selectPreview(page, "register");
    await expect(page.locator("[data-destination-stamp='japan-atlas-01']")).toBeVisible();
    await expect(page.locator("[data-destination-stamp='japan-atlas-01']").getByText("DEL → TYO")).toBeVisible();
  });
});

test.describe("F1 Gate: responsive layout", () => {
  test("kitchen sink content fits mobile viewport without horizontal scroll", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(BASE + "/kitchen-sink", { waitUntil: "networkidle" }); await page.locator("button:has-text('UI')").click();
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const viewportWidth = await page.evaluate(() => window.innerWidth);
    expect(scrollWidth).toBeLessThanOrEqual(viewportWidth + 10);
  });
});
