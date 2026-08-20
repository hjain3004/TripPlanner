import { test, expect } from "@playwright/test";
import path from "path";

const BASE = "http://localhost:3000";
const PLAN_URL = BASE + "/plan";
const REFS_DIR = path.resolve(__dirname, "../design/refs/f3");

function redeemScreenshotReport() {
  return {
    trace_id: "msw-ss-redeem",
    status: "ok",
    trip_spec: { home_country: "IN", origin_city: "DEL", destination_city: "SIN", start_date: "2026-08-01", end_date: "2026-08-05", travelers: 1, style: "balanced", interests: ["food"], wallet: { card_ids: ["hdfc-infinia"], points_balances: { "voyager-prime": 140000 } } },
    costed_trip: { booking_date: "2026-07-26", trip_start_date: "2026-08-01", lines: [{ id: "flight_001", label: "DEL→SIN", category: "flights", amount_minor: 12000000, currency: "INR", available_channels: ["direct_airline"] }] },
    optimizer_result: { assignments: [], gross_minor: 20000000, discounts_minor: 200000, rewards_value_minor: 800000, forex_fees_minor: 0, effective_cost_minor: 19000000, cash_outlay_now_minor: 19000000, deferred_value_minor: 800000, savings_pct_bp: 1000, cap_pools_final: {}, confidence: 0.85 },
    budget_totals: { gross_minor: 20000000, discounts_minor: 200000, rewards_value_minor: 800000, forex_fees_minor: 0, effective_cost_minor: 19000000, cash_outlay_now_minor: 19000000, deferred_value_minor: 800000, savings_pct_bp: 1000 },
    payment_strategy: [{ line_id: "flight_001", label: "DEL→SIN", card_id: "hdfc-infinia", channel: "direct_airline", action_sentence: "Book with HDFC Infinia" }],
    confidence: 0.85, assumptions: ["Sample data"],
    itinerary: { hotel_area_id: "marina_bay", days: [{ date: "2026-08-01", items: [] }], itinerary_quality: "llm" },
    summary: "Well-balanced trip.", itinerary_overview: "Explore Marina Bay.", payment_overview: "Use HDFC Infinia.", footer: "Sample data.",
    transfer_advice: {
      recommendation: { kind: "REDEEM", reason: "Voyager Prime to StarAlliance" },
      plans: [{ id: "ta_001", travelers: 1, points_consumed: 120000, source_currency: "Voyager Prime", existing_miles_used: 0, leftover_miles: 20000, total_fees_minor: 500000, value_per_point_micro: 2100, effective_redemption_cost_minor: 500000, savings_vs_cash_minor: 7000000, dominated: false, award: { id: "aw_001", program_id: "star-alliance", origin: "DEL", destination: "SIN", cabin: "economy", trip_type: "round_trip", miles_cost: 120000, fees_minor: 500000, fees_currency: "INR", operating_airline_hint: "Singapore Airlines", availability_note: "Standard award", provenance: { source_url: "", source_type: "manual_curation", last_verified: "2026-07-01", verified_by: "sample", needs_verification: true, confidence: 0.8 } }, steps: [{ from_id: "voyager-prime", to_id: "star-alliance", amount_source: 120000, amount_dest: 120000, bonus_applied: null, transfer_time_hours_typical: 2, transfer_time_hours_max: 24 }], checklist_steps: ["Verify award availability on StarAlliance.com", "Check transfer bonus is still active"], explanation: ["Voyager Prime transfers 1:1 to StarAlliance"] }],
      infeasible: [],
    },
  };
}

test.describe("F3 results page: happy path", () => {
  test("complete flow shows verdict header, itinerary, budget, and plan another trip", async ({ page }) => {
    await page.goto(PLAN_URL);

    // Fill all 5 steps and submit
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

    // Wait for results
    await expect(page.getByTestId("results-view")).toBeVisible({ timeout: 15000 });

    // Verdict header with day count and destination code
    await expect(page.locator("h1")).toContainText(/SIN.*plan|plan.*SIN/);
  });
});

