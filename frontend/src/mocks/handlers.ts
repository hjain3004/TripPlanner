import { http, HttpResponse } from "msw";
import type {
  CredentialsIn,
  FinalReport,
  PlanJobStatus,
  RecomputeRequest,
  RefreshProseRequest,
  UserOut,
} from "@/lib/api";

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
        { id: "poi:poi_001", label: "Gardens by the Bay", category: "attractions", amount_minor: 450000, currency: "INR", available_channels: ["pos_abroad"] },
      ],
    },
    optimizer_result: {
      assignments: [
        {
          line: { id: "poi:poi_001", label: "Gardens by the Bay", category: "attractions", amount_minor: 450000, currency: "INR", available_channels: ["pos_abroad"] },
          card_id: "hdfc-infinia",
          channel: "pos_abroad",
          points_earned: 750,
          points_value_minor: 75000,
          forex_fee_minor: 9000,
          benefit_minor: 66000,
          assumed_redemption: "portal_flights",
          explanation: ["5x reward rate via international POS on Infinia", "2% markup offset by 3.3% net points value"],
          provenance_flags: ["verified"],
        }
      ],
      gross_minor: 20450000, discounts_minor: 200000, rewards_value_minor: 875000,
      forex_fees_minor: 9000, effective_cost_minor: 19384000, cash_outlay_now_minor: 20259000,
      deferred_value_minor: 875000, savings_pct_bp: 1050, cap_pools_final: {}, confidence: 0.85,
    },
    budget_totals: {
      gross_minor: 20450000, discounts_minor: 200000, rewards_value_minor: 875000,
      forex_fees_minor: 9000, effective_cost_minor: 19384000, cash_outlay_now_minor: 20259000,
      deferred_value_minor: 875000, savings_pct_bp: 1050,
    },
    payment_strategy: [
      { line_id: "flight_001", label: "DEL→SIN flights (2 pax)", card_id: "hdfc-infinia", channel: "direct_airline", action_sentence: "Book with HDFC Infinia via direct airline for 5% cashback" },
      { line_id: "poi:poi_001", label: "Gardens by the Bay", card_id: "hdfc-infinia", channel: "pos_abroad", action_sentence: "Use HDFC Infinia for 3.3% net reward return overseas" },
    ],
    confidence: 0.85,
    assumptions: ["Sample data used — verify before booking"],
    flights_pick: null,
    hotel_pick: null,
    freshness: {
      budget: "fresh",
      payment_strategy: "fresh",
      itinerary: "fresh",
      prose: "fresh",
      critic_verdict: "fresh",
      edit_count: 0,
    },
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
        {
          date: "2026-08-01",
          unmet_needs: ["travel budget exceeded"],
          rejections: [],
          items: [
            {
              poi_id: "poi_001",
              start_hint: "morning",
              name: "Gardens by the Bay",
              category: "nature",
              lat: 1.2815,
              lon: 103.8636,
              travel_from_previous: { duration_min: 15, status: "estimated", source: "mock" },
              evidence: { status: "live", last_verified: "2026-07-01", licence_id: null, attribution: null, needs_verification: false, poi_id: "poi_001" },
            },
            {
              poi_id: "poi_002",
              start_hint: "afternoon",
              name: "Merlion Park",
              category: "landmark",
              lat: 1.2868,
              lon: 103.8545,
              travel_from_previous: { duration_min: 10, status: "estimated", source: "mock" },
              evidence: { status: "live", last_verified: "2026-07-01", licence_id: null, attribution: null, needs_verification: false, poi_id: "poi_002" },
            },
          ],
        },
        {
          date: "2026-08-02",
          unmet_needs: [],
          rejections: [],
          items: [
            {
              poi_id: "poi_003",
              start_hint: "morning",
              name: "Singapore Botanic Gardens",
              category: "nature",
              lat: 1.3138,
              lon: 103.8159,
              evidence: { status: "live", last_verified: "2026-07-01", licence_id: null, attribution: null, needs_verification: false, poi_id: "poi_003" },
            },
          ],
        },
        { date: "2026-08-03", unmet_needs: [], rejections: [], items: [] },
        { date: "2026-08-04", unmet_needs: [], rejections: [], items: [] },
      ],
      itinerary_quality: "llm",
    },
    summary: "A well-balanced 4-night trip to Singapore with solid savings.",
    itinerary_overview: "Explore Marina Bay with a nature-focused itinerary.",
    payment_overview: "Use HDFC Infinia for flights and attractions to maximize savings.",
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

