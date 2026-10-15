import type { PreferencePatch, TravelPreferenceProfile } from "@/lib/api";
import type {
  PreferenceSource,
  PreferenceValue,
  ProfilePreferenceField,
  ProfilePreferenceGroup,
} from "./types";

type ApiLeaf = {
  value?: unknown;
  source?: string;
  updated_at?: string;
} | null | undefined;

type FieldSpec = {
  id: string;
  label: string;
  type: ProfilePreferenceField["type"];
  options?: readonly string[];
  description?: string;
  list?: boolean;
};

const NO_PREFERENCE = "No preference — choose for me";
const BOOL_OPTIONS = [NO_PREFERENCE, "Yes", "No"] as const;

function leaf<T>(value: T | null | undefined, now: string): { value: T; source: "user_profile_edit"; updated_at: string } | null {
  if (value === null || value === undefined || value === "") return null;
  if (Array.isArray(value) && value.length === 0) return null;
  return { value: value as T, source: "user_profile_edit", updated_at: now };
}

function listValue(value: unknown): string[] {
  if (Array.isArray(value)) return value.flatMap((item) => String(item).split(",")).map((item) => item.trim()).filter(Boolean);
  return String(value ?? "").split(",").map((item) => item.trim()).filter(Boolean);
}

function optionalNumber(value: unknown): number | null {
  if (value === "" || value === null || value === undefined) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function optionalBoolean(value: unknown): boolean | null {
  if (value === "Yes" || value === true) return true;
  if (value === "No" || value === false) return false;
  return null;
}

function optionValue<M extends Record<string, string>>(value: unknown, map: M): M[keyof M] | null {
  const normalized = String(value ?? "");
  if (!normalized || normalized === NO_PREFERENCE || normalized === "Not set") return null;
  return (map[normalized] ?? normalized.toLowerCase().replaceAll(" ", "_")) as M[keyof M];
}

const GROUP_SPECS: readonly {
  id: string;
  title: string;
  description: string;
  section: keyof TravelPreferenceProfile;
  fields: readonly FieldSpec[];
}[] = [
  {
    id: "flight",
    title: "Flights",
    description: "Cabin, schedule, baggage, and airport preferences.",
    section: "flight",
    fields: [
      { id: "cabin", label: "Preferred cabin", type: "select", options: [NO_PREFERENCE, "Economy", "Premium economy", "Business", "First"] },
      { id: "max_stops", label: "Maximum stops", type: "number", description: "Leave blank when you are flexible." },
      { id: "schedule", label: "Preferred departure time", type: "select", options: [NO_PREFERENCE, "Morning", "Afternoon", "Evening", "Overnight"] },
      { id: "checked_baggage", label: "Checked baggage", type: "select", options: BOOL_OPTIONS },
      { id: "airport_flexible", label: "Flexible airports", type: "select", options: BOOL_OPTIONS },
      { id: "seat", label: "Preferred seat", type: "select", options: [NO_PREFERENCE, "Aisle", "Window", "Middle"] },
    ],
  },
  {
    id: "stay",
    title: "Stays",
    description: "The lodging style, location, room, and loyalty choices to carry between trips.",
    section: "stay",
    fields: [
      { id: "lodging_styles", label: "Lodging styles", type: "text", list: true, description: "Separate multiple choices with commas." },
      { id: "location_priorities", label: "Location priorities", type: "text", list: true, description: "Separate multiple choices with commas." },
      { id: "room_needs", label: "Room needs", type: "text", list: true, description: "Separate multiple choices with commas." },
      { id: "location_price_tradeoff", label: "Location versus price", type: "select", options: [NO_PREFERENCE, "Location first", "Price first", "Balanced"] },
      { id: "loyalty_programs", label: "Hotel loyalty programs", type: "text", list: true, description: "Separate multiple programs with commas." },
    ],
  },
  {
    id: "rhythm",
    title: "Daily rhythm",
    description: "How full, early, or relaxed your days should feel.",
    section: "rhythm",
    fields: [
      { id: "pace", label: "Typical pace", type: "select", options: [NO_PREFERENCE, "Relaxed", "Moderate", "Packed"] },
      { id: "day_start", label: "Day start", type: "select", options: [NO_PREFERENCE, "Early", "Normal", "Late"] },
      { id: "evening_style", label: "Evening style", type: "select", options: [NO_PREFERENCE, "Quiet", "Flexible", "Late"] },
      { id: "downtime_minutes", label: "Downtime per day", type: "number" },
      { id: "transit_tolerance_minutes", label: "Transit tolerance", type: "number" },
      { id: "day_trip_appetite", label: "Day-trip appetite", type: "select", options: [NO_PREFERENCE, "None", "One", "Multiple"] },
    ],
  },
  {
    id: "experiences",
    title: "Experiences & food",
    description: "Interests and the balance between iconic highlights and local discoveries.",
    section: "experiences",
    fields: [
      { id: "interests", label: "Interests", type: "text", list: true, description: "Separate multiple interests with commas." },
      { id: "food_interests", label: "Food interests", type: "text", list: true, description: "Separate multiple interests with commas." },
      { id: "iconic_local_balance", label: "Iconic versus local", type: "select", options: [NO_PREFERENCE, "Iconic", "Balanced", "Local"] },
      { id: "nightlife", label: "Nightlife", type: "select", options: BOOL_OPTIONS },
      { id: "shopping", label: "Shopping", type: "select", options: BOOL_OPTIONS },
    ],
  },
  {
    id: "constraints",
    title: "Accessibility & constraints",
    description: "Needs that should be visible before an itinerary is built.",
    section: "constraints",
    fields: [
      { id: "dietary", label: "Dietary needs", type: "text", list: true, description: "Separate multiple needs with commas." },
      { id: "accessibility", label: "Accessibility needs", type: "text", list: true, description: "Separate multiple needs with commas." },
    ],
  },
  {
    id: "optimization",
    title: "Rewards objective",
    description: "The trade-off the planner should make when comparing cash and points.",
    section: "optimization",
    fields: [
      { id: "objective", label: "Planning objective", type: "select", options: [NO_PREFERENCE, "Lowest cash", "Highest value", "Convenience", "Balanced"] },
      { id: "points_priority", label: "Points priority", type: "select", options: [NO_PREFERENCE, "Save points", "Use points", "Best value"] },
    ],
  },
] as const;

function sourceFor(leaf: ApiLeaf): PreferenceSource {
  if (!leaf) return "unset";
  if (leaf.source === "user_profile_edit") return "profile";
  if (leaf.source === "user_confirmed_from_trip") return "confirmed";
  return "unset";
}

function displayValue(leaf: ApiLeaf): PreferenceValue {
  if (!leaf || leaf.value === null || leaf.value === undefined) return "Not set";
  if (Array.isArray(leaf.value)) return leaf.value.length ? leaf.value.join(", ") : "Not set";
  if (typeof leaf.value === "boolean") return leaf.value ? "Yes" : "No";
  return String(leaf.value);
}

function groupSource(fields: readonly ProfilePreferenceField[]): PreferenceSource {
  const sources = new Set(fields.map((field) => field.source ?? "unset").filter((source) => source !== "unset"));
  if (sources.size > 1) return "mixed";
  return sources.values().next().value ?? "unset";
}

function groupUpdatedAt(fields: readonly ProfilePreferenceField[]): string | undefined {
  const dates = fields
    .map((field) => field.updatedAt)
    .filter((value): value is string => Boolean(value))
    .sort();
  return dates.at(-1);
}

export function projectTravelPreferences(profile: TravelPreferenceProfile): ProfilePreferenceGroup[] {
  return GROUP_SPECS.map((spec) => {
    const section = (profile[spec.section] ?? {}) as Record<string, ApiLeaf>;
    const fields = spec.fields.map((field): ProfilePreferenceField => {
      const leaf = section[field.id];
      return {
        id: field.id,
        label: field.label,
        value: displayValue(leaf),
        type: field.type,
        options: field.options,
        description: field.description,
        source: sourceFor(leaf),
        updatedAt: leaf?.updated_at,
      };
    });
    const hasValue = fields.some((field) => field.source !== "unset");
    return {
      id: spec.id,
      title: spec.title,
      description: spec.description,
      fields,
      source: groupSource(fields),
      updateStatus: hasValue ? "saved" : "not-set",
      updatedAt: groupUpdatedAt(fields),
      canRemove: true,
    };
  });
}

export function editablePreferenceValue(field: ProfilePreferenceField): PreferenceValue {
  return field.source === "unset" ? "" : field.value;
}

export function buildPreferencePatch(groupId: string, values: Record<string, PreferenceValue>, now: string): PreferencePatch {
  const v = (id: string) => values[id];
  if (groupId === "flight") return { flight: {
    cabin: leaf(optionValue(v("cabin"), { Economy: "economy", "Premium economy": "premium_economy", Business: "business", First: "first" }), now),
    max_stops: leaf(optionalNumber(v("max_stops")), now),
    schedule: leaf(optionValue(v("schedule"), { Morning: "morning", Afternoon: "afternoon", Evening: "evening", Overnight: "overnight" }) ?? "no_preference", now),
    checked_baggage: leaf(optionalBoolean(v("checked_baggage")), now),
    airport_flexible: leaf(optionalBoolean(v("airport_flexible")), now),
    seat: leaf(optionValue(v("seat"), { Aisle: "aisle", Window: "window", Middle: "middle" }) ?? "no_preference", now),
  } as unknown as PreferencePatch["flight"] };
  if (groupId === "stay") return { stay: {
    lodging_styles: leaf(listValue(v("lodging_styles")), now), location_priorities: leaf(listValue(v("location_priorities")), now), room_needs: leaf(listValue(v("room_needs")), now),
    location_price_tradeoff: leaf(optionValue(v("location_price_tradeoff"), { "Location first": "location", "Price first": "price", Balanced: "balanced" }), now), loyalty_programs: leaf(listValue(v("loyalty_programs")), now),
  } as unknown as PreferencePatch["stay"] };
  if (groupId === "rhythm") return { rhythm: {
    pace: leaf(optionValue(v("pace"), { Relaxed: "relaxed", Moderate: "moderate", Packed: "packed" }), now), day_start: leaf(optionValue(v("day_start"), { Early: "early", Normal: "normal", Late: "late" }), now), evening_style: leaf(optionValue(v("evening_style"), { Quiet: "quiet", Flexible: "flexible", Late: "late" }), now),
    downtime_minutes: leaf(optionalNumber(v("downtime_minutes")), now), transit_tolerance_minutes: leaf(optionalNumber(v("transit_tolerance_minutes")), now), day_trip_appetite: leaf(optionValue(v("day_trip_appetite"), { None: "none", One: "one", Multiple: "multiple" }), now),
  } as unknown as PreferencePatch["rhythm"] };
  if (groupId === "experiences") return { experiences: {
    interests: leaf(listValue(v("interests")), now), food_interests: leaf(listValue(v("food_interests")), now), iconic_local_balance: leaf(optionValue(v("iconic_local_balance"), { Iconic: "iconic", Balanced: "balanced", Local: "local" }), now), nightlife: leaf(optionalBoolean(v("nightlife")), now), shopping: leaf(optionalBoolean(v("shopping")), now),
  } as unknown as PreferencePatch["experiences"] };
  if (groupId === "constraints") return { constraints: { dietary: leaf(listValue(v("dietary")), now), accessibility: leaf(listValue(v("accessibility")), now) } as unknown as PreferencePatch["constraints"] };
  return { optimization: {
    objective: leaf(optionValue(v("objective"), { "Lowest cash": "lowest_cash", "Highest value": "highest_value", Convenience: "convenience", Balanced: "balanced" }), now), points_priority: leaf(optionValue(v("points_priority"), { "Save points": "save_points", "Use points": "use_points", "Best value": "best_value" }), now),
  } as unknown as PreferencePatch["optimization"] };
}

export function emptyPreferencePatch(groupId: string): PreferencePatch {
  if (groupId === "flight") return { flight: { cabin: null, max_stops: null, schedule: null, checked_baggage: null, airport_flexible: null, seat: null } };
  if (groupId === "stay") return { stay: { lodging_styles: null, location_priorities: null, room_needs: null, location_price_tradeoff: null, loyalty_programs: null } };
  if (groupId === "rhythm") return { rhythm: { pace: null, day_start: null, evening_style: null, downtime_minutes: null, transit_tolerance_minutes: null, day_trip_appetite: null } };
  if (groupId === "experiences") return { experiences: { interests: null, food_interests: null, iconic_local_balance: null, nightlife: null, shopping: null } };
  if (groupId === "constraints") return { constraints: { dietary: null, accessibility: null } };
  return { optimization: { objective: null, points_priority: null } };
}

export const profileGroupSpecs = GROUP_SPECS;
