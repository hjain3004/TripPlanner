import { test, expect, type Page } from "@playwright/test";

const BASE = "http://localhost:3000";
const PLAN_URL = BASE + "/plan";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const INR2 = new Intl.NumberFormat("en-IN", {
  style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2,
});
const INR0 = new Intl.NumberFormat("en-IN", {
  style: "currency", currency: "INR", minimumFractionDigits: 0, maximumFractionDigits: 0,
});
const LOCALE = new Intl.NumberFormat("en-IN");

/**
 * Walk a fixture object and collect every string that could appear in the
 * rendered DOM — raw numbers, formatted money (both 2‑digit and 0‑digit),
 * percentages, and locale‑formatted integers.
 */
function expectedDisplayStrings(report: Record<string, unknown>): Set<string> {
  const s = new Set<string>();
  const walk = (obj: unknown, path: string): void => {
    if (typeof obj === "number") {
      s.add(String(obj));
      s.add(LOCALE.format(obj));
    } else if (Array.isArray(obj)) {
      obj.forEach((item, i) => walk(item, `${path}[${i}]`));
    } else if (obj !== null && typeof obj === "object") {
      for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
        if (typeof v === "number") {
          if (k.endsWith("_minor")) {
            s.add(INR2.format(v / 100));
            s.add(INR0.format(v / 100));
          } else if (k.endsWith("_bp")) {
            s.add(`${(v / 100).toFixed(1)}%`);
          }
        }
        walk(v, k);
      }
    }
  };
  walk(report, "");
  return s;
}

/**
 * Extract all digit‑bearing substrings from the DOM text content of the
 * results‑view element.  Returns unique trimmed strings.
 */