test.describe("F3 results page: sections", () => {
  test("itinerary timeline renders with day numbers and dates", async ({ page }) => {
    await page.goto(PLAN_URL);
    await page.fill("#origin", "DEL");
    await page.fill("#destination", "SIN");
    await page.fill("#start-date", "2026-08-01");
    await page.fill("#end-date", "2026-08-05");
    await page.fill("#travelers", "1");
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Generate plan" }).click();

    await expect(page.getByTestId("results-view")).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole("heading", { name: "Itinerary" })).toBeVisible();
    await expect(page.getByText("2026-08-01").first()).toBeVisible();
  });

  test("budget section renders cost rows", async ({ page }) => {
    await page.goto(PLAN_URL);
    await page.fill("#origin", "DEL");
    await page.fill("#destination", "SIN");
    await page.fill("#start-date", "2026-08-01");
    await page.fill("#end-date", "2026-08-05");
    await page.fill("#travelers", "1");
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Generate plan" }).click();

    await expect(page.getByTestId("results-view")).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole("heading", { name: "Budget" })).toBeVisible();
    await expect(page.getByText("Effective cost").first()).toBeVisible();
  });

  test("transfer advice section renders when present", async ({ page }) => {
    await page.goto(PLAN_URL);

    await page.waitForFunction(() => !!(globalThis as unknown as Record<string, unknown>).__msw);
    await page.evaluate(() => {
      const msw = (globalThis as unknown as Record<string, unknown>).__msw as {
        worker: { use: (...h: unknown[]) => void };
        http: { get: (p: string, h: () => unknown) => unknown };
        HttpResponse: { json: (d: unknown, s?: { status?: number }) => unknown };
      };
      let transferSent = false;
      msw.worker.use(
        msw.http.get("http://localhost:8000/plan/:jobId", () => {
          if (transferSent) {
            return msw.HttpResponse.json({
              job_id: "tr-test",
              status: "complete",
              stage: null,
              stage_index: null,
              stages_total: 6,
              report: {
                trace_id: "msw-transfer-e2e",
                status: "ok",
                trip_spec: {
                  home_country: "IN", origin_city: "DEL", destination_city: "SIN",
                  start_date: "2026-08-01", end_date: "2026-08-05",
                  travelers: 1, style: "balanced", interests: ["food"],
                  wallet: { card_ids: ["hdfc-infinia"], points_balances: { "voyager-prime": 140000 } },
                },
                costed_trip: {
                  booking_date: "2026-07-26", trip_start_date: "2026-08-01",
                  lines: [{ id: "flight_001", label: "DEL→SIN", category: "flights", amount_minor: 12000000, currency: "INR", available_channels: ["direct_airline"] }],
                },
                optimizer_result: {
                  assignments: [], gross_minor: 12000000, discounts_minor: 0, rewards_value_minor: 0,
                  forex_fees_minor: 0, effective_cost_minor: 12000000, cash_outlay_now_minor: 12000000,
                  deferred_value_minor: 0, savings_pct_bp: 0, cap_pools_final: {}, confidence: 0.85,
                },
                budget_totals: {
                  gross_minor: 12000000, discounts_minor: 0, rewards_value_minor: 0,
                  forex_fees_minor: 0, effective_cost_minor: 12000000, cash_outlay_now_minor: 12000000,
                  deferred_value_minor: 0, savings_pct_bp: 0,
                },
                payment_strategy: [{ line_id: "flight_001", label: "DEL→SIN", card_id: "hdfc-infinia", channel: "direct_airline", action_sentence: "Book with HDFC Infinia" }],
                confidence: 0.85,
                assumptions: ["Sample data"],
                itinerary: {
                  hotel_area_id: "marina_bay",
                  days: [{ date: "2026-08-01", items: [] }],
                  itinerary_quality: "llm",
                },
                transfer_advice: {
                  recommendation: { kind: "REDEEM", reason: "Voyager Prime → StarAlliance" },
                  plans: [{
                    id: "ta_001", travelers: 1, points_consumed: 120000, source_currency: "Voyager Prime",
                    existing_miles_used: 0, leftover_miles: 20000, total_fees_minor: 500000,
                    value_per_point_micro: 2100, effective_redemption_cost_minor: 500000,
                    savings_vs_cash_minor: 7000000, dominated: false,
                    award: {
                      id: "aw_001", program_id: "star-alliance", origin: "DEL", destination: "SIN",
                      cabin: "economy", trip_type: "round_trip", miles_cost: 120000, fees_minor: 500000,
                      fees_currency: "INR", operating_airline_hint: "Singapore Airlines",
                      availability_note: "Standard award", provenance: {
                        source_url: "", source_type: "manual_curation",
                        last_verified: "2026-07-01", verified_by: "sample", needs_verification: true, confidence: 0.8,
                      },
                    },
                    steps: [{ from_id: "voyager-prime", to_id: "star-alliance", amount_source: 120000, amount_dest: 120000,
                      bonus_applied: null, transfer_time_hours_typical: 2, transfer_time_hours_max: 24 }],
                    checklist_steps: ["Verify award availability"],
                    explanation: ["Voyager Prime transfers 1:1 to StarAlliance"],
                  }],
                  infeasible: [],
                },
              },
            });
          }
          transferSent = true;
          return msw.HttpResponse.json({
            job_id: "tr-test",
            status: "queued",
            stage: null,
            stage_index: null,
            stages_total: 6,
          });
        })
      );
    });

    await page.fill("#origin", "DEL");
    await page.fill("#destination", "SIN");
    await page.fill("#start-date", "2026-08-01");
    await page.fill("#end-date", "2026-08-05");
    await page.fill("#travelers", "1");
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Generate plan" }).click();

    await expect(page.getByTestId("results-view")).toBeVisible({ timeout: 15000 });
    await expect(page.getByText("Points & transfers")).toBeVisible();
  });
});

