import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type RouteNodeState = "done" | "current" | "pending" | "warning";

interface RouteNodeProps {
  state: RouteNodeState;
  label: string;
  children?: ReactNode;
}

const stateStyles: Record<RouteNodeState, string> = {
  done: "bg-primary border-primary",
  current: "border-primary bg-bg",
  pending: "border-border bg-bg",
  warning: "bg-accent-4 border-accent-4",
};

const dotBase = "w-3 h-3 rounded-full border-2 shrink-0";

export function RouteNode({ state, label, children }: RouteNodeProps) {
  return (
    <div className="flex gap-3 items-start">
      <div className="flex flex-col items-center gap-1 pt-1">
        <div className={cn(dotBase, stateStyles[state])} />
      </div>
      <div className="flex-1 min-w-0">
        <span className="text-sm font-medium text-text">{label}</span>
        {children && <div className="mt-1">{children}</div>}
      </div>
    </div>
  );
}
