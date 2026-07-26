import type { ReactNode } from "react";
import { RouteNode, type RouteNodeState } from "./route-node";

interface RouteStep {
  id: string;
  state: RouteNodeState;
  label: string;
  content?: ReactNode;
}

interface RouteSpineProps {
  steps: RouteStep[];
}

export function RouteSpine({ steps }: RouteSpineProps) {
  return (
    <div className="relative">
      <div className="absolute left-[5px] top-3 bottom-3 w-0.5 bg-border" />
      <div className="flex flex-col gap-4">
        {steps.map((step) => (
          <RouteNode key={step.id} state={step.state} label={step.label}>
            {step.content}
          </RouteNode>
        ))}
      </div>
    </div>
  );
}
