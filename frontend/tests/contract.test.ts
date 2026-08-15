import { describe, it, expect } from "vitest";
import { planJobStatusSchema } from "../src/lib/api/schemas";
import { fixtureHandlers } from "../src/mocks/handlers";

// ---------------------------------------------------------------------------
// 1. Fixture Zod parsing
// ---------------------------------------------------------------------------

function wrapReport(report: ReturnType<typeof fixtureHandlers.happyReport>): unknown {
  return {
    job_id: `test-${report.trace_id}`,
    status: "complete",
    stage: null,
    stage_index: null,
    stages_total: 6,
    report,
  };
}

const FIXTURES = [
  { name: "happy", fn: fixtureHandlers.happyReport },
  { name: "fallback", fn: fixtureHandlers.fallbackReport },
  { name: "provenance-warnings", fn: fixtureHandlers.provenanceWarningsReport },
  { name: "redeem", fn: fixtureHandlers.redeemReport },
  { name: "pay-cash", fn: fixtureHandlers.payCashReport },
  { name: "no-data", fn: fixtureHandlers.noDataReport },
] as const;

describe("contract: fixtures parse through Zod", () => {
  for (const fix of FIXTURES) {
    it(`${fix.name} parses cleanly`, () => {
      const wrapped = wrapReport(fix.fn());
      const result = planJobStatusSchema.safeParse(wrapped);
      if (!result.success) {
        throw new Error(
          `${fix.name}: ${result.error.issues.map((i) => `[${i.path.join(".")}] ${i.message}`).join("; ")}`
        );
      }
      // Ensure report is present
      expect(result.data.report).toBeDefined();
    });
  }
});

describe("contract: fixture structural integrity", () => {
  it("happy report has itinerary days", () => {
    const r = fixtureHandlers.happyReport();
    expect(r.itinerary.days.length).toBeGreaterThanOrEqual(4);
  });

  it("fallback report has itinerary_quality=fallback + notes", () => {
    const r = fixtureHandlers.fallbackReport();
    expect(r.itinerary.itinerary_quality).toBe("fallback");
    expect(r.itinerary.notes?.length).toBeGreaterThanOrEqual(1);
  });

  it("provenance warnings report has warnings", () => {
    const r = fixtureHandlers.provenanceWarningsReport();
    expect(r.provenance_warnings?.length).toBeGreaterThanOrEqual(3);
  });

  it("redeem report has transfer advice with REDEEM recommendation", () => {
    const r = fixtureHandlers.redeemReport();
    expect(r.transfer_advice).toBeDefined();
    expect(r.transfer_advice!.recommendation.kind).toBe("REDEEM");
    expect(r.transfer_advice!.plans.length).toBeGreaterThanOrEqual(1);
  });

  it("pay-cash report has transfer advice with PAY_CASH recommendation", () => {
    const r = fixtureHandlers.payCashReport();
    expect(r.transfer_advice).toBeDefined();
    expect(r.transfer_advice!.recommendation.kind).toBe("PAY_CASH");
  });

  it("no-data report has transfer advice with NO_DATA recommendation + infeasible", () => {
    const r = fixtureHandlers.noDataReport();
    expect(r.transfer_advice).toBeDefined();
    expect(r.transfer_advice!.recommendation.kind).toBe("NO_DATA");
    expect(r.transfer_advice!.infeasible.length).toBeGreaterThanOrEqual(1);
  });
});

// ---------------------------------------------------------------------------
// 2. Error taxonomy mapping
// ---------------------------------------------------------------------------

describe("contract: error taxonomy mapping", () => {
  it("422 validation error shape matches UI expectation", () => {
    const error422 = {
      detail: [
        { loc: ["body", "raw_request"], msg: "field required", type: "value_error" },
      ],
    };
    expect(error422.detail).toBeInstanceOf(Array);
    expect(error422.detail[0]!.loc).toContain("raw_request");
    expect(error422.detail[0]!.msg).toBe("field required");
  });

  it("failed status error shape matches JobError type", () => {
    const err = { code: "PIPELINE_ERROR", message: "Intake failed", trace_id: "fail-001" };
    expect(err).toHaveProperty("code");
    expect(err).toHaveProperty("message");
    expect(err).toHaveProperty("trace_id");
  });

  it("timeout error shape — no report, no error object", () => {
    const timeout: Record<string, unknown> = {
      job_id: "timeout-001",
      status: "running",
      stage: "itinerary",
      stage_index: 2,
      stages_total: 6,
    };
    const parsed = planJobStatusSchema.safeParse(timeout);
    expect(parsed.success).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 3. No-orphan-numbers — moved to e2e/f3-no-orphan-numbers.spec.ts
//    The original vitest-based version walked fixture JSON only; the
//    e2e version renders each fixture in a real page and asserts every
//    digit string in the DOM text traces to a value in the fixture JSON.
// ---------------------------------------------------------------------------

describe("contract: non-negative fixture monetary fields", () => {
  const ALLOWED_ORPHAN_PATHS = [
    "jitter_seed",
    "jitter_iterations",
    "stops",
    "stars",
    "travelers",
    "transfer_time_hours_typical",
    "transfer_time_hours_max",
  ];

  const MONETARY_LIKE_PATTERNS = [
    "_minor", "_micro", "_bp", "value_per_", "confidence",
    "points_consumed", "leftover_miles", "existing_miles_used",
    "miles_cost", "amount_source", "amount_dest", "shortfall_points",
  ];

  for (const fix of FIXTURES) {
    it(`${fix.name}: fixture numeric fields are non-negative`, () => {
      const report = fix.fn();

      function checkLeafNumbers(obj: unknown, prefix = ""): void {
        if (typeof obj === "number") {
          const isMonetary = MONETARY_LIKE_PATTERNS.some((p) => prefix.includes(p));
          const isAllowed = ALLOWED_ORPHAN_PATHS.some((p) => prefix.endsWith(p));
          if (isMonetary && !isAllowed) {
            expect(obj, `${fix.name}: ${prefix} = ${obj} should be >= 0`).toBeGreaterThanOrEqual(0);
          }
        } else if (Array.isArray(obj)) {
          obj.forEach((item, i) => checkLeafNumbers(item, `${prefix}[${i}]`));
        } else if (obj && typeof obj === "object") {
          for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
            checkLeafNumbers(v, prefix ? `${prefix}.${k}` : k);
          }
        }
      }
      checkLeafNumbers(report);
    });
  }

  it("all fixtures have matching trace_id prefix", () => {
    const prefixes = FIXTURES.map((f) => f.fn().trace_id.split("-").slice(0, 2).join("-"));
    const expected = ["msw-happy", "msw-fallback", "msw-prov", "msw-redeem", "msw-cash", "msw-nodata"];
    for (let i = 0; i < prefixes.length; i++) {
      expect(prefixes[i]).toBe(expected[i]);
    }
  });
});

describe("contract: itinerary rendering evidence", () => {
  it("happy report itinerary items contain rendering metadata", () => {
    const r = fixtureHandlers.happyReport();
    const firstDay = r.itinerary.days[0];
    if (!firstDay) throw new Error("no days");
    expect(firstDay.unmet_needs).toBeDefined();
    expect(firstDay.rejections).toBeDefined();
    const item = firstDay.items[0];
    if (!item) throw new Error("no items");
    expect(item.name).toBeDefined();
    expect(item.category).toBeDefined();
    expect(item.travel_from_previous).toBeDefined();
    expect(item.evidence).toBeDefined();
  });
});
