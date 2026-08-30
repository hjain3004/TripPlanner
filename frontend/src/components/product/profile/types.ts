export type PreferenceSource = "profile" | "trip" | "confirmed" | "imported" | "default" | "unset" | "mixed";
export type PreferenceUpdateStatus = "saved" | "pending" | "needs-review" | "not-set";
export type PreferenceValue = string | number | boolean | string[];
export type PreferenceFieldType = "text" | "number" | "select";

export interface ProfilePreferenceField {
  id: string;
  label: string;
  value: PreferenceValue;
  type: PreferenceFieldType;
  options?: readonly string[];
  description?: string;
  source?: PreferenceSource;
  updatedAt?: string;
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
  onSave: (groupId: string, values: PreferenceDraft) => boolean | Promise<boolean>;
  onReset: (groupId: string) => boolean | Promise<boolean>;
  onRemove: (groupId: string) => boolean | Promise<boolean>;
}
