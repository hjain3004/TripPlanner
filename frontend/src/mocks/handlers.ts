import { http, HttpResponse, type JsonBodyType } from "msw";
import type {
  ApiErrorBody,
  CredentialsIn,
  FinalReport,
  PlanJobStatus,
  RecomputeRequest,
  RefreshProseRequest,
  RerunStatusOut,
  RevisionOut,
  SaveTripIn,
  TripDetailOut,
  TripSummaryOut,
  UserOut,
  WelcomeStatusApiErrorBody,
  WelcomeStatusIn,
  WelcomeWindowReport,
} from "@/lib/api";
import { createJapanVisualReport } from "./japan-visual-fixture";

const SPEED_MULTIPLIER = 1;

const jobStore: Record<string, { status: PlanJobStatus; timer: ReturnType<typeof setInterval> | null }> = {};
const questionCatalog = [{ id: "trip_essentials", prompt: "Where are you headed, and what are your travel dates?", phase: "core", answer_kind: "trip_essentials", required: true, allow_delegate: false, control: { type: "trip_essentials", fields: ["origin", "destination", "start_date", "end_date", "travelers"], allow_skip: false, options: [] } }];
const conversationSession = {
  id: "msw-session-001",
  user_id: "msw-user-001",
  status: "interviewing",
  version: 0,
  created_at: "2026-08-29T00:00:00Z",
  updated_at: "2026-08-29T00:00:00Z",
  expires_at: "2026-09-28T00:00:00Z",
  current_question: questionCatalog[0],
  question_catalog: questionCatalog,
  suggested_question_ids: [],
  progress: { completed: 0, minimum_total: 8, maximum_total: 12, status: "interviewing" },
  // The wallet the session will plan with, snapshotted server-side at session
  // start (A3). The review step renders this, not a live account re-read.
  wallet: { card_ids: ["hdfc-infinia"], points_balances: { "hdfc-reward-points": 100 } },
  answers: {},
  events: [{ id: "msw-event-001", kind: "assistant_question", question_id: "trip_essentials", text: "Where are you headed, and what are your travel dates?", created_at: "2026-08-29T00:00:00Z" }],
  assistance_status: "not_run",
  assistance_pending: false,
  assistance_diagnostics: [],
  interview_llm_calls: 0,
  pending_answer: null,
  contradictions: [],
  pending_profile_updates: [],
  brief: null,
  planning_job_id: null,
};

const cp4Workspace: {
  session_id: string;
  version: number;
  current_result_id: string;
  workspace: Record<string, unknown>;
  report: ReturnType<typeof createHappyReport>;
  operations: unknown[];
} = {
  session_id: "msw-session-001",
  version: 1,
  current_result_id: "msw-result-001",
  workspace: { session_id: "msw-session-001", confirmed_brief_revision: 1 },
  report: createHappyReport(),
  operations: [],
};

type Cp4ProposalFixture = {
  proposal_id: string;
  operation_id: string;
  status: string;
  action: unknown;
  impact: Record<string, unknown>;
  decision: "pending" | "approved" | "rejected";
};

