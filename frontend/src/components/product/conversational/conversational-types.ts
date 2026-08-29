export type AnswerValue = string | string[] | number | null;

export type AnswerSource = "trip" | "profile" | "default" | "delegated";

export interface AnswerState {
  value: AnswerValue;
  source: AnswerSource;
  /** True when the answer is the explicit “No preference — choose for me” choice. */
  delegated?: boolean;
}
export interface ChoiceOption {
  value: string;
  label: string;
  description?: string;
}

export interface SingleSelectControl {
  kind: "single-select";
  options: ChoiceOption[];
  allowNoPreference?: boolean;
}

export interface MultiSelectControl {
  kind: "multi-select";
  options: ChoiceOption[];
  maxSelections?: number;
  allowNoPreference?: boolean;
}

export interface SliderControl {
  kind: "slider";
  min: number;
  max: number;
  step?: number;
  unit?: string;
  minLabel?: string;
  maxLabel?: string;
}

export interface DateControl {
  kind: "date";
  min?: string;
  max?: string;
}

export interface NumberControl {
  kind: "number";
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
}

export interface TextControl {
  kind: "text";
  placeholder?: string;
  maxLength?: number;
}

export type ControlDefinition =
  | SingleSelectControl
  | MultiSelectControl
  | SliderControl
  | DateControl
  | NumberControl
  | TextControl;

export interface InterviewQuestion {
  id: string;
  eyebrow?: string;
  title: string;
  description?: string;
  step: number;
  totalSteps: number;
  required?: boolean;
  canSkip?: boolean;
  control: ControlDefinition;
  answer?: AnswerState;
  /** Explain why this answer is already filled before the user edits it. */
  profileDerived?: string;
  /** Marks a value that applies only to this trip, not the saved profile. */
  tripOnly?: boolean;
}

export interface BriefItem {
  id: string;
  label: string;
  value: string;
  source: AnswerSource;
  detail?: string;
}

export interface BriefSection {
  id: string;
  title: string;
  description?: string;
  items: BriefItem[];
  amendable?: boolean;
}

export interface PendingProfileChange {
  id: string;
  label: string;
  value: string;
  reason?: string;
  approved?: boolean;
}

export interface TripBriefPresentation {
  title?: string;
  subtitle?: string;
  sections: BriefSection[];
  assumptions?: string[];
  unresolvedRequirements?: string[];
  pendingProfileChanges?: PendingProfileChange[];
}

export function progressLabel(current: number, total: number): string {
  const safeTotal = Math.max(1, total);
  const safeCurrent = Math.min(Math.max(1, current), safeTotal);
  return `${safeCurrent} of ${safeTotal}`;
}

export function isAnswerComplete(question: InterviewQuestion, value: AnswerValue): boolean {
  if (!question.required && (value === null || value === undefined || value === "")) {
    return true;
  }
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  return Number.isFinite(value);
}

export function answerSourceLabel(source: AnswerSource, delegated = false): string {
  if (delegated || source === "delegated") return "Chosen for me";
  if (source === "profile") return "Profile default";
  if (source === "default") return "Suggested default";
  return "This trip";
}
