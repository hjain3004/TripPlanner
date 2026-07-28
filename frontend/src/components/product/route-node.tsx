import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Plane } from "lucide-react";

export type RouteNodeState = "done" | "current" | "pending" | "warning";

interface RouteNodeProps {
  state: RouteNodeState;
  label: string;
  subtitle?: string;
  icon?: any;
  children?: ReactNode;
}

export function RouteNode({ state, label, subtitle, icon: Icon = Plane, children }: RouteNodeProps) {
  const colors = {
    done: "bg-primary border-primary text-bg shadow-1",
    current: "bg-bg border-primary text-primary shadow-1",
    pending: "bg-bg border-border text-text-muted",
    warning: "bg-bg border-accent-4 text-accent-4"
  };

  return (
    <div className="relative pl-[44px] pb-14 last:pb-0">
      <div className="absolute left-[15px] top-10 bottom-0 w-[2px] bg-border last:hidden" />
      <div className={cn("absolute left-0 top-1 w-[32px] h-[32px] rounded-none border-[2px] flex items-center justify-center z-10", colors[state])}>
        <Icon className="w-4 h-4" />
      </div>
      <div className="flex flex-col gap-1">
        <h3 className={cn("font-ui text-[24px] font-semibold leading-[1.15] tracking-[-0.005em]", state === "pending" ? "text-text-muted" : "text-primary")}>
          {label}
        </h3>
        {subtitle && <p className="text-[14px] text-text-muted font-ui">{subtitle}</p>}
      </div>
      {children && (
        <div className="mt-5">
          {children}
        </div>
      )}
    </div>
  );
}
