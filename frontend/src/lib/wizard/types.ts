export interface WizardData {
  origin: string;
  destination: string;
  startDate: string;
  endDate: string;
  travelers: number;
  cardIds: string[];
  pointsBalances: Record<string, number>;
  budgetStyle: "budget" | "balanced" | "luxury";
  pace: "relaxed" | "moderate" | "packed";
  interests: string[];
  editedRawRequest?: string;
}

export const EMPTY_WIZARD: WizardData = {
  origin: "",
  destination: "",
  startDate: "",
  endDate: "",
  travelers: 1,
  cardIds: [],
  pointsBalances: {},
  budgetStyle: "balanced",
  pace: "moderate",
  interests: [],
};
