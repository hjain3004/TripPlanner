import type { FinalReport, Provenance } from "@/lib/api";

const sampleProvenance: Provenance = {
  source_url: "",
  source_type: "manual_curation",
  last_verified: "2026-08-11",
  verified_by: "frontend_sample",
  needs_verification: true,
  confidence: 0.62,
  notes: "sample visual fixture; not live inventory or provider-verified availability",
};

const japanVisualReport = {
  trace_id: "frontend-japan-visual-001",
  status: "ok",
  trip_spec: {
    home_country: "IN",
    origin_city: "DEL",
    destination_city: "TYO",
    start_date: "2026-11-03",
    end_date: "2026-11-08",
    travelers: 2,
    budget_minor: 32000000,
    budget_currency: "INR",
    style: "balanced",
    interests: ["food", "temples", "rail"],
    wallet: {
      card_ids: ["hdfc-infinia", "amex-platinum-sample"],
      points_balances: { "voyager-prime": 210000 },
    },
  },
  hotel_area: {
    id: "tokyo-ueno-asakusa-sample",
    name: "Ueno / Asakusa",
    reason: "Sample area chosen for rail access, museums, and old Tokyo walking routes.",
  },
  flights_pick: {
    id: "sample-flight-del-tyo-001",
    origin: "DEL",
    destination: "TYO",
    airline: "Sample carrier",
    stops: 1,
    price_minor: 18000000,
    currency: "INR",
    cabin: "economy",
    purchasable_channels: ["direct_airline", "ota_generic"],
    notes: "Frontend visual fixture only; verify cash and award availability before booking.",
    provenance: sampleProvenance,
  },
  hotel_pick: {
    id: "sample-hotel-tokyo-001",
    city: "Tokyo",
    name: "Sample ryokan-inspired hotel",
    area: "Ueno / Asakusa",
    stars: 4,
    price_per_night_minor: 1960000,
    currency: "INR",
    style: "balanced",
    purchasable_channels: ["direct_hotel", "ota_generic"],
    provenance: sampleProvenance,
  },
  costed_trip: {
    booking_date: "2026-08-11",
    trip_start_date: "2026-11-03",
    lines: [
      {
        id: "flight_001",
        label: "DEL→TYO sample flights (2 pax)",
        category: "flights",
        amount_minor: 18000000,
        currency: "INR",
        available_channels: ["direct_airline", "ota_generic"],
        merchant_hint: "sample carrier",
      },
      {
        id: "hotel_001",
        label: "Tokyo sample hotel 5 nights",
        category: "hotels",
        amount_minor: 9800000,
        currency: "INR",
        available_channels: ["direct_hotel", "ota_generic"],
        merchant_hint: "sample hotel",
      },
    ],
  },
  optimizer_result: {
    assignments: [],
    gross_minor: 27800000,
    discounts_minor: 400000,
    rewards_value_minor: 2200000,
    forex_fees_minor: 0,
    effective_cost_minor: 25200000,
    cash_outlay_now_minor: 25200000,
    deferred_value_minor: 2200000,
    savings_pct_bp: 935,
    cap_pools_final: {},
    confidence: 0.72,
  },
  budget_totals: {
    gross_minor: 27800000,
    discounts_minor: 400000,
    rewards_value_minor: 2200000,
    forex_fees_minor: 0,
    effective_cost_minor: 25200000,
    cash_outlay_now_minor: 25200000,
    deferred_value_minor: 2200000,
    savings_pct_bp: 935,
  },
  payment_strategy: [
    {
      line_id: "flight_001",
      label: "DEL→TYO sample flights (2 pax)",
      card_id: "hdfc-infinia",
      channel: "direct_airline",
      offers: ["sample rewards valuation"],
      action_sentence: "Sample only: compare direct-airline cash booking against the listed transfer path before acting.",
    },
    {
      line_id: "hotel_001",
      label: "Tokyo sample hotel 5 nights",
      card_id: "amex-platinum-sample",
      channel: "direct_hotel",
      offers: ["sample hotel credit placeholder"],
      action_sentence: "Sample only: verify hotel rate, taxes, and card benefit eligibility before booking.",
    },
  ],
  transfer_advice: {
    recommendation: {
      kind: "REDEEM",
      plan_id: "jp_sample_transfer_001",
      reason: "Sample transfer path illustrates pointmaxxing flow; verify award space before transferring.",
    },
    plans: [
      {
        id: "jp_sample_transfer_001",
        travelers: 2,
        points_consumed: 150000,
        source_currency: "Voyager Prime",
        existing_miles_used: 0,
        leftover_miles: 60000,
        total_fees_minor: 720000,
        value_per_point_micro: 1800,
        effective_redemption_cost_minor: 720000,
        savings_vs_cash_minor: 18000000,
        dominated: false,
        award: {
          id: "sample-award-del-tyo-001",
          program_id: "sample-sakura-miles",
          origin: "DEL",
          destination: "TYO",
          cabin: "economy",
          trip_type: "round_trip",
          miles_cost: 150000,
          fees_minor: 720000,
          fees_currency: "INR",
          operating_airline_hint: "Sample carrier",
          availability_note: "Sample award shape only; no live seat availability checked.",
          provenance: sampleProvenance,
        },
        steps: [
          {
            from_id: "voyager-prime",
            to_id: "sample-sakura-miles",
            amount_source: 150000,
            amount_dest: 150000,
            bonus_applied: null,
            transfer_time_hours_typical: 24,
            transfer_time_hours_max: 72,
          },
        ],
        checklist_steps: [
          "Verify award availability before transferring points.",
          "Confirm transfer ratio and timing in the issuer portal.",
          "Reprice cash flights and hotel rates before booking.",
        ],
        provenance_flags: ["sample_visual_fixture", "needs_verification"],
        explanation: [
          "This fixture demonstrates a source → partner → redemption chain without claiming live inventory.",
        ],
      },
    ],
    infeasible: [],
  },
  itinerary: {
    hotel_area_id: "tokyo-ueno-asakusa-sample",
    itinerary_quality: "llm",
    notes: ["Frontend visual fixture · sample data · verify all availability before action."],
    days: [
      { date: "2026-11-03", items: [{ poi_id: "sample-ueno-arrival", start_hint: "evening" }] },
      { date: "2026-11-04", items: [{ poi_id: "sample-asakusa-walk", start_hint: "morning" }] },
      { date: "2026-11-05", items: [{ poi_id: "sample-yanaka", start_hint: "afternoon" }] },
      { date: "2026-11-06", items: [{ poi_id: "sample-hakone-day", start_hint: "morning" }] },
      { date: "2026-11-07", items: [{ poi_id: "sample-ginza-food", start_hint: "evening" }] },
    ],
  },
  summary: "Japan results preview built from frontend sample evidence.",
  itinerary_overview: "A sample Tokyo-first route with old-city walks, rail access, and one day-trip slot.",
  payment_overview: "Sample payment strategy only; no live bank offer, flight, hotel, or award search was performed.",
  booking_checklist: [
    "Verify award availability before transferring points.",
    "Verify hotel rates and cancellation rules.",
    "Reconfirm every sample price before booking.",
  ],
  assumptions: [
    "Frontend visual fixture · sample data.",
    "No provider inventory, account synchronization, or live award availability was queried.",
  ],
  provenance_warnings: [
    "Sample Japan inventory is manual visual evidence and needs verification.",
    "Transfer path is illustrative; verify transfer partner rules before action.",
  ],
  confidence: 0.72,
  caveats: [
    "Do not transfer points or book from this preview.",
    "This preview exists to validate UI composition only.",
  ],
  footer: "Frontend visual fixture · sample data · verify before booking or transferring points.",
} satisfies FinalReport;

export type DestinationVisualFixture = {
  id: "japan-golden";
  primaryCountryCode: "JP";
  report: FinalReport;
};

export const japanVisualFixture: DestinationVisualFixture = {
  id: "japan-golden",
  primaryCountryCode: "JP",
  report: japanVisualReport,
};

export function createJapanVisualReport(): FinalReport {
  return structuredClone(japanVisualFixture.report);
}
