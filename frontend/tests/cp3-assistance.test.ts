import { describe, expect, it } from "vitest";
import type { AnswerRequest, QuestionOut } from "../src/lib/api/generated/types.gen";
import { interpretationLimit, payloadForValue, supportsInterpretation, valueFromPayload } from "../src/components/product/conversational/answer-payload";

const question: QuestionOut = { id: "flight_preferences", prompt: "Cabin?", phase: "core", answer_kind: "flight", required: false, allow_delegate: true, control: { type: "flight", options: [{ value: "business", label: "Business" }], allow_skip: true } };
const payload: AnswerRequest["payload"] = { cabin: "business", max_stops: 0, schedule: "morning", checked_baggage: true, airport_flexible: false, seat: "aisle" };

describe("CP3 candidate and assistance boundaries", () => {
  it("round-trips a full candidate through the scalar control without erasing fields", () => {
    const value = valueFromPayload(question, payload!);
    expect(value).toBe("business");
    expect(payloadForValue(question.id, value, payload)).toEqual(payload);
    expect(payloadForValue(question.id, "economy", payload)).toEqual({ ...payload, cabin: "economy" });
    expect(payload).toMatchObject({ cabin: "business", seat: "aisle" });
  });
  it("preserves arrays, nulls and boolean candidates across a stay control edit", () => {
    const stay = { lodging_styles: ["boutique"], neighborhood_priorities: ["quiet"], room_count: 1, room_needs: ["twin beds"], location_price_tradeoff: "location" } as AnswerRequest["payload"];
    expect(payloadForValue("stay_preferences", "price", stay)).toEqual({ ...stay, location_price_tradeoff: "price" });
    const rhythm = { pace: "relaxed", day_start: "late", evening_style: "quiet", downtime_minutes: null, transit_tolerance_minutes: null, day_trip_appetite: "no_preference" } as AnswerRequest["payload"];
    expect(payloadForValue("daily_rhythm", "packed", rhythm)).toEqual({ ...rhythm, pace: "packed" });
  });
  it("reserves the second call until every core decision has been answered, including delegated answers", () => {
    const answered = Object.fromEntries(["trip_essentials", "purpose_and_party", "budget_and_objective", "flight_preferences", "stay_preferences", "daily_rhythm", "experiences_and_food", "hard_constraints"].map((id) => [id, { delegated: true }]));
    expect(interpretationLimit(0, {})).toBeUndefined();
    expect(interpretationLimit(1, {})).toContain("reserved");
    expect(interpretationLimit(1, answered)).toBeUndefined();
    delete answered.hard_constraints;
    expect(interpretationLimit(1, answered)).toContain("reserved");
    expect(interpretationLimit(2, answered)).toContain("limit");
  });
  it("excludes essential, budget and party facts while allowing catalog detail interpretation", () => {
    for (const id of ["trip_essentials", "budget_and_objective", "purpose_and_party", "invented_question"]) expect(supportsInterpretation(id)).toBe(false);
    for (const id of ["flight_preferences", "stay_preferences", "hard_constraints", "food_depth", "children_needs"]) expect(supportsInterpretation(id)).toBe(true);
  });
});
