import { describe, expect, it } from "vitest";
import { planJobStatusSchema } from "../src/lib/api/schemas";
import { japanVisualFixture } from "../src/mocks/japan-visual-fixture";

function wrappedFixture() {
  return {
    job_id: "test-japan-visual",
    status: "complete",
    stage: null,
    stage_index: null,
    stages_total: 6,
    report: japanVisualFixture.report,
  };
}

describe("Japan visual fixture", () => {
  it("wraps an API-valid report without extending FinalReport", () => {
    expect(japanVisualFixture.id).toBe("japan-golden");
    expect(japanVisualFixture.primaryCountryCode).toBe("JP");
    expect(planJobStatusSchema.safeParse(wrappedFixture()).success).toBe(true);
    expect("primaryCountryCode" in japanVisualFixture.report).toBe(false);
  });

  it("marks invented inventory as sample evidence needing verification where supported", () => {
    const { flights_pick, hotel_pick, transfer_advice } = japanVisualFixture.report;

    expect(flights_pick?.provenance.verified_by).toBe("frontend_sample");
    expect(flights_pick?.provenance.needs_verification).toBe(true);
    expect(flights_pick?.provenance.notes).toContain("sample visual fixture");

    expect(hotel_pick?.provenance.verified_by).toBe("frontend_sample");
    expect(hotel_pick?.provenance.needs_verification).toBe(true);
    expect(hotel_pick?.provenance.notes).toContain("sample visual fixture");

    const award = transfer_advice?.plans[0]?.award;
    expect(award?.provenance.verified_by).toBe("frontend_sample");
    expect(award?.provenance.needs_verification).toBe(true);
    expect(award?.provenance.notes).toContain("sample visual fixture");
  });
});
