export type PreferenceSource = "profile" | "trip" | "imported" | "default";
export type PreferenceUpdateStatus = "saved" | "pending" | "needs-review";
export type PreferenceValue = string | number;
export type PreferenceFieldType = "text" | "number" | "select";

export interface ProfilePreferenceField {
  id: string;
  label: string;
  value: PreferenceValue;
  type: PreferenceFieldType;
  options?: readonly string[];
  description?: string;
  source?: PreferenceSource;
}

export interface ProfilePreferenceGroup {
  id: string;
  title: string;
  description: string;
  fields: readonly ProfilePreferenceField[];
  source: PreferenceSource;
  updateStatus: PreferenceUpdateStatus;
  updatedAt?: string;
  canRemove?: boolean;
}

export type PreferenceDraft = Record<string, PreferenceValue>;

export interface ProfilePreferencesHandlers {
  onSave: (groupId: string, values: PreferenceDraft) => void;
  onReset: (groupId: string) => void;
  onRemove: (groupId: string) => void;
}
