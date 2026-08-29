import type { PreferenceSource, PreferenceUpdateStatus } from "./types";

const SOURCE_LABELS: Record<PreferenceSource, string> = {
  profile: "Saved preference",
  trip: "This trip only",
  imported: "Imported from account",
  default: "TripPlanner default",
};

const STATUS_LABELS: Record<PreferenceUpdateStatus, string> = {
  saved: "Saved",
  pending: "Changes pending",
  "needs-review": "Review suggested",
};

export function getPreferenceSourceLabel(source: PreferenceSource): string {
  return SOURCE_LABELS[source];
}

export function getPreferenceStatusLabel(status: PreferenceUpdateStatus): string {
  return STATUS_LABELS[status];
}