function createRegionCapabilityReport(): FinalReport {
  return {
    ...baseReport(),
    trace_id: "msw-region-cap-001",
    status: "ok",
    itinerary: {
      hotel_area_id: "marina_bay",
      days: [
        { date: "2026-08-01", unmet_needs: [], rejections: [], items: [] },
        { date: "2026-08-02", unmet_needs: [], rejections: [], items: [] },
      ],
      itinerary_quality: "llm",
    },
    summary: "Itinerary ready — cost data isn't available for this destination yet.",
    itinerary_overview: "A first look at the destination, without a costed budget.",
    payment_overview: "",
    footer: "Sample data. Verify before booking.",
    region_capability: {
      region: "BOM",
      catalog_status: "active",
      place_count: 340,
      budget_supported: false,
      known_gaps: ["No FX rates or per-diem data for INR"],
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
  http.post("*/auth/register", async ({ request }) => {
    const body = (await request.json()) as CredentialsIn;
    const user: UserOut = {
      id: "msw-user-001",
      email: body.email.trim().toLowerCase(),
      status: "active",
    };
    return HttpResponse.json(user, { status: 201 });
  }),

  http.post("*/auth/login", async ({ request }) => {
    const body = (await request.json()) as CredentialsIn;
    const user: UserOut = {
      id: "msw-user-001",
      email: body.email.trim().toLowerCase(),
      status: "active",
    };
    return HttpResponse.json(user);
  }),

  http.post("*/auth/logout", () => new HttpResponse(null, { status: 204 })),

  http.get("*/auth/me", () => {
    const user: UserOut = {
      id: "msw-user-001",
      email: "student@example.com",
      status: "active",
    };
    return HttpResponse.json(user);
  }),

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

  http.post("*/places/search", async ({ request }) => {
    const body = (await request.json()) as { destination: string; query?: string; category?: string; limit?: number };
    const query = (body.query || "").toLowerCase();
    const catalog = [
      {
        poi_id: "poi_jewel",
        name: "Jewel Changi Airport",
        category: "attractions",
        area: "Changi",
        lat: 1.3602,
        lon: 103.9897,
        price_minor: 0,
        currency: "SGD",
        evidence: { status: "live", last_verified: "2026-07-01", licence_id: null, attribution: null, needs_verification: false, poi_id: "poi_jewel" },
      },
      {
        poi_id: "poi_maxwell",
        name: "Maxwell Food Centre",
        category: "food",
        area: "Chinatown",
        lat: 1.2803,
        lon: 103.8447,
        price_minor: 1500,
        currency: "SGD",
        evidence: { status: "live", last_verified: "2026-07-01", licence_id: null, attribution: null, needs_verification: false, poi_id: "poi_maxwell" },
      },
      {
        poi_id: "poi_artscience",
        name: "ArtScience Museum",
        category: "culture",
        area: "Marina Bay",
        lat: 1.2863,
        lon: 103.8593,
        price_minor: 3000,
        currency: "SGD",
        evidence: { status: "live", last_verified: "2026-07-01", licence_id: null, attribution: null, needs_verification: false, poi_id: "poi_artscience" },
      },
      {
        poi_id: "poi_zoo",
        name: "Singapore Zoo",
        category: "nature",
        area: "Mandai",
        lat: 1.4043,
        lon: 103.7930,
        price_minor: 4800,
        currency: "SGD",
        evidence: { status: "live", last_verified: "2026-07-01", licence_id: null, attribution: null, needs_verification: false, poi_id: "poi_zoo" },
      },
    ];
    let filtered = catalog;
    if (body.category) {
      filtered = filtered.filter((p) => p.category.toLowerCase() === body.category?.toLowerCase());
    }
    if (query) {
      filtered = filtered.filter((p) => p.name.toLowerCase().includes(query) || p.category.toLowerCase().includes(query));
    }
    return HttpResponse.json({ results: filtered.slice(0, body.limit || 10) });
  }),

  http.post("*/plan/recompute", async ({ request }) => {
    const body = (await request.json()) as RecomputeRequest;
    const rep = createHappyReport();
    rep.itinerary = body.itinerary ? JSON.parse(JSON.stringify(body.itinerary)) : rep.itinerary;

    // Apply edit to mock itinerary if present
    const edit = body.edit as (
      | { op: "add_item"; poi_id: string; day_index: number; position: number }
      | { op: "replace_item"; old_poi_id: string; new_poi_id: string; day_index: number }
      | { op: "remove_item"; poi_id: string; day_index: number }
      | undefined
    );
    if (edit) {
      if (edit.op === "add_item") {
        const day = rep.itinerary.days[edit.day_index];
        if (day) {
          day.items = day.items || [];
          day.items.splice(edit.position, 0, {
            poi_id: edit.poi_id,
            name: edit.poi_id === "poi_jewel" ? "Jewel Changi Airport" : edit.poi_id,
            category: "attractions",
            lat: 1.3602,
            lon: 103.9897,
            evidence: { status: "live", last_verified: "2026-07-01", licence_id: null, attribution: null, needs_verification: false, poi_id: edit.poi_id },
          });
        }
      } else if (edit.op === "replace_item") {
        const day = rep.itinerary.days[edit.day_index];
        if (day?.items) {
          const idx = day.items.findIndex((item) => item.poi_id === edit.old_poi_id);
          if (idx !== -1) {
            day.items[idx] = {
              poi_id: edit.new_poi_id,
              name: edit.new_poi_id === "poi_artscience" ? "ArtScience Museum" : edit.new_poi_id,
              category: "culture",
              lat: 1.2863,
              lon: 103.8593,
              evidence: { status: "live", last_verified: "2026-07-01", licence_id: null, attribution: null, needs_verification: false, poi_id: edit.new_poi_id },
            };
          }
        }
      } else if (edit.op === "remove_item") {
        const day = rep.itinerary.days[edit.day_index];
        if (day?.items) {
          day.items = day.items.filter((item) => item.poi_id !== edit.poi_id);
        }
      }
    }

    const prevCount = body.previous_freshness?.edit_count ?? 0;
    rep.freshness = {
      budget: "recomputed",
      payment_strategy: "recomputed",
      itinerary: "recomputed",
      prose: "stale",
      critic_verdict: "stale",
      edit_count: prevCount + 1,
    };
    return HttpResponse.json(rep);
  }),

  http.post("*/plan/refresh-prose", async ({ request }) => {
    const body = (await request.json()) as RefreshProseRequest;
    const rep = createHappyReport();
    rep.itinerary = body.itinerary || rep.itinerary;
    const prev = body.previous_freshness;
    rep.freshness = {
      budget: prev?.budget ?? "recomputed",
      payment_strategy: prev?.payment_strategy ?? "recomputed",
      itinerary: prev?.itinerary ?? "recomputed",
      prose: "fresh",
      critic_verdict: prev?.critic_verdict ?? "stale",
      edit_count: prev?.edit_count ?? 1,
    };
    return HttpResponse.json(rep);
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
  regionCapabilityReport: () => createRegionCapabilityReport(),
};
