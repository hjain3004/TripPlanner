import { z } from "zod";
import type { PlanJobStatus } from "./generated/types.gen";

const stageEnum = z.enum([
  "intake",
  "itinerary",
  "costing",
  "optimizing",
  "transfer",
  "critic",
  "explaining",
]);

const sectionStateEnum = z.enum(["fresh", "stale", "recomputed"]);

export const sectionFreshnessSchema = z.object({
  budget: sectionStateEnum.optional(),
  payment_strategy: sectionStateEnum.optional(),
  itinerary: sectionStateEnum.optional(),
  prose: sectionStateEnum.optional(),
  critic_verdict: sectionStateEnum.optional(),
  edit_count: z.number().int().optional(),
});

const jobErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  trace_id: z.string(),
});

const regionCapabilitySchema = z.object({
  region: z.string(),
  catalog_status: z.enum(["active", "absent", "provisioning", "stale"]),
  place_count: z.number().int(),
  budget_supported: z.boolean(),
  known_gaps: z.array(z.string()),
});

const priceScopeSchema = z.object({
  basis: z.enum(["sample_per_traveler_trip", "sample_nightly_stay", "party_total", "unknown"]),
  scope_verified: z.boolean(),
  travelers: z.number().int().positive().optional().nullable(),
  rooms: z.number().int().positive().optional().nullable(),
});

const inventoryQuoteSchema = z.object({
  domain: z.enum(["flight", "hotel"]),
  quote_id: z.string(),
  provider_id: z.string(),
  provider_quote_id: z.string().optional().nullable(),
  status: z.enum(["live", "cached", "estimated", "stale", "verify_required"]),
  needs_verification: z.boolean(),
  source_url: z.string().url().optional().nullable(),
  deep_link_url: z.string().url().optional().nullable(),
  attribution: z.string().optional().nullable(),
  retrieved_at: z.string(),
  expires_at: z.string().optional().nullable(),
  completeness: z.enum(["complete", "taxes_uncertain", "fees_uncertain", "partial"]),
  source_amount_minor: z.number().int().nonnegative(),
  source_currency: z.string().length(3),
  converted_amount_minor: z.number().int().nonnegative().optional().nullable(),
  price_scope: priceScopeSchema,
  selected: z.boolean(),
  alternative: z.boolean(),
  limitations: z.array(z.string()),
}).superRefine((quote, ctx) => {
  if (quote.provider_id.startsWith("sample_") && quote.status === "live") {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: "Sample evidence cannot claim live status" });
  }
});

const travelInventorySchema = z.object({
  flight: inventoryQuoteSchema.optional().nullable(),
  hotel: inventoryQuoteSchema.optional().nullable(),
  alternatives: z.array(inventoryQuoteSchema).optional(),
  limitations: z.array(z.string()).optional(),
  diagnostics: z.array(z.object({ code: z.string(), domain: z.enum(["flight", "hotel", "general"]), message: z.string(), provider_id: z.string().optional().nullable() })).optional(),
  reference_only_awards: z.boolean().optional(),
});

const finalReportSchema = z.object({
  trace_id: z.string(),
  summary: z.string().optional(),
  itinerary_overview: z.string().optional(),
  payment_overview: z.string().optional(),
  footer: z.string().optional(),
  caveats: z.array(z.string()).optional(),
  assumptions: z.array(z.string()).optional(),
  provenance_warnings: z.array(z.string()).optional(),
  booking_checklist: z.array(z.string()).optional(),
  confidence: z.number(),
  status: z.enum(["needs_clarification", "ok", "error"]).optional(),
  region_capability: regionCapabilitySchema.nullable().optional(),
  freshness: sectionFreshnessSchema.optional(),
  travel_inventory: travelInventorySchema.optional().nullable(),
}).passthrough();

export const planJobStatusSchema = z.object({
  job_id: z.string(),
  status: z.enum([
    "queued",
    "running",
    "needs_clarification",
    "complete",
    "failed",
  ]),
  stage: stageEnum.nullable().optional(),
  stage_index: z.number().int().nullable().optional(),
  stages_total: z.number().int().optional(),
  unresolved: z.array(z.string()).nullable().optional(),
  report: finalReportSchema.nullable().optional(),
  error: jobErrorSchema.nullable().optional(),
}).refine(
  (data) => {
    if (data.status === "complete") return data.report != null;
    return true;
  },
  { message: "complete status requires report" }
).refine(
  (data) => {
    if (data.status === "needs_clarification") {
      return data.unresolved != null && data.unresolved.length > 0;
    }
    return true;
  },
  { message: "needs_clarification requires unresolved" }
);

export function parsePlanJobStatus(raw: unknown): PlanJobStatus {
  return planJobStatusSchema.parse(raw) as PlanJobStatus;
}
