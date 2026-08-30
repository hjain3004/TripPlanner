import { test, expect, type Page } from "@playwright/test";

const BASE = "http://localhost:3000";

test.use({ serviceWorkers: "block" });

function profile(cabin: "business" | null = "business") {
  const leaf = (value: unknown) => value === null ? null : { value, source: "user_profile_edit", updated_at: "2026-08-29T00:00:00Z" };
  return {
    user_id: "msw-user-001",
    updated_at: "2026-08-29T00:00:00Z",
    flight: { cabin: leaf(cabin), max_stops: null, schedule: null, checked_baggage: null, airport_flexible: null, seat: null },
    stay: { lodging_styles: null, location_priorities: null, room_needs: null, location_price_tradeoff: null, loyalty_programs: null },
    rhythm: { pace: null, day_start: null, evening_style: null, downtime_minutes: null, transit_tolerance_minutes: null, day_trip_appetite: null },
    experiences: { interests: null, food_interests: null, iconic_local_balance: null, nightlife: null, shopping: null },
    constraints: { dietary: null, accessibility: null },
    optimization: { objective: null, points_priority: null },
  };
}

async function mockProfile(page: Page, initial = profile()) {
  await page.route("**/planning/preferences", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: { profile: initial } });
      return;
    }
    await route.continue();
  });
}

test.describe("CP2 profile preferences", () => {
  test("loads six persisted groups and truthful source metadata", async ({ page }) => {
    await mockProfile(page);
    await page.goto(`${BASE}/profile`);
    await expect(page.getByRole("heading", { name: "Your travel memory" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Flights" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Rewards objective" })).toBeVisible();
    await expect(page.getByText("Saved preference").first()).toBeVisible();
    await expect(page.getByText("Not set").first()).toBeVisible();
  });

  test("commits an edit only after the API succeeds", async ({ page }) => {
    await page.route("**/planning/preferences", async (route) => {
      await route.fulfill({ json: route.request().method() === "GET" ? { profile: profile() } : { profile: profile(null) } });
    });
    await page.route("**/planning/preferences/*", (route) => route.continue());
    await page.goto(`${BASE}/profile`);
    await page.getByRole("button", { name: "Edit group" }).first().click();
    await page.getByLabel("Preferred cabin").selectOption({ label: "Economy" });
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("Not set").first()).toBeVisible();
  });

  test("keeps a failed draft open with an actionable error", async ({ page }) => {
    await page.route("**/planning/preferences", async (route) => {
      if (route.request().method() === "PATCH") await route.fulfill({ status: 503, json: { detail: "unavailable" } });
      else await route.fulfill({ json: { profile: profile() } });
    });
    await page.route("**/planning/preferences/*", (route) => route.continue());
    await page.goto(`${BASE}/profile`);
    await page.getByRole("button", { name: "Edit group" }).first().click();
    await page.getByLabel("Preferred cabin").selectOption({ label: "Economy" });
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("Your draft is still open")).toBeVisible();
    await expect(page.getByRole("button", { name: "Save changes" })).toBeVisible();
  });

  test("uses PATCH for reset and DELETE for remove", async ({ page }) => {
    const methods: string[] = [];
    page.on("request", (request) => { if (request.url().includes("preferences")) methods.push(request.method()); });
    await page.route("**/planning/preferences", async (route) => {
      await route.fulfill({ json: { profile: profile(null) } });
    });
    await page.route("**/planning/preferences/*", async (route) => {
      await route.fulfill({ json: { profile: profile(null) } });
    });
    await page.goto(`${BASE}/profile`);
    await page.getByRole("button", { name: "Reset Flights" }).click();
    await page.getByRole("button", { name: "Reset preferences" }).click();
    await expect.poll(() => methods).toContain("PATCH");
    await page.getByRole("button", { name: "Remove Flights" }).click();
    await page.getByRole("button", { name: "Remove preferences" }).click();
    await expect.poll(() => methods).toEqual(["GET", "PATCH", "DELETE"]);
  });

  test("has no horizontal overflow on mobile", async ({ page }) => {
    await mockProfile(page);
    await page.goto(`${BASE}/profile`);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });

  test("has no axe violations", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "aXe only in chromium");
    await mockProfile(page);
    await page.goto(`${BASE}/profile`);
    const AxeBuilder = (await import("@axe-core/playwright")).default;
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  });
});