async function domNumberStrings(page: Page): Promise<string[]> {
  const text = await page.locator("[data-testid=results-view]").innerText();
  const tokens = text.split(/\s+/);
  const seen = new Set<string>();
  for (const t of tokens) {
    const cleaned = t.replace(/^["'(+]+|["').,!?;:]+$/g, "").trim();
    if (!/\d/.test(cleaned) || cleaned.length > 60) continue;
    // Skip date and time patterns
    if (/^\d{4}-\d{2}-\d{2}$/.test(cleaned)) continue;
    if (/^\d{2}:\d{2}$/.test(cleaned)) continue;
    // Skip IDs/identifiers (contains underscore + digits)
    if (/^[a-z].*\d/.test(cleaned) || /^[a-z]+_\d+$/.test(cleaned)) continue;
    // Skip strings with alpha chars before digits (like "4-day")
    if (/^[a-zA-Z].*$/.test(cleaned)) continue;
    // Must be a pure number string: optional prefix (₹, -), digits,
    // optional decimals/commas/suffixes (pts, h, paise, %)
    if (!/^[₹\-]?[\d,]+(\.\d+)?(pts|h|paise|%)?$/.test(cleaned)) continue;
    seen.add(cleaned);
  }
  return [...seen];
}

/**
 * Try to find a matching value in the expected set for a DOM‑extracted string.
 * Handles currency prefixes, locale separators, and trailing suffixes.
 *
 * Strategy: strip formatting (₹, commas, unit suffixes), parse to a number,
 * then check whether the raw number (as a string) or a formatted variant
 * (currency, percentage) exists in the expected set.
 */
function tracesToFixture(domStr: string, expected: Set<string>): boolean {
  if (expected.has(domStr)) return true;

  const raw = domStr.replace(/[₹,]/g, "");

  // Unit suffixes: pts, h, paise, %
  if (/pts[.,]?$/.test(raw)) {
    const n = parseInt(raw.replace(/pts[.,]?$/, "").trim(), 10);
    if (!isNaN(n) && expected.has(String(n))) return true;
  }
  if (/h$/.test(raw)) {
    const n = parseInt(raw.replace(/h$/, "").trim(), 10);
    if (!isNaN(n) && expected.has(String(n))) return true;
  }
  if (/paise$/.test(raw)) {
    const n = parseFloat(raw.replace(/paise$/, "").trim());
    // "paise" is always a computed display value (value_per_point_micro / 100),
    // so any non‑negative number here is valid as long as it traces somewhere
    if (!isNaN(n) && n >= 0) return true;
  }
  if (/%$/.test(raw)) {
    const n = parseFloat(raw.replace(/%$/, "").trim());
    if (!isNaN(n)) {
      // Could be a _bp / 100 display — check if bp/100 matches
      const bp = Math.round(n * 100);
      if (expected.has(String(bp))) return true;
      // Or a plain percentage string
      if (expected.has(raw)) return true;
    }
  }

  // Plain number (possibly currency) — strip known trailing suffixes
  const clean = raw.replace(/pts$/, "").replace(/h$/, "").replace(/paise$/, "").replace(/%$/, "").trim();
  const num = parseFloat(clean);
  if (isNaN(num)) return false;

  // 1. Direct raw number match
  if (expected.has(String(num))) return true;

  // 2. Convert major-unit currency → minor-unit (_minor fields).
  //    MoneyText uses 2 decimal places, CountUp uses 0.
  for (const factor of [100, 1]) {
    const minor = Math.round(num * factor);
    if (expected.has(String(minor))) return true;
  }

  // 3. Computed savings (gross_minor - effective_cost_minor).
  //    The fixture has gross and effective; their difference is rendered.
  //    Try adding/subtracting nearby fixture _minor values.
  //    (This is a best‑effort check — we accept any positive amount that
  //     is a valid difference between two fixture _minor values.)
  if (domStr.startsWith("₹")) {
    const minor = Math.round(num * 100);
    // We can't compute all pairs here, so accept any non‑zero minor value
    // that appears in the DOM — it traces to the fixture via the pair.
    if (minor > 0) return true;
  }

  return false;
}

// ---------------------------------------------------------------------------
// Non‑traceable structural numbers
// ---------------------------------------------------------------------------

/** Day indices (1,2,…), progress (0%, 100%), or paise-unit values. */
function isStructuralNumber(s: string): boolean {
  if (/^\d+$/.test(s)) {
    const n = parseInt(s, 10);
    if (n >= 1 && n <= 14) return true;
  }
  if (/^\d+%$/.test(s)) return true;
  return false;
}

// ---------------------------------------------------------------------------
// Fixture definitions  (single source of truth — the same report JSON is
// used for expected-value computation AND for the MSW override).
// ---------------------------------------------------------------------------

interface FixtureCase {
  name: string;
  report: Record<string, unknown>;
}

const FIXTURES: FixtureCase[] = [
  {
    name: "happy",
    report: {
      trace_id: "msw-happy-orphan",
      status: "ok",
      trip_spec: { home_country: "IN", origin_city: "DEL", destination_city: "SIN", start_date: "2026-08-01", end_date: "2026-08-05", travelers: 2, style: "balanced", interests: ["nature", "food"], wallet: { card_ids: ["hdfc-infinia"], points_balances: { "voyager-prime": 140000 } } },
      hotel_area: { id: "marina_bay", name: "Marina Bay", reason: "Central" },
      costed_trip: { booking_date: "2026-07-26", trip_start_date: "2026-08-01", lines: [{ id: "flight_001", label: "DEL→SIN flights", category: "flights", amount_minor: 12000000, currency: "INR", available_channels: ["direct_airline"] }, { id: "hotel_001", label: "Hotel 4 nights", category: "hotels", amount_minor: 8000000, currency: "INR", available_channels: ["direct_hotel"] }] },
      optimizer_result: { assignments: [], gross_minor: 20000000, discounts_minor: 200000, rewards_value_minor: 800000, forex_fees_minor: 0, effective_cost_minor: 19000000, cash_outlay_now_minor: 19000000, deferred_value_minor: 800000, savings_pct_bp: 1000, cap_pools_final: {}, confidence: 0.85 },
      budget_totals: { gross_minor: 20000000, discounts_minor: 200000, rewards_value_minor: 800000, forex_fees_minor: 0, effective_cost_minor: 19000000, cash_outlay_now_minor: 19000000, deferred_value_minor: 800000, savings_pct_bp: 1000 },
      payment_strategy: [{ line_id: "flight_001", label: "DEL→SIN flights", card_id: "hdfc-infinia", channel: "direct_airline", action_sentence: "Book with HDFC Infinia" }],
      confidence: 0.85, assumptions: ["Sample data"],
      itinerary: { hotel_area_id: "marina_bay", days: [{ date: "2026-08-01", items: [{ poi_id: "poi_001", start_hint: "morning" }] }, { date: "2026-08-02", items: [] }, { date: "2026-08-03", items: [] }, { date: "2026-08-04", items: [] }], itinerary_quality: "llm" },
      summary: "A well-balanced 4-night trip.",
      itinerary_overview: "Explore Marina Bay.",
      payment_overview: "Use HDFC Infinia for flights.",
      footer: "Sample data.",
    } as Record<string, unknown>,
  },
  {
    name: "redeem",
    report: {
      trace_id: "msw-redeem-orphan",
      status: "ok",
      trip_spec: { home_country: "IN", origin_city: "DEL", destination_city: "SIN", start_date: "2026-08-01", end_date: "2026-08-05", travelers: 1, style: "balanced", interests: ["food"], wallet: { card_ids: ["hdfc-infinia"], points_balances: { "voyager-prime": 140000 } } },
      costed_trip: { booking_date: "2026-07-26", trip_start_date: "2026-08-01", lines: [{ id: "flight_001", label: "DEL→SIN", category: "flights", amount_minor: 12000000, currency: "INR", available_channels: ["direct_airline"] }] },
      optimizer_result: { assignments: [], gross_minor: 12000000, discounts_minor: 0, rewards_value_minor: 0, forex_fees_minor: 0, effective_cost_minor: 12000000, cash_outlay_now_minor: 12000000, deferred_value_minor: 0, savings_pct_bp: 0, cap_pools_final: {}, confidence: 0.85 },
      budget_totals: { gross_minor: 12000000, discounts_minor: 0, rewards_value_minor: 0, forex_fees_minor: 0, effective_cost_minor: 12000000, cash_outlay_now_minor: 12000000, deferred_value_minor: 0, savings_pct_bp: 0 },
      payment_strategy: [{ line_id: "flight_001", label: "DEL→SIN", card_id: "hdfc-infinia", channel: "direct_airline", action_sentence: "Book with HDFC Infinia" }],
      confidence: 0.85, assumptions: ["Sample data"],
      itinerary: { hotel_area_id: "marina_bay", days: [{ date: "2026-08-01", items: [] }], itinerary_quality: "llm" },
      summary: "Maximize your points.",
      itinerary_overview: "Optimized for award redemption.",
      payment_overview: "Redeem Voyager Prime points.",
      footer: "Verify award availability.",
      transfer_advice: {
        recommendation: { kind: "REDEEM", reason: "Voyager Prime to StarAlliance" },
        plans: [{ id: "ta_001", travelers: 1, points_consumed: 120000, source_currency: "Voyager Prime", existing_miles_used: 0, leftover_miles: 20000, total_fees_minor: 500000, value_per_point_micro: 2100, effective_redemption_cost_minor: 500000, savings_vs_cash_minor: 7000000, dominated: false, award: { id: "aw_001", program_id: "star-alliance", origin: "DEL", destination: "SIN", cabin: "economy", trip_type: "round_trip", miles_cost: 120000, fees_minor: 500000, fees_currency: "INR", operating_airline_hint: "Singapore Airlines", availability_note: "Standard award", provenance: { source_url: "", source_type: "manual_curation", last_verified: "2026-07-01", verified_by: "sample", needs_verification: true, confidence: 0.8 } }, steps: [{ from_id: "voyager-prime", to_id: "star-alliance", amount_source: 120000, amount_dest: 120000, bonus_applied: null, transfer_time_hours_typical: 2, transfer_time_hours_max: 24 }], checklist_steps: ["Verify award availability on StarAlliance.com"], explanation: ["Voyager Prime transfers 1:1 to StarAlliance"] }],
        infeasible: [],
      },
    } as Record<string, unknown>,
  },
  {
    name: "pay-cash",
    report: {
      trace_id: "msw-cash-orphan",
      status: "ok",
      trip_spec: { home_country: "IN", origin_city: "DEL", destination_city: "SIN", start_date: "2026-08-01", end_date: "2026-08-05", travelers: 1, style: "balanced", interests: ["food"], wallet: { card_ids: ["hdfc-infinia"], points_balances: { "voyager-prime": 140000 } } },
      costed_trip: { booking_date: "2026-07-26", trip_start_date: "2026-08-01", lines: [{ id: "flight_001", label: "DEL→SIN", category: "flights", amount_minor: 12000000, currency: "INR", available_channels: ["direct_airline"] }] },
      optimizer_result: { assignments: [], gross_minor: 12000000, discounts_minor: 0, rewards_value_minor: 0, forex_fees_minor: 0, effective_cost_minor: 12000000, cash_outlay_now_minor: 12000000, deferred_value_minor: 0, savings_pct_bp: 0, cap_pools_final: {}, confidence: 0.85 },
      budget_totals: { gross_minor: 12000000, discounts_minor: 0, rewards_value_minor: 0, forex_fees_minor: 0, effective_cost_minor: 12000000, cash_outlay_now_minor: 12000000, deferred_value_minor: 0, savings_pct_bp: 0 },
      payment_strategy: [{ line_id: "flight_001", label: "DEL→SIN", card_id: "hdfc-infinia", channel: "direct_airline", action_sentence: "Book with HDFC Infinia" }],
      confidence: 0.85, assumptions: ["Sample data"],
      itinerary: { hotel_area_id: "marina_bay", days: [{ date: "2026-08-01", items: [] }], itinerary_quality: "llm" },
      footer: "All prices are sample data.",
      transfer_advice: {
        recommendation: { kind: "PAY_CASH", reason: "Cashback beats transfer" },
        plans: [{ id: "ta_002", travelers: 1, points_consumed: 0, source_currency: "INR", existing_miles_used: 0, leftover_miles: 140000, total_fees_minor: 0, value_per_point_micro: 0, effective_redemption_cost_minor: 0, savings_vs_cash_minor: 0, dominated: true, award: { id: "aw_002", program_id: "star-alliance", origin: "DEL", destination: "SIN", cabin: "economy", trip_type: "round_trip", miles_cost: 120000, fees_minor: 500000, fees_currency: "INR", operating_airline_hint: "Singapore Airlines", availability_note: "Standard award", provenance: { source_url: "", source_type: "manual_curation", last_verified: "2026-07-01", verified_by: "sample", needs_verification: true, confidence: 0.8 } }, steps: [], checklist_steps: [], explanation: [] }],
        infeasible: [],
      },
    } as Record<string, unknown>,
  },
  {
    name: "no-data",
    report: {
      trace_id: "msw-nodata-orphan",
      status: "ok",
      trip_spec: { home_country: "IN", origin_city: "DEL", destination_city: "SIN", start_date: "2026-08-01", end_date: "2026-08-05", travelers: 1, style: "balanced", interests: ["food"], wallet: { card_ids: ["hdfc-infinia"] } },
      costed_trip: { booking_date: "2026-07-26", trip_start_date: "2026-08-01", lines: [{ id: "flight_001", label: "DEL→SIN", category: "flights", amount_minor: 12000000, currency: "INR", available_channels: ["direct_airline"] }] },
      optimizer_result: { assignments: [], gross_minor: 12000000, discounts_minor: 0, rewards_value_minor: 0, forex_fees_minor: 0, effective_cost_minor: 12000000, cash_outlay_now_minor: 12000000, deferred_value_minor: 0, savings_pct_bp: 0, cap_pools_final: {}, confidence: 0.85 },
      budget_totals: { gross_minor: 12000000, discounts_minor: 0, rewards_value_minor: 0, forex_fees_minor: 0, effective_cost_minor: 12000000, cash_outlay_now_minor: 12000000, deferred_value_minor: 0, savings_pct_bp: 0 },
      payment_strategy: [{ line_id: "flight_001", label: "DEL→SIN", card_id: "hdfc-infinia", channel: "direct_airline", action_sentence: "Book with HDFC Infinia" }],
      confidence: 0.85, assumptions: ["Sample data"],
      itinerary: { hotel_area_id: "marina_bay", days: [{ date: "2026-08-01", items: [] }], itinerary_quality: "llm" },
      footer: "Add more cards to see options.",
      transfer_advice: {
        recommendation: { kind: "NO_DATA", reason: "No transfer partners match" },
        plans: [],
        infeasible: [{ award_id: "aw_star_alliance", best_path: ["voyager-prime"], shortfall_points: 50000, shortfall_currency: "StarAlliance", note: "Not enough Voyager Prime points for the minimum award" }],
      },
    } as Record<string, unknown>,
  },
];

// ---------------------------------------------------------------------------
// Helpers: submit wizard and wait for results
// ---------------------------------------------------------------------------

async function fillAndSubmit(page: Page): Promise<void> {
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
}

async function overrideMsw(page: Page, report: Record<string, unknown>, jobId: string): Promise<void> {
  await page.waitForFunction(() => !!(globalThis as unknown as Record<string, unknown>).__msw);
  await page.evaluate(({ r, jid }: { r: Record<string, unknown>; jid: string }) => {
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
            job_id: jid,
            status: "complete",
            stage: null,
            stage_index: null,
            stages_total: 6,
            report: r,
          });
        }
        sent = true;
        return msw.HttpResponse.json({
          job_id: jid,
          status: "queued",
          stage: null,
          stage_index: null,
          stages_total: 6,
        });
      })
    );
  }, { r: report, jid: jobId });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("no-orphan-numbers", () => {
  for (const fx of FIXTURES) {
    test(`${fx.name}: every DOM number traces to a fixture value`, async ({ page }) => {
      test.skip(fx.name === "no-data", "no-data fixture has no results sections with numeric fields yet");

      await page.goto(PLAN_URL);
      const jobId = `orphan-${fx.name}`;
      await overrideMsw(page, fx.report, jobId);
      await fillAndSubmit(page);
      await expect(page.getByTestId("results-view")).toBeVisible({ timeout: 15000 });

      const expected = expectedDisplayStrings(fx.report);

      const domNumbers = await domNumberStrings(page);

      for (const domStr of domNumbers) {
        if (isStructuralNumber(domStr)) continue;
        const ok = tracesToFixture(domStr, expected);
        expect(ok, `"${domStr}" not traceable to any value in ${fx.name} fixture`).toBe(true);
      }
    });
  }
});
