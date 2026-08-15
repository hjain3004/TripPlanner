import { z } from "zod";
import type { PlanJobStatus } from "./types.gen";

const stageEnum = z.enum([
  "intake",
  "itinerary",
  "costing",
  "optimizing",
  "transfer",
  "critic",
  "explaining",
]);

const jobErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  trace_id: z.string(),
});

const regionCapabilitySchema = z.object({
  region: z.string(),
  catalog_status: z.enum(["active", "absent", "stale"]),
  place_count: z.number().int(),
  budget_supported: z.boolean(),
  known_gaps: z.array(z.string()),
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
