import { http, HttpResponse } from "msw";
import type { PlanJobStatus, FinalReport } from "@/lib/api/types.gen";

const SPEED_MULTIPLIER = 1;

const jobStore: Record<string, { status: PlanJobStatus; timer: ReturnType<typeof setInterval> | null }> = {};

const STAGES: PlanJobStatus["stage"][] = [
  "intake",
  "itinerary",
  "costing",
  "optimizing",
  "critic",
  "explaining",
];

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function baseReport(): Omit<FinalReport, "summary" | "itinerary_overview" | "payment_overview" | "footer" | "status" | "itinerary" | "transfer_advice" | "provenance_warnings" | "booking_checklist" | "caveats"> {
  return {
    trace_id: "msw-fixture-001",
    trip_spec: {
      home_country: "IN",
      origin_city: "DEL",
      destination_city: "SIN",
      start_date: "2026-08-01",
      end_date: "2026-08-05",
      travelers: 2,
      budget_minor: 25000000,
      budget_currency: "INR",
      style: "balanced",
      interests: ["nature", "food"],
      wallet: { card_ids: ["hdfc-infinia"], points_balances: { "voyager-prime": 140000 } },
    },
    hotel_area: { id: "marina_bay", name: "Marina Bay", reason: "Central location with good public transport" },
    costed_trip: {
      booking_date: today(),
      trip_start_date: "2026-08-01",
      lines: [
        { id: "flight_001", label: "DEL→SIN flights (2 pax)", category: "flights", amount_minor: 12000000, currency: "INR", available_channels: ["direct_airline", "ota_generic"] },
        { id: "hotel_001", label: "Marina Bay hotel 4 nights", category: "hotels", amount_minor: 8000000, currency: "INR", available_channels: ["direct_hotel", "ota_generic"] },
      ],
    },
    optimizer_result: {
      assignments: [], gross_minor: 20000000, discounts_minor: 200000, rewards_value_minor: 800000,
      forex_fees_minor: 0, effective_cost_minor: 19000000, cash_outlay_now_minor: 19000000,
      deferred_value_minor: 800000, savings_pct_bp: 1000, cap_pools_final: {}, confidence: 0.85,
    },
    budget_totals: {
      gross_minor: 20000000, discounts_minor: 200000, rewards_value_minor: 800000,
      forex_fees_minor: 0, effective_cost_minor: 19000000, cash_outlay_now_minor: 19000000,
      deferred_value_minor: 800000, savings_pct_bp: 1000,
    },
    payment_strategy: [
      { line_id: "flight_001", label: "DEL→SIN flights (2 pax)", card_id: "hdfc-infinia", channel: "direct_airline", action_sentence: "Book with HDFC Infinia via direct airline for 5% cashback" },
    ],
    confidence: 0.85,
    assumptions: ["Sample data used — verify before booking"],
    flights_pick: null,
    hotel_pick: null,
  };
}

function createHappyReport(): FinalReport {
  return {
    ...baseReport(),
    trace_id: "msw-happy-001",
    status: "ok",
    itinerary: {
      hotel_area_id: "marina_bay",
      days: [
        { date: "2026-08-01", unmet_needs: ["travel budget exceeded"], rejections: [], items: [{ poi_id: "poi_001", start_hint: "morning", name: "Sample POI", category: "other", travel_from_previous: { duration_min: 15, status: "estimated", source: "mock" }, evidence: { status: "live", last_verified: "2026-07-01", licence_id: null, attribution: null, needs_verification: true, poi_id: "poi_001" } }] },
        { date: "2026-08-02", unmet_needs: [], rejections: [], items: [] },
        { date: "2026-08-03", unmet_needs: [], rejections: [], items: [] },
        { date: "2026-08-04", unmet_needs: [], rejections: [], items: [] },
      ],
      itinerary_quality: "llm",
    },
    summary: "A well-balanced 4-night trip to Singapore with solid savings.",
    itinerary_overview: "Explore Marina Bay with a nature-focused itinerary.",
    payment_overview: "Use HDFC Infinia for flights to maximize savings.",
    footer: "All prices are sample data. Verify before booking.",
  };
}

function createFallbackReport(): FinalReport {
  return {
    ...baseReport(),
    trace_id: "msw-fallback-001",
    status: "ok",
    itinerary: {
      hotel_area_id: "marina_bay",
      days: [
        { date: "2026-08-01", unmet_needs: [], rejections: [], items: [{ poi_id: "poi_001", start_hint: "morning" }] },
        { date: "2026-08-02", unmet_needs: [], rejections: [], items: [] },
        { date: "2026-08-03", unmet_needs: [], rejections: [], items: [] },
        { date: "2026-08-04", unmet_needs: [], rejections: [], items: [] },
      ],
      itinerary_quality: "fallback",
      notes: ["Best-effort itinerary — LLM was unavailable"],
    },
    summary: "Best-effort itinerary for your Singapore trip.",
    itinerary_overview: "Fallback itinerary — review and adjust.",
    payment_overview: "Use HDFC Infinia for flights to maximize savings.",
    footer: "All prices are sample data. Verify before booking.",
    caveats: ["Itinerary generated via fallback — review before booking"],
  };
}

function createProvenanceWarningsReport(): FinalReport {
  return {
    ...baseReport(),
    trace_id: "msw-prov-001",
    status: "ok",
    itinerary: {
      hotel_area_id: "marina_bay",
      days: [{ date: "2026-08-01", unmet_needs: [], rejections: [], items: [] }, { date: "2026-08-02", unmet_needs: [], rejections: [], items: [] }, { date: "2026-08-03", unmet_needs: [], rejections: [], items: [] }, { date: "2026-08-04", unmet_needs: [], rejections: [], items: [] }],
      itinerary_quality: "llm",
    },
    summary: "Trip plan with data quality warnings.",
    itinerary_overview: "Some data sources need verification.",
    payment_overview: "Optimized for HDFC Infinia.",
    footer: "All prices are sample data. Verify before booking.",
    provenance_warnings: [
      "Flight price may be outdated — last verified 30 days ago",
      "Hotel availability not confirmed — contact hotel directly",
      "Transfer partner rates may have changed since last check",
    ],
  };
}

function createRedeemReport(): FinalReport {
  return {
    ...baseReport(),
    trace_id: "msw-redeem-001",
    status: "ok",
    itinerary: {
      hotel_area_id: "marina_bay",
      days: [{ date: "2026-08-01", unmet_needs: [], rejections: [], items: [] }, { date: "2026-08-02", unmet_needs: [], rejections: [], items: [] }, { date: "2026-08-03", unmet_needs: [], rejections: [], items: [] }, { date: "2026-08-04", unmet_needs: [], rejections: [], items: [] }],
      itinerary_quality: "llm",
    },
    summary: "Maximize your points by redeeming through Voyager Prime.",
    itinerary_overview: "Optimized for award redemption.",
    payment_overview: "Redeem Voyager Prime points for flights — save ₹12,000.",
    footer: "Verify award availability before transferring points.",
    transfer_advice: {
      recommendation: { kind: "REDEEM", reason: "Voyager Prime → StarAlliance transfer gives 2.1 CPP" },
      plans: [
        {
          id: "ta_001", travelers: 2, points_consumed: 120000, source_currency: "Voyager Prime",
          existing_miles_used: 0, leftover_miles: 20000, total_fees_minor: 500000,
          value_per_point_micro: 2100, effective_redemption_cost_minor: 500000,
          savings_vs_cash_minor: 12000000, dominated: false,
          award: {
            id: "aw_001", program_id: "star-alliance", origin: "DEL", destination: "SIN",
            cabin: "economy", trip_type: "round_trip", miles_cost: 120000, fees_minor: 500000,
            fees_currency: "INR", operating_airline_hint: "Singapore Airlines",
            availability_note: "Standard award — limited seats", provenance: {
              source_url: "https://example.com/award", source_type: "manual_curation",
              last_verified: "2026-07-01", verified_by: "sample", needs_verification: true, confidence: 0.8,
            },
          },
          steps: [
            { from_id: "voyager-prime", to_id: "star-alliance", amount_source: 120000, amount_dest: 120000,
              bonus_applied: null, transfer_time_hours_typical: 2, transfer_time_hours_max: 24 },
          ],
          checklist_steps: ["Verify award availability on StarAlliance.com", "Confirm transfer bonus is still active"],
          explanation: ["Voyager Prime transfers 1:1 to StarAlliance"],
        },
      ],
      infeasible: [],
    },
  };
}

function createPayCashReport(): FinalReport {
  return {
    ...baseReport(),
    trace_id: "msw-cash-001",
    status: "ok",
    itinerary: {
      hotel_area_id: "marina_bay",
      days: [{ date: "2026-08-01", unmet_needs: [], rejections: [], items: [] }, { date: "2026-08-02", unmet_needs: [], rejections: [], items: [] }, { date: "2026-08-03", unmet_needs: [], rejections: [], items: [] }, { date: "2026-08-04", unmet_needs: [], rejections: [], items: [] }],
      itinerary_quality: "llm",
    },
    summary: "Paying cash gives you the best deal for this trip.",
    itinerary_overview: "Cash booking with HDFC Infinia for maximum rewards.",
    payment_overview: "Pay cash via HDFC Infinia — earn 5% cashback on flights.",
    footer: "All prices are sample data.",
    transfer_advice: {
      recommendation: { kind: "PAY_CASH", reason: "Cashback on HDFC Infinia beats any transfer value for this route" },
      plans: [{ id: "ta_002", travelers: 2, points_consumed: 0, source_currency: "INR", existing_miles_used: 0, leftover_miles: 140000, total_fees_minor: 0, value_per_point_micro: 0, effective_redemption_cost_minor: 0, savings_vs_cash_minor: 0, dominated: true, award: {
        id: "aw_002", program_id: "star-alliance", origin: "DEL", destination: "SIN",
        cabin: "economy", trip_type: "round_trip", miles_cost: 120000, fees_minor: 500000,
        fees_currency: "INR", operating_airline_hint: "Singapore Airlines",
        availability_note: "Standard award", provenance: {
          source_url: "", source_type: "manual_curation", last_verified: "2026-07-01",
          verified_by: "sample", needs_verification: true, confidence: 0.8,
        },
      }, steps: [], checklist_steps: [], explanation: [] }],
      infeasible: [],
    },
  };
}

function createNoDataReport(): FinalReport {
  return {
    ...baseReport(),
    trace_id: "msw-nodata-001",
    status: "ok",
    itinerary: {
      hotel_area_id: "marina_bay",
      days: [{ date: "2026-08-01", unmet_needs: [], rejections: [], items: [] }, { date: "2026-08-02", unmet_needs: [], rejections: [], items: [] }, { date: "2026-08-03", unmet_needs: [], rejections: [], items: [] }, { date: "2026-08-04", unmet_needs: [], rejections: [], items: [] }],
      itinerary_quality: "llm",
    },
    summary: "We couldn't find award or transfer options for your wallet.",
    itinerary_overview: "Paying cash is your only option with the current wallet.",
    payment_overview: "Pay cash — no transfer or award options available.",
    footer: "Add more cards or points programs to see comparison options.",
    transfer_advice: {
      recommendation: { kind: "NO_DATA", reason: "No transfer partners match your current wallet" },
      plans: [],
      infeasible: [
        { award_id: "aw_star_alliance", best_path: ["voyager-prime"], shortfall_points: 50000, shortfall_currency: "StarAlliance", note: "Not enough Voyager Prime points for the minimum award" },
      ],
    },
  };
}

function createClarificationStatus(): PlanJobStatus {
  return {
    job_id: "",
    status: "needs_clarification",
    stage: "intake",
    stage_index: 1,
    stages_total: 6,
    unresolved: ["origin city unclear", "travel dates needed"],
  };
}

function createFailedStatus(jobId: string): PlanJobStatus {
  return {
    job_id: jobId,
    status: "failed",
    stage: "intake",
    stage_index: 1,
    stages_total: 6,
    error: { code: "PIPELINE_ERROR", message: "Intake parsing failed", trace_id: `msw-fail-${jobId}` },
  };
}

export const handlers = [
  http.post("*/plan", async ({ request }) => {
    const body = (await request.json()) as { raw_request?: string };
    if (!body?.raw_request) {
      return HttpResponse.json(
        { detail: [{ loc: ["body", "raw_request"], msg: "field required", type: "value_error" }] },
        { status: 422 }
      );
    }

    const jobId = Math.random().toString(36).slice(2, 10);

    const initialStatus: PlanJobStatus = {
      job_id: jobId,
      status: "queued",
      stage: null,
      stage_index: null,
      stages_total: STAGES.length,
    };

    jobStore[jobId] = { status: initialStatus, timer: null };

    let stageIdx = 0;
    const timer = setInterval(() => {
      const entry = jobStore[jobId];
      if (!entry) return;

      if (stageIdx < STAGES.length) {
        entry.status = {
          ...entry.status,
          status: "running",
          stage: STAGES[stageIdx]!,
          stage_index: stageIdx + 1,
        };
        stageIdx++;
      } else {
        entry.status = {
          ...entry.status,
          status: "complete",
          stage: "explaining",
          stage_index: STAGES.length,
          report: createHappyReport(),
        };
        clearInterval(timer);
        entry.timer = null;
      }
    }, 300 * SPEED_MULTIPLIER);

    return HttpResponse.json({ job_id: jobId }, { status: 202 });
  }),

  http.get("*/plan/:jobId", ({ params }) => {
    const { jobId } = params;
    const entry = jobStore[jobId as string];
    if (!entry) {
      return HttpResponse.json(
        { detail: [{ loc: ["path", "job_id"], msg: "Job not found", type: "value_error" }] },
        { status: 404 }
      );
    }
    return HttpResponse.json(entry.status);
  }),
];

export const fixtureHandlers = {
  clarification: http.get("*/plan/:jobId", () => {
    return HttpResponse.json(createClarificationStatus());
  }),

  failed: http.get("*/plan/:jobId", ({ params }) => {
    return HttpResponse.json(createFailedStatus(params.jobId as string));
  }),

  happyReport: () => createHappyReport(),
  fallbackReport: () => createFallbackReport(),
  provenanceWarningsReport: () => createProvenanceWarningsReport(),
  redeemReport: () => createRedeemReport(),
  payCashReport: () => createPayCashReport(),
  noDataReport: () => createNoDataReport(),
};
