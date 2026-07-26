"use client";

import { RouteSpine } from "./route-spine";
import type { RouteNodeState } from "./route-node";
const STAGE_ORDER = [
  "intake", "itinerary", "costing", "optimizing", "transfer", "critic", "explaining",
] as const;

const STAGE_LABELS: Record<string, string> = {
  intake: "Understanding your trip",
  itinerary: "Designing your days",
  costing: "Pricing it out",
  optimizing: "Optimizing your cards",
  transfer: "Checking your points",
  critic: "Double-checking",
  explaining: "Writing it up",
};

interface StageTrackerProps {
  stageIndex: number | null;
  stagesTotal: number;
  stage: string | null;
  indeterminate?: boolean;
}

export function StageTracker({ stageIndex, stagesTotal, stage, indeterminate }: StageTrackerProps) {
  if (indeterminate || stage === null || stageIndex === null) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <span className="inline-block w-3 h-3 rounded-full bg-primary animate-pulse" />
          <span className="text-sm text-text-muted">Working on your plan</span>
        </div>
        <div className="h-1.5 bg-accent-2 rounded-full overflow-hidden">
          <div className="h-full bg-primary rounded-full animate-pulse w-1/3" />
        </div>
      </div>
    );
  }

  const currentIdx = (STAGE_ORDER as readonly string[]).indexOf(stage);
  const visibleStages = STAGE_ORDER.slice(0, Math.max(currentIdx + 1, stagesTotal));

  const steps = visibleStages.map((s, i) => {
    let state: RouteNodeState;
    if (i < currentIdx) state = "done";
    else if (i === currentIdx) state = "current";
    else state = "pending";
    return {
      id: s,
      state,
      label: STAGE_LABELS[s] ?? s,
    };
  });

  return <RouteSpine steps={steps} />;
}