const cp4Proposals = new Map<string, Cp4ProposalFixture>();
const cp4RevisionEvents = new Map<string, { trip_id: string; revision: number; result_id: string }>();

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
    travel_inventory: {
      flight: {
        domain: "flight",
        quote_id: "sample-flight-001",
        provider_id: "sample_travel_adapter",
        provider_quote_id: "sample-flight-001",
        status: "estimated",
        needs_verification: true,
        source_url: null,
        deep_link_url: null,
        attribution: "TripPlanner sample fixture data (not real inventory)",
        retrieved_at: "2026-08-01T00:00:00Z",
        expires_at: null,
        completeness: "taxes_uncertain",
        source_amount_minor: 8200000,
        source_currency: "INR",
        converted_amount_minor: 8200000,
        price_scope: { basis: "sample_per_traveler_trip", scope_verified: true, travelers: 2, rooms: null },
        selected: true,
        alternative: false,
        limitations: ["Verify price and availability before booking."],
      },
      hotel: null,
      alternatives: [],
      diagnostics: [],
      limitations: ["Award guidance is reference-only; verify before transfer."],
      reference_only_awards: true,
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

// --- A3 wallet: a small stateful mock so add/edit/remove actually round-trip.
// Without state the /wallet route could not be exercised end to end in mock mode.
type MswWalletEntry = {
  id: string;
  card_id: string;
  nickname: string;
  last4: string | null;
  statement_day: number | null;
  opened_on: string | null;
  points_balances: Record<string, number>;
  added_at: string;
  version: number;
};

const MSW_CARD_PRODUCTS = [
  { card_id: "axis-atlas", display_name: "Atlas", issuer: "Axis Bank", is_eligible: true },
  { card_id: "hdfc-infinia", display_name: "Infinia Metal", issuer: "HDFC Bank", is_eligible: true },
  { card_id: "icici-emeralde", display_name: "Emeralde Private Metal", issuer: "ICICI Bank", is_eligible: true },
  { card_id: "sbi-cashback", display_name: "Cashback", issuer: "SBI Card", is_eligible: true },
];

let mswWallet: MswWalletEntry[] = [];
let mswWalletSeq = 0;

export function resetMswWallet(entries: MswWalletEntry[] = []): void {
  mswWallet = [...entries];
  mswWalletSeq = entries.length;
}

function mswWalletSorted(): MswWalletEntry[] {
  return [...mswWallet].sort((a, b) =>
    a.card_id === b.card_id ? a.id.localeCompare(b.id) : a.card_id.localeCompare(b.card_id),
  );
}

// Mirrors accounts/projection.py: card ids de-duplicated and sorted, duplicate
// points currencies collapsed by MAX (never summed).
function mswProjection(): { card_ids: string[]; points_balances: Record<string, number> } {
  const cardIds = [...new Set(mswWallet.map((e) => e.card_id))].sort();
  const balances: Record<string, number> = {};
  for (const entry of mswWallet) {
    for (const [currency, amount] of Object.entries(entry.points_balances)) {
      const current = balances[currency];
      if (current === undefined || amount > current) balances[currency] = amount;
    }
  }
  const ordered: Record<string, number> = {};
  for (const key of Object.keys(balances).sort()) {
    const value = balances[key];
    if (value !== undefined) ordered[key] = value;
  }
  return { card_ids: cardIds, points_balances: ordered };
}

function walletConflict(code: string, message: string) {
  return HttpResponse.json({ detail: { code, message } }, { status: 409 });
}


// --- A4 saved trips (stateful mock; mirrors api/saved_trips.py) ---------------
//
// Reports are returned verbatim as stored, never re-derived. The mock models the
// behaviour a UI must handle: idempotent replay and event-id reuse, one trip per
// planning session, the session a trip is attached to, the trip/revision caps, and a
// re-run that is "running" until its revision has been appended.
//
// Sentinel session ids select the documented plan-state failures deterministically.

const MSW_MAX_TRIPS = 50;
const MSW_MAX_REVISIONS = 25;

interface MswTripRecord {
  summary: TripSummaryOut;
  revisions: RevisionOut[];
  sessionId: string;
}

interface MswRerun {
  tripId: string;
  polls: number;
  revision: number | null;
}

let mswTrips: MswTripRecord[] = [];
let mswTripSeq = 0;
/** `<operation>:<client_event_id>` -> original fingerprint + response body (replay). */
let mswTripEvents = new Map<string, { fingerprint: string; body: JsonBodyType }>();
let mswReruns = new Map<string, MswRerun>();
/** Rerun starts by client event id -> fingerprint + job id (in memory, as in the API). */
let mswRerunStarts = new Map<string, { fingerprint: string; jobId: string }>();

export function resetMswTrips(): void {
  mswTrips = [];
  mswTripSeq = 0;
  mswTripEvents = new Map();
  mswReruns = new Map();
  mswRerunStarts = new Map();
}

function tripError(
  status: number,
  code: ApiErrorBody["code"],
  message: string,
  extra: Record<string, string> = {},
) {
  return HttpResponse.json({ detail: { code, message, ...extra } }, { status });
}

const tripNotFound = () => tripError(404, "TRIP_NOT_FOUND", "No such saved trip.");
const eventReused = () =>
  tripError(409, "IDEMPOTENCY_KEY_REUSED", "This client event id was already used for a different request.");

/** Plan-state failures selected by sentinel session ids (the API reads these off the job). */
function sessionFailure(sessionId: string) {
  switch (sessionId) {
    case "msw-session-missing":
      return tripError(404, "SESSION_NOT_FOUND", "Planning session not found");
    case "msw-session-expired":
      return tripError(410, "SESSION_EXPIRED", "Planning session has expired");
    case "msw-session-unconfirmed":
      return tripError(409, "SESSION_NOT_CONFIRMED", "Confirm the trip brief and let planning finish before saving.");
    case "msw-session-lost":
      return tripError(409, "PLAN_RESULT_UNAVAILABLE", "This plan's result is no longer available to save. Plan the trip again.");
    default:
      return null;
  }
}

function mswRevision(n: number, report: Record<string, unknown>): RevisionOut {
  return {
    revision: n,
    computed_at: "2026-10-24T12:00:00+00:00",
    trace_id: `msw-trace-${n}`,
    schema_version: "1",
    is_current_schema: true,
    report,
  };
}

function mswReport(): Record<string, unknown> {
  return createHappyReport() as unknown as Record<string, unknown>;
}

function refreshSummary(record: MswTripRecord): void {
  const latest = record.revisions[record.revisions.length - 1];
  if (latest === undefined) return;
  record.summary = {
    ...record.summary,
    revision_count: record.revisions.length,
    latest_revision: latest.revision,
    latest_computed_at: latest.computed_at,
  };
}

function mswTripDetail(record: MswTripRecord): TripDetailOut {
  return {
    ...record.summary,
    revisions: record.revisions.map((r) => ({
      revision: r.revision,
      computed_at: r.computed_at,
      trace_id: r.trace_id,
      schema_version: r.schema_version,
      is_current_schema: r.is_current_schema,
    })),
  };
}

function hasActiveRerun(tripId: string): boolean {
  return [...mswReruns.values()].some((r) => r.tripId === tripId && r.revision === null);
}

/** Typed error responses for every documented saved-trip failure (status + code). */
export const SAVED_TRIP_ERROR_FIXTURES = {
  unauthenticated: { status: 401, detail: "Not authenticated" },
  csrf: { status: 403, detail: "CSRF check failed" },
  TRIP_NOT_FOUND: { status: 404, code: "TRIP_NOT_FOUND" },
  SESSION_NOT_FOUND: { status: 404, code: "SESSION_NOT_FOUND" },
  REVISION_NOT_FOUND: { status: 404, code: "REVISION_NOT_FOUND" },
  RERUN_NOT_FOUND: { status: 404, code: "RERUN_NOT_FOUND" },
  PLAN_RESULT_UNAVAILABLE: { status: 409, code: "PLAN_RESULT_UNAVAILABLE" },
  SESSION_NOT_CONFIRMED: { status: 409, code: "SESSION_NOT_CONFIRMED" },
  SESSION_ALREADY_SAVED: { status: 409, code: "SESSION_ALREADY_SAVED", trip_id: "msw-trip-1" },
  SESSION_NOT_ATTACHED: { status: 409, code: "SESSION_NOT_ATTACHED" },
  STALE_SESSION: { status: 409, code: "STALE_SESSION" },
  RERUN_IN_PROGRESS: { status: 409, code: "RERUN_IN_PROGRESS" },
  TRIP_NOT_RERUNNABLE: { status: 409, code: "TRIP_NOT_RERUNNABLE" },
  TRIP_LIMIT_REACHED: { status: 409, code: "TRIP_LIMIT_REACHED" },
  REVISION_LIMIT_REACHED: { status: 409, code: "REVISION_LIMIT_REACHED" },
  IDEMPOTENCY_KEY_REUSED: { status: 409, code: "IDEMPOTENCY_KEY_REUSED" },
  TRIP_REVISION_CONFLICT: { status: 409, code: "TRIP_REVISION_CONFLICT" },
  SESSION_EXPIRED: { status: 410, code: "SESSION_EXPIRED" },
  REPORT_TOO_LARGE: { status: 413, code: "REPORT_TOO_LARGE" },
  SAVED_TRIP_INVALID: { status: 422, code: "SAVED_TRIP_INVALID" },
  SAVED_TRIPS_UNAVAILABLE: { status: 503, code: "SAVED_TRIPS_UNAVAILABLE" },
} as const satisfies Record<
  string,
  { status: number; code?: ApiErrorBody["code"]; detail?: string; trip_id?: string }
>;

export type SavedTripErrorFixture = keyof typeof SAVED_TRIP_ERROR_FIXTURES;

/** A one-off handler that answers the given route with a documented failure. */
export function savedTripErrorHandler(
  method: "get" | "post" | "delete",
  path: string,
  fixture: SavedTripErrorFixture,
) {
  const spec = SAVED_TRIP_ERROR_FIXTURES[fixture] as {
    status: number;
    code?: ApiErrorBody["code"];
    detail?: string;
    trip_id?: string;
  };
  return http[method](path, () =>
    spec.code === undefined
      ? HttpResponse.json({ detail: spec.detail }, { status: spec.status })
      : tripError(
          spec.status,
          spec.code,
          "Mocked saved-trip failure.",
          spec.trip_id === undefined ? {} : { trip_id: spec.trip_id },
        ),
  );
}

// --- Spec 18 Case A welcome-window status (mirrors api/welcome.py) -------------
//
// With no approved offer data shipped, the real route answers `unknown` /
// NO_APPROVED_OFFER, so that is what this mock answers: it never invents a window, a
// shortfall or a bonus. Wallet entry, trip and revision are resolved against the same
// stateful mocks the wallet and saved-trip routes use, with the same typed not-found errors.

function welcomeError(status: number, code: WelcomeStatusApiErrorBody["code"], message: string) {
  return HttpResponse.json({ detail: { code, message } }, { status });
}

interface MswStoredAssignment {
  card_id?: string;
  channel?: string;
  offers_applied?: { discount_minor?: number }[];
  line?: { id?: string; label?: string; category?: string; amount_minor?: number; currency?: string };
}

/** This card's assigned lines in a stored mock report, read the way the API reads them. */
function mswCardLines(report: RevisionOut["report"], cardId: string) {
  const result = report.optimizer_result as { assignments?: MswStoredAssignment[] } | undefined;
  const lines: WelcomeWindowReport["lines"] = [];
  let omittedZero = 0;
  for (const a of result?.assignments ?? []) {
    if (a.card_id !== cardId) continue;
    const amount = a.line?.amount_minor ?? 0;
    if (amount === 0) {
      omittedZero += 1;
      continue;
    }
    const discounts = (a.offers_applied ?? []).reduce((sum, o) => sum + (o.discount_minor ?? 0), 0);
    const channel = a.channel ?? "";
    lines.push({
      line_id: a.line?.id ?? "",
      label: a.line?.label ?? "",
      category: a.line?.category ?? "",
      channel,
      timing_basis: channel.startsWith("pos_") ? "on_trip" : "advance_booking",
      amount_minor: amount,
      instant_discounts_minor: discounts,
      counted_minor: Math.max(0, amount - discounts),
      currency: a.line?.currency ?? "INR",
      assessment: "window_unknown",
    });
  }
  return { lines, omittedZero };
}

export const WELCOME_STATUS_ERROR_FIXTURES = {
  unauthenticated: { status: 401, detail: "Not authenticated" },
  csrf: { status: 403, detail: "CSRF check failed" },
  WALLET_ENTRY_NOT_FOUND: { status: 404, code: "WALLET_ENTRY_NOT_FOUND" },
  TRIP_NOT_FOUND: { status: 404, code: "TRIP_NOT_FOUND" },
  REVISION_NOT_FOUND: { status: 404, code: "REVISION_NOT_FOUND" },
  REVISION_NOT_READABLE: { status: 409, code: "REVISION_NOT_READABLE" },
  WELCOME_STATUS_UNAVAILABLE: { status: 503, code: "WELCOME_STATUS_UNAVAILABLE" },
} as const satisfies Record<
  string,
  { status: number; code?: WelcomeStatusApiErrorBody["code"]; detail?: string }
>;

export type WelcomeStatusErrorFixture = keyof typeof WELCOME_STATUS_ERROR_FIXTURES;

/** A one-off handler that answers the welcome-status route with a documented failure. */
export function welcomeStatusErrorHandler(fixture: WelcomeStatusErrorFixture) {
  const spec = WELCOME_STATUS_ERROR_FIXTURES[fixture] as {
    status: number;
    code?: WelcomeStatusApiErrorBody["code"];
    detail?: string;
  };
  return http.post("*/account/wallet/:entryId/welcome-status", () =>
    spec.code === undefined
      ? HttpResponse.json({ detail: spec.detail }, { status: spec.status })
      : welcomeError(spec.status, spec.code, "Mocked welcome-status failure."),
  );
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

  http.get("*/planning/preferences", () => HttpResponse.json({ profile: { user_id: "msw-user-001", updated_at: today(), flight: null, stay: null, rhythm: null, experiences: null, constraints: null, optimization: null } })),
  http.patch("*/planning/preferences", async ({ request }) => HttpResponse.json({ profile: await request.json() })),
  http.post("*/planning/sessions", () => HttpResponse.json(conversationSession, { status: 201 })),
  http.get("*/planning/sessions/:sessionId", () => HttpResponse.json(conversationSession)),
  http.post("*/planning/sessions/:sessionId/interpret", async ({ request }) => {
    const body = await request.json() as { expected_version: number };
    return HttpResponse.json({ ...conversationSession, version: body.expected_version + 1, assistance_status: "degraded", assistance_diagnostics: ["unavailable"], interview_llm_calls: 1 });
  }),
  http.post("*/planning/sessions/:sessionId/answers", async ({ request }) => {
    const body = (await request.json()) as { client_event_id?: string };
    return HttpResponse.json({ ...conversationSession, version: 1, answers: {}, events: [...conversationSession.events, { id: `msw-answer-${body.client_event_id ?? "1"}`, kind: "user_answer", text: "Answer recorded.", created_at: new Date().toISOString() }] });
  }),
  http.post("*/planning/sessions/:sessionId/skip", () => HttpResponse.json({ ...conversationSession, version: 1 })),
  http.get("*/planning/sessions/:sessionId/review", () => HttpResponse.json({ ...conversationSession, status: "reviewing" })),
  http.post("*/planning/sessions/:sessionId/back", () => HttpResponse.json({ ...conversationSession, version: 1 })),
  http.post("*/planning/sessions/:sessionId/amend", () => HttpResponse.json({ ...conversationSession, status: "reviewing", version: 1 })),
  http.post("*/planning/sessions/:sessionId/profile-updates/:proposalId/approve", () => HttpResponse.json({ ...conversationSession, version: 1 })),
  http.post("*/planning/sessions/:sessionId/confirm", () => HttpResponse.json({ ...conversationSession, status: "planning", planning_job_id: "msw-job-001", job_id: "msw-job-001" }, { status: 202 })),
  http.get("*/planning/sessions/:sessionId/job", () => HttpResponse.json({ job_id: "msw-job-001", status: "complete", stage: "explaining", progress: 1 })),
  http.post("*/planning/sessions/:sessionId/workspace", () => HttpResponse.json(cp4Workspace)),
  http.get("*/planning/sessions/:sessionId/workspace", () => HttpResponse.json(cp4Workspace)),
  http.post("*/planning/sessions/:sessionId/actions", async ({ request }) => {
    const body = await request.json() as { client_event_id?: string; action?: unknown };
    const eventId = body.client_event_id ?? "1";
    const replay = cp4Proposals.get(eventId);
    if (replay) return HttpResponse.json(replay);
    const proposal: Cp4ProposalFixture = { proposal_id: `msw-proposal-${body.client_event_id ?? "1"}`, operation_id: `msw-operation-${body.client_event_id ?? "1"}`, status: "complete", action: body.action ?? { kind: "clarification_required", reason: "needs_detail", question: "What should change?", choices: [] }, impact: { invalidated_domains: [], affected_dates: [], refetch_domains: [], inventory_reuse: "full", requires_confirmation: false, changes_trip: false, explanation_only: false }, decision: "pending" };
    cp4Proposals.set(eventId, proposal);
    cp4Workspace.version += 1;
    cp4Workspace.operations = [...cp4Workspace.operations, proposal];
    return HttpResponse.json(proposal);
  }),
  http.post("*/planning/sessions/:sessionId/actions/:proposalId/approve", ({ params }) => {
    const proposal = [...cp4Proposals.values()].find((value) => value.proposal_id === params.proposalId);
    if (!proposal || proposal.decision !== "pending") return HttpResponse.json({ detail: { code: "PROPOSAL_NOT_PENDING", message: "This proposal is no longer pending." } }, { status: 409 });
    proposal.decision = "approved";
    cp4Workspace.version += 1;
    cp4Workspace.current_result_id = `msw-result-${cp4Workspace.version}`;
    return HttpResponse.json({ operation_id: `msw-approve-${params.proposalId}`, proposal_id: params.proposalId, status: "complete", decision: "approved", result_id: cp4Workspace.current_result_id });
  }),
  http.post("*/planning/sessions/:sessionId/actions/:proposalId/reject", ({ params }) => {
    const proposal = [...cp4Proposals.values()].find((value) => value.proposal_id === params.proposalId);
    if (!proposal || proposal.decision !== "pending") return HttpResponse.json({ detail: { code: "PROPOSAL_NOT_PENDING", message: "This proposal is no longer pending." } }, { status: 409 });
    proposal.decision = "rejected";
    cp4Workspace.version += 1;
    return HttpResponse.json({ operation_id: `msw-reject-${params.proposalId}`, proposal_id: params.proposalId, status: "complete", decision: "rejected", result_id: cp4Workspace.current_result_id });
  }),
  http.post("*/planning/sessions/:sessionId/workspace/revisions", async ({ request }) => {
    const body = await request.json() as { client_event_id?: string; expected_workspace_version?: number };
    const eventId = body.client_event_id ?? "revision-1";
    const replay = cp4RevisionEvents.get(eventId);
    if (replay) return HttpResponse.json(replay, { status: 201 });
    if (body.expected_workspace_version !== cp4Workspace.version) {
      return HttpResponse.json(
        { detail: { code: "STALE_WORKSPACE", message: "The accepted result changed." } },
        { status: 409 },
      );
    }
    const result = {
      trip_id: "msw-trip-001",
      revision: cp4Workspace.version,
      result_id: cp4Workspace.current_result_id,
    };
    cp4RevisionEvents.set(eventId, result);
    return HttpResponse.json(result, { status: 201 });
  }),

  // --- A3 authenticated wallet ---
  http.get("*/account/card-products", () => HttpResponse.json(MSW_CARD_PRODUCTS)),

  http.get("*/account/wallet", () => HttpResponse.json(mswWalletSorted())),

  http.get("*/account/wallet/projection", () => HttpResponse.json(mswProjection())),

  http.post("*/account/wallet", async ({ request }) => {
    const body = (await request.json()) as Partial<MswWalletEntry> & { card_id?: string };
    if (!MSW_CARD_PRODUCTS.some((p) => p.card_id === body.card_id)) {
      return HttpResponse.json(
        { detail: { code: "unknown_card_product", message: "That card product is not available." } },
        { status: 422 },
      );
    }
    mswWalletSeq += 1;
    const entry: MswWalletEntry = {
      id: `msw-wallet-${mswWalletSeq}`,
      card_id: body.card_id as string,
      nickname: body.nickname ?? "Card",
      last4: body.last4 ?? null,
      statement_day: body.statement_day ?? null,
      opened_on: body.opened_on ?? null,
      points_balances: body.points_balances ?? {},
      added_at: new Date("2026-10-19T12:00:00Z").toISOString(),
      version: 1,
    };
    mswWallet.push(entry);
    return HttpResponse.json(entry, { status: 201 });
  }),

  http.patch("*/account/wallet/:entryId", async ({ request, params }) => {
    const body = (await request.json()) as Record<string, unknown>;
    const current = mswWallet.find((e) => e.id === params.entryId);
    if (current === undefined) {
      return HttpResponse.json(
        { detail: { code: "wallet_entry_not_found", message: "No such wallet entry." } },
        { status: 404 },
      );
    }
    if (body.expected_version !== current.version) {
      return walletConflict(
        "wallet_version_conflict",
        "This wallet entry changed since you loaded it. Reload and retry.",
      );
    }
    const patched: MswWalletEntry = { ...current, version: current.version + 1 };
    for (const field of ["nickname", "last4", "statement_day", "opened_on", "points_balances"] as const) {
      if (field in body) (patched as Record<string, unknown>)[field] = body[field];
    }
    mswWallet = mswWallet.map((e) => (e.id === current.id ? patched : e));
    return HttpResponse.json(patched);
  }),

  http.delete("*/account/wallet/:entryId", ({ params }) => {
    const before = mswWallet.length;
    mswWallet = mswWallet.filter((e) => e.id !== params.entryId);
    if (mswWallet.length === before) {
      return HttpResponse.json(
        { detail: { code: "wallet_entry_not_found", message: "No such wallet entry." } },
        { status: 404 },
      );
    }
    return new HttpResponse(null, { status: 204 });
  }),

  // --- Spec 18 Case A: welcome-window status (honest "no approved offer" answer) ---
  http.post("*/account/wallet/:entryId/welcome-status", async ({ params, request }) => {
    const body = (await request.json()) as WelcomeStatusIn;
    const entry = mswWallet.find((e) => e.id === params.entryId);
    if (entry === undefined) {
      return welcomeError(404, "WALLET_ENTRY_NOT_FOUND", "No such wallet entry.");
    }
    const record = mswTrips.find((t) => t.summary.id === body.trip_id);
    if (record === undefined) return welcomeError(404, "TRIP_NOT_FOUND", "No such saved trip.");
    const revision = record.revisions.find((r) => r.revision === body.revision);
    if (revision === undefined) return welcomeError(404, "REVISION_NOT_FOUND", "No such revision.");
    const prior = body.prior_qualifying_spend_minor ?? null;
    const { lines, omittedZero } = mswCardLines(revision.report, entry.card_id);
    const gross = lines.reduce((sum, l) => sum + l.amount_minor, 0);
    const counted = lines.reduce((sum, l) => sum + l.counted_minor, 0);
    const costed = revision.report.costed_trip as
      | { booking_date?: string; home_currency?: string }
      | undefined;
    const plannedWallet = (revision.report.trip_spec as { wallet?: { card_ids?: string[] } } | undefined)
      ?.wallet?.card_ids;
    const duplicate = mswWallet.filter((e) => e.card_id === entry.card_id).length > 1;
    const status: WelcomeWindowReport = {
      card_id: entry.card_id,
      card_name: MSW_CARD_PRODUCTS.find((p) => p.card_id === entry.card_id)?.display_name ?? null,
      wallet_entry_id: entry.id,
      as_of: "2026-10-30",
      status: "unknown",
      limitations: [
        {
          code: "NO_APPROVED_OFFER",
          message:
            "No approved welcome-offer terms are available for this card, so the spend window and bonus cannot be computed.",
        },
        ...(entry.opened_on === null
          ? [
              {
                code: "OPENED_ON_UNKNOWN" as const,
                message:
                  "This card has no recorded open date. The window is not guessed from any other data.",
              },
            ]
          : []),
        ...(duplicate
          ? [
              {
                code: "DUPLICATE_CARD_ENTRIES" as const,
                message:
                  "More than one wallet entry holds this card product. The plan assigns spend to the product, not to one entry, so none of it is attributed here.",
              },
            ]
          : []),
        ...(plannedWallet !== undefined && !plannedWallet.includes(entry.card_id)
          ? [
              {
                code: "CARD_NOT_IN_PLANNED_WALLET" as const,
                message:
                  "This card was not in the wallet the stored plan was computed with, so the plan assigned it no spend.",
              },
            ]
          : []),
        ...(prior === null
          ? [
              {
                code: "PRIOR_SPEND_UNKNOWN" as const,
                message:
                  "Spend already made on this card in the window was not provided. It is not assumed to be zero, so the remaining spend cannot be stated.",
              },
            ]
          : []),
      ],
      opened_on: entry.opened_on,
      window_closes_on: null,
      days_remaining: null,
      offer: null,
      ineligible_offer_count: 0,
      min_spend_minor: null,
      currency: null,
      qualifying_spend_to_date_minor: prior,
      shortfall_minor: null,
      trip: {
        trip_id: record.summary.id,
        revision: revision.revision,
        revision_computed_at: revision.computed_at,
        trip_start_date: record.summary.start_date,
        trip_end_date: record.summary.end_date,
        plan_booking_date: costed?.booking_date ?? record.summary.start_date,
        currency: costed?.home_currency ?? "INR",
      },
      trip_assigned_spend_minor: gross,
      trip_counted_spend_minor: counted,
      conditional_trip_spend_minor: 0,
      shortfall_after_conditional_trip_minor: null,
      trip_alone_clears_minimum_if_conditions_hold: null,
      omitted_zero_amount_lines: omittedZero,
      lines,
      bonus: null,
      // Simplified: `as_of` is fixed and only the assumptions that apply with no offer
      // are listed; the real route also lists offer-dependent ones.
      assumptions: [
        "The report describes the assignments in the stored plan. It does not change them, re-rank them, or add the welcome bonus to any plan total.",
        "Payment timing is not observed. Spend is reported as conditional, never as confirmed qualifying.",
      ],
    };
    return HttpResponse.json(status);
  }),

  // --- A4 saved trips ---
  http.get("*/account/trips", () =>
    HttpResponse.json([...mswTrips].reverse().map((t) => t.summary)),
  ),

  http.post("*/account/trips", async ({ request }) => {
    const body = (await request.json()) as SaveTripIn;
    const fingerprint = JSON.stringify([body.session_id, body.title ?? null]);
    const prior = mswTripEvents.get(`save:${body.client_event_id}`);
    if (prior !== undefined) {
      return prior.fingerprint === fingerprint ? HttpResponse.json(prior.body, { status: 201 }) : eventReused();
    }
    const failure = sessionFailure(body.session_id);
    if (failure !== null) return failure;
    const existing = mswTrips.find((t) => t.sessionId === body.session_id);
    if (existing !== undefined) {
      return tripError(
        409,
        "SESSION_ALREADY_SAVED",
        "This plan is already saved. Add the current plan to that trip as a new revision.",
        { trip_id: existing.summary.id },
      );
    }
    if (mswTrips.length >= MSW_MAX_TRIPS) {
      return tripError(409, "TRIP_LIMIT_REACHED", "You have reached the maximum number of saved trips. Delete one to save another.");
    }
    mswTripSeq += 1;
    const id = `msw-trip-${mswTripSeq}`;
    const revision = mswRevision(1, mswReport());
    const record: MswTripRecord = {
      summary: {
        id,
        title: body.title ?? "DEL → SIN · 2026-11-01",
        origin_city: "DEL",
        destination_city: "SIN",
        start_date: "2026-11-01",
        end_date: "2026-11-05",
        created_at: "2026-10-24T12:00:00+00:00",
        revision_count: 1,
        latest_revision: 1,
        latest_computed_at: revision.computed_at,
      },
      revisions: [revision],
      sessionId: body.session_id,
    };
    mswTrips.push(record);
    const created = { trip: record.summary, revision };
    mswTripEvents.set(`save:${body.client_event_id}`, { fingerprint, body: created });
    return HttpResponse.json(created, { status: 201 });
  }),

  http.get("*/account/trips/:tripId", ({ params }) => {
    const record = mswTrips.find((t) => t.summary.id === params.tripId);
    return record === undefined ? tripNotFound() : HttpResponse.json(mswTripDetail(record));
  }),

  http.delete("*/account/trips/:tripId", ({ params, request }) => {
    const eventId = new URL(request.url).searchParams.get("client_event_id");
    const fingerprint = `delete:${String(params.tripId)}`;
    if (eventId !== null) {
      const prior = mswTripEvents.get(`delete:${eventId}`);
      if (prior !== undefined) {
        // A retried delete replays as 204 even though the trip is gone.
        return prior.fingerprint === fingerprint ? new HttpResponse(null, { status: 204 }) : eventReused();
      }
    }
    const before = mswTrips.length;
    mswTrips = mswTrips.filter((t) => t.summary.id !== params.tripId);
    if (mswTrips.length === before) return tripNotFound();
    if (eventId !== null) mswTripEvents.set(`delete:${eventId}`, { fingerprint, body: null });
    return new HttpResponse(null, { status: 204 });
  }),

  http.post("*/account/trips/:tripId/revisions", async ({ params, request }) => {
    const body = (await request.json()) as { session_id: string; client_event_id: string };
    const record = mswTrips.find((t) => t.summary.id === params.tripId);
    if (record === undefined) return tripNotFound();
    const fingerprint = JSON.stringify([record.summary.id, body.session_id]);
    const prior = mswTripEvents.get(`append:${body.client_event_id}`);
    if (prior !== undefined) {
      return prior.fingerprint === fingerprint ? HttpResponse.json(prior.body, { status: 201 }) : eventReused();
    }
    const failure = sessionFailure(body.session_id);
    if (failure !== null) return failure;
    if (body.session_id !== record.sessionId) {
      return tripError(409, "SESSION_NOT_ATTACHED", "That planning session is not the one this trip was saved from.");
    }
    if (record.revisions.length >= MSW_MAX_REVISIONS) {
      return tripError(409, "REVISION_LIMIT_REACHED", "This trip has reached its maximum number of revisions.");
    }
    const revision = mswRevision(record.revisions.length + 1, mswReport());
    record.revisions.push(revision);
    refreshSummary(record);
    mswTripEvents.set(`append:${body.client_event_id}`, { fingerprint, body: revision });
    return HttpResponse.json(revision, { status: 201 });
  }),

  http.get("*/account/trips/:tripId/revisions/:revision", ({ params }) => {
    const record = mswTrips.find((t) => t.summary.id === params.tripId);
    if (record === undefined) return tripNotFound();
    const found = record.revisions.find((r) => r.revision === Number(params.revision));
    return found === undefined
      ? tripError(404, "REVISION_NOT_FOUND", "No such revision.")
      : HttpResponse.json(found);
  }),

  http.post("*/account/trips/:tripId/reruns", async ({ params, request }) => {
    const body = (await request.json()) as { client_event_id: string };
    const record = mswTrips.find((t) => t.summary.id === params.tripId);
    if (record === undefined) return tripNotFound();
    const fingerprint = `rerun:${record.summary.id}`;
    const prior = mswRerunStarts.get(body.client_event_id);
    if (prior !== undefined) {
      return prior.fingerprint === fingerprint
        ? HttpResponse.json({ job_id: prior.jobId }, { status: 202 })
        : eventReused();
    }
    if (hasActiveRerun(record.summary.id)) {
      return tripError(409, "RERUN_IN_PROGRESS", "This trip is already being planned again. Wait for it to finish.");
    }
    if (record.revisions.length >= MSW_MAX_REVISIONS) {
      return tripError(409, "REVISION_LIMIT_REACHED", "This trip has reached its maximum number of revisions.");
    }
    const jobId = `msw-rerun-${mswReruns.size + 1}`;
    mswReruns.set(jobId, { tripId: record.summary.id, polls: 0, revision: null });
    mswRerunStarts.set(body.client_event_id, { fingerprint, jobId });
    return HttpResponse.json({ job_id: jobId }, { status: 202 });
  }),

  http.get("*/account/trips/:tripId/reruns/:jobId", ({ params }) => {
    const record = mswTrips.find((t) => t.summary.id === params.tripId);
    if (record === undefined) return tripNotFound();
    const jobId = String(params.jobId);
    const rerun = mswReruns.get(jobId);
    if (rerun === undefined || rerun.tripId !== record.summary.id) {
      return tripError(404, "RERUN_NOT_FOUND", "No such re-run.");
    }
    rerun.polls += 1;
    if (rerun.revision === null && rerun.polls >= 2) {
      // The first poll sees it running; the revision is appended once it completes.
      const revision = mswRevision(record.revisions.length + 1, mswReport());
      record.revisions.push(revision);
      refreshSummary(record);
      rerun.revision = revision.revision;
    }
    const status: RerunStatusOut =
      rerun.revision === null
        ? { job_id: jobId, status: "running", stage: "planning", revision: null, error: null }
        : { job_id: jobId, status: "complete", stage: "explaining", revision: rerun.revision, error: null };
    return HttpResponse.json(status);
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
  japanVisualReport: () => createJapanVisualReport(),
};
