export type Quip = {
  id: string;
  text: string;
  categories: string[];
  tone: "playful" | "warm";
  approved: boolean;
};

export type QuipPack = {
  destination: string;
  version: number;
  quips: Quip[];
};

export type PipelineStage =
  | "intake"
  | "itinerary"
  | "costing"
  | "optimizing"
  | "transfer"
  | "critic"
  | "explaining";
