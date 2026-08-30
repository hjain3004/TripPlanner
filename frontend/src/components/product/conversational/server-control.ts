import type { QuestionOut } from "@/lib/api";
import type { ControlDefinition } from "./conversational-types";

/**
 * Convert the generated server control discriminant to the presentation
 * discriminant. Options and fields are intentionally copied from the server;
 * this adapter contains no question vocabulary of its own.
 */
export function controlFromServer(
  control: QuestionOut["control"],
  defaultAdults = 1,
): ControlDefinition {
  switch (control.type) {
    case "trip_essentials":
      return { kind: "trip-essentials", fields: control.fields, optionalFields: control.optional_fields };
    case "hard_constraints":
      return { kind: "hard-constraints", fields: control.fields };
    case "text":
      return { kind: "text", maxLength: 1000 };
    case "purpose_party":
      return {
        kind: "party",
        options: control.options.map(({ value, label }) => ({ value, label })),
        allowNoPreference: control.allow_skip,
        defaultAdults: Math.max(1, defaultAdults),
      };
    default:
      return {
        kind: "single-select",
        options: control.options.map(({ value, label }) => ({ value, label })),
        allowNoPreference: control.allow_skip,
      };
  }
}