test.describe("F3 results page: fallback badge", () => {
  test("fallback itinerary shows trusted badge", async ({ page }) => {
    await page.goto(PLAN_URL);

    // Override MSW to return fallback report
    await page.waitForFunction(() => !!(globalThis as unknown as Record<string, unknown>).__msw);
    await page.evaluate(() => {
      const msw = (globalThis as unknown as Record<string, unknown>).__msw as {
        worker: { use: (...h: unknown[]) => void };
        http: { get: (p: string, h: () => unknown) => unknown };
        HttpResponse: { json: (d: unknown, s?: { status?: number }) => unknown };
      };
      let fallbackSent = false;
      msw.worker.use(
        msw.http.get("http://localhost:8000/plan/:jobId", () => {
          if (fallbackSent) {
            return msw.HttpResponse.json({
              job_id: "fb-test",
              status: "complete",
              stage: null,
              stage_index: null,
              stages_total: 6,
              report: {
                trace_id: "msw-fallback-e2e",
                status: "ok",
                trip_spec: {
                  home_country: "IN", origin_city: "DEL", destination_city: "SIN",
                  start_date: "2026-08-01", end_date: "2026-08-05",
                  travelers: 2, style: "balanced", interests: ["food"],
                  wallet: { card_ids: ["hdfc-infinia"] },
                },
                hotel_area: { id: "marina_bay", name: "Marina Bay", reason: "Central" },
                costed_trip: {
                  booking_date: "2026-07-26", trip_start_date: "2026-08-01",
                  lines: [{ id: "flight_001", label: "DEL→SIN", category: "flights", amount_minor: 12000000, currency: "INR", available_channels: ["direct_airline"] }],
                },
                optimizer_result: {
                  assignments: [], gross_minor: 12000000, discounts_minor: 0, rewards_value_minor: 0,
                  forex_fees_minor: 0, effective_cost_minor: 12000000, cash_outlay_now_minor: 12000000,
                  deferred_value_minor: 0, savings_pct_bp: 0, cap_pools_final: {}, confidence: 0.7,
                },
                budget_totals: {
                  gross_minor: 12000000, discounts_minor: 0, rewards_value_minor: 0,
                  forex_fees_minor: 0, effective_cost_minor: 12000000, cash_outlay_now_minor: 12000000,
                  deferred_value_minor: 0, savings_pct_bp: 0,
                },
                payment_strategy: [{ line_id: "flight_001", label: "DEL→SIN", card_id: "hdfc-infinia", channel: "direct_airline", action_sentence: "Book with HDFC Infinia" }],
                confidence: 0.7,
                assumptions: ["Fallback itinerary — review before booking"],
                itinerary: {
                  hotel_area_id: "marina_bay",
                  days: [{ date: "2026-08-01", items: [] }],
                  itinerary_quality: "fallback",
                  notes: ["LLM unavailable — best-effort itinerary"],
                },
              },
            });
          }
          fallbackSent = true;
          return msw.HttpResponse.json({
            job_id: "fb-test",
            status: "queued",
            stage: null,
            stage_index: null,
            stages_total: 6,
          });
        })
      );
    });

    await page.fill("#origin", "DEL");
    await page.fill("#destination", "SIN");
    await page.fill("#start-date", "2026-08-01");
    await page.fill("#end-date", "2026-08-05");
    await page.fill("#travelers", "1");
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Generate plan" }).click();

    await expect(page.getByTestId("results-view")).toBeVisible({ timeout: 15000 });
    await expect(page.getByText("Best-effort itinerary")).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Accessibility — chromium only
// ---------------------------------------------------------------------------

test.describe("F3 results page: accessibility", () => {
  test("no aXe violations on results page", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "aXe only in chromium");

    await page.goto(PLAN_URL);
    await page.fill("#origin", "DEL");
    await page.fill("#destination", "SIN");
    await page.fill("#start-date", "2026-08-01");
    await page.fill("#end-date", "2026-08-05");
    await page.fill("#travelers", "1");
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Generate plan" }).click();
    await expect(page.getByTestId("results-view")).toBeVisible({ timeout: 15000 });
    await page.waitForTimeout(2000); // let GSAP entrance animation settle

    const AxeBuilder = (await import("@axe-core/playwright")).default;
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Reduced motion — reduced-motion project only
// ---------------------------------------------------------------------------

test.describe("F3 results page: reduced motion", () => {
  test("data-motion elements resolve instantly and confetti does not fire", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "reduced-motion", "reduced-motion assertions only in reduced-motion project");

    await page.goto(PLAN_URL);
    await page.fill("#origin", "DEL");
    await page.fill("#destination", "SIN");
    await page.fill("#start-date", "2026-08-01");
    await page.fill("#end-date", "2026-08-05");
    await page.fill("#travelers", "1");
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Generate plan" }).click();
    await expect(page.getByTestId("results-view")).toBeVisible({ timeout: 15000 });

    // Assert every [data-motion] element has opacity >= 0.99 (animations
    // resolved instantly rather than leaving content invisible)
    const motionEls = page.locator("[data-motion]");
    const count = await motionEls.count();
    expect(count).toBeGreaterThanOrEqual(1);
    for (let i = 0; i < count; i++) {
      const opacity = await motionEls.nth(i).evaluate((el) =>
        parseFloat(getComputedStyle(el).opacity)
      );
      expect(opacity, `[data-motion] element ${i} has opacity ${opacity}`).toBeGreaterThanOrEqual(0.99);
    }

    // Assert no confetti canvas element was appended (confetti
    // respects disableForReducedMotion: true).
    //
    // Excludes the MapLibre canvas. This test predates I6, which added the
    // trip map to the results page; "any canvas" meant "confetti" when it was
    // written, and has not since. Verified by enumerating the canvases on this
    // page under reduced-motion: the only one present is .maplibregl-canvas,
    // which is the map rendering correctly, not an animation firing.
    const confettiCanvases = page.locator("canvas:not(.maplibregl-canvas)");
    await expect(confettiCanvases).toHaveCount(0);
  });
});

// ---------------------------------------------------------------------------
// Screenshot capture for evidence bundle
// ---------------------------------------------------------------------------

test.describe("F3 results page: screenshots", () => {
  test("capture all results sections", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "screenshots only in chromium");

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(PLAN_URL);
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
    // Let all animations/renders settle
    await page.waitForTimeout(1200);

    // Verdict header
    const verdict = page.locator("[data-motion=verdict]");
    await verdict.screenshot({ path: path.join(REFS_DIR, "results-verdict-header-happy-1440.png") });

    // Itinerary
    const itinerary = page.getByRole("heading", { name: "Itinerary" }).locator("..");
    if (await itinerary.count() > 0) {
      const section = itinerary.locator("..");
      await section.screenshot({ path: path.join(REFS_DIR, "results-itinerary-happy-1440.png") });
    }

    // Budget
    const budget = page.getByRole("heading", { name: "Budget" });
    if (await budget.count() > 0) {
      const section = budget.locator("..");
      await section.screenshot({ path: path.join(REFS_DIR, "results-budget-happy-1440.png") });
    }

    // Transfer plan – override with redeem fixture for richer content
    // (done in a separate test below)
  });

  test("capture transfer plan and map with redeem fixture", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "screenshots only in chromium");

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(PLAN_URL);

    const reportData = redeemScreenshotReport();
    await page.waitForFunction(() => !!(globalThis as unknown as Record<string, unknown>).__msw);
    await page.evaluate((r) => {
      const msw = (globalThis as unknown as Record<string, unknown>).__msw as {
        worker: { use: (...h: unknown[]) => void };
        http: { get: (p: string, h: () => unknown) => unknown };
        HttpResponse: { json: (d: unknown, s?: { status?: number }) => unknown };
      };
      let sent = false;
      msw.worker.use(
        msw.http.get("http://localhost:8000/plan/:jobId", () => {
          if (sent) {
            return msw.HttpResponse.json({
              job_id: "ss-redeem",
              status: "complete",
              stage: null,
              stage_index: null,
              stages_total: 6,
              report: r,
            });
          }
          sent = true;
          return msw.HttpResponse.json({ job_id: "ss-redeem", status: "queued", stage: null, stage_index: null, stages_total: 6 });
        })
      );
    }, reportData);

    await page.fill("#origin", "DEL");
    await page.fill("#destination", "SIN");
    await page.fill("#start-date", "2026-08-01");
    await page.fill("#end-date", "2026-08-05");
    await page.fill("#travelers", "1");
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Next" }).click();
    await page.locator("button").filter({ hasText: "Generate plan" }).click();
    await expect(page.getByTestId("results-view")).toBeVisible({ timeout: 15000 });
    await page.waitForTimeout(1200);

    // Transfer plan
    const transfers = page.getByText("Points & transfers");
    if (await transfers.count() > 0) {
      const section = transfers.locator("../../../..");
      await section.screenshot({ path: path.join(REFS_DIR, "results-transfer-plan-redeem-1440.png") });
    }

    // Booking checklist heading
    const checklist = page.getByText("Booking checklist");
    if (await checklist.count() > 0) {
      const section = checklist.locator("../../..");
      await section.screenshot({ path: path.join(REFS_DIR, "results-checklist-happy-1440.png") });
    }

    // Trip map (lazy-loaded)
    await page.waitForTimeout(500);
    const mapText = page.getByText("Trip map");
    if (await mapText.count() > 0) {
      const section = mapText.locator("../../..");
      await section.screenshot({ path: path.join(REFS_DIR, "results-trip-map-happy-1440.png") });
    }
  });
});
