import type { AnswerRequest, QuestionOut } from "@/lib/api";
import type { AnswerValue } from "./conversational-types";

type Payload = NonNullable<AnswerRequest["payload"]>;

export function primaryAnswerField(questionId: string): string {
  switch (questionId) {
    case "budget_and_objective": return "objective";
    case "flight_preferences": return "cabin";
    case "stay_preferences": return "location_price_tradeoff";
    case "daily_rhythm": return "pace";
    case "experiences_and_food": return "iconic_local_balance";
    default: return "detail";
  }
}

export function valueFromPayload(question: QuestionOut, payload: Payload): AnswerValue {
  if (["trip_essentials", "purpose_party", "hard_constraints"].includes(question.control.type)) return payload as AnswerValue;
  const fields = payload as unknown as Record<string, unknown>;
  const value = fields[primaryAnswerField(question.id)];
  return typeof value === "string" ? value : null;
}

/** Change only the displayed field; keep every other confirmed/proposed field. */
export function payloadForValue(questionId: string, value: AnswerValue, base?: AnswerRequest["payload"]): AnswerRequest["payload"] {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) return value as Payload;
  const text = typeof value === "string" ? value : "";
  if (base) return { ...base, [primaryAnswerField(questionId)]: text } as Payload;
  switch (questionId) {
    case "purpose_and_party": return { purpose: text || "leisure", adults: 1, children_ages: [] } as Payload;
    case "budget_and_objective": return { budget_minor: null, currency: "INR", travel_style: "balanced", objective: text || "balanced", points_priority: "best_value" } as Payload;
    case "flight_preferences": return { cabin: text || "no_preference", max_stops: null, schedule: "no_preference", checked_baggage: null, airport_flexible: null, seat: "no_preference" } as Payload;
    case "stay_preferences": return { lodging_styles: [], neighborhood_priorities: [], room_count: 1, room_needs: [], location_price_tradeoff: text || "no_preference" } as Payload;
    case "daily_rhythm": return { pace: text || "no_preference", day_start: "no_preference", evening_style: "no_preference", downtime_minutes: null, transit_tolerance_minutes: null, day_trip_appetite: "no_preference" } as Payload;
    case "experiences_and_food": return { interests: text && text !== "no_preference" ? [text] : [], food_interests: [], iconic_local_balance: text || "no_preference", nightlife: null, shopping: null } as Payload;
    default: return { detail: text };
  }
}

const CORE_IDS = ["trip_essentials", "purpose_and_party", "budget_and_objective", "flight_preferences", "stay_preferences", "daily_rhythm", "experiences_and_food", "hard_constraints"] as const;
const INTERPRETABLE_IDS = new Set(["flight_preferences", "stay_preferences", "daily_rhythm", "experiences_and_food", "hard_constraints", "celebration_details", "children_needs", "mobility_details", "points_strategy", "flight_tradeoff", "hotel_tradeoff", "food_depth"]);
export function supportsInterpretation(questionId: string): boolean { return INTERPRETABLE_IDS.has(questionId); }
export function interpretationLimit(calls: number, answers: Partial<Record<typeof CORE_IDS[number], unknown>>): string | undefined {
  if (calls >= 2) return "The interview assistance limit has been reached. You can still use the answer controls.";
  if (calls >= 1 && CORE_IDS.some((id) => !answers[id])) return "The remaining assistance call is reserved for your trip review.";
  return undefined;
}
export function answerTitle(id: string): string { return id.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }
