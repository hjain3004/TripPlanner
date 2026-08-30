import type { PreferenceSource, PreferenceUpdateStatus } from "./types";

const SOURCE_LABELS: Record<PreferenceSource, string> = {
  profile: "Saved preference",
  trip: "This trip only",
  confirmed: "Saved from a trip",
  imported: "Imported from account",
  default: "TripPlanner default",
  unset: "Not set",
  mixed: "Mixed sources",
};

const STATUS_LABELS: Record<PreferenceUpdateStatus, string> = {
  saved: "Saved",
  pending: "Changes pending",
  "needs-review": "Review suggested",
  "not-set": "Not set",
};

export function getPreferenceSourceLabel(source: PreferenceSource): string {
  return SOURCE_LABELS[source];
}

export function getPreferenceStatusLabel(status: PreferenceUpdateStatus): string {
  return STATUS_LABELS[status];
}
