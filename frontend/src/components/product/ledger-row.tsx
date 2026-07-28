import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface LedgerRowProps {
  label: string;
  value: string;
  dominant?: boolean;
  notch?: string;
  children?: ReactNode;
}

export function LedgerRow({ label, value, dominant, notch, children }: LedgerRowProps) {
  return (
    <div
      className={cn(
        "flex items-center justify-between py-3 border-b border-border",
        dominant && "bg-accent-2 -mx-4 px-4 rounded-sm"
      )}
    >
      <div className="flex items-center gap-2">
        {notch && (
          <span className="text-[10px] font-medium uppercase tracking-wider text-accent-4 -ml-6 pl-1 border-l-2 border-accent-4 leading-none">
            {notch}
          </span>
        )}
        <span className={cn("text-sm", dominant ? "font-semibold text-text" : "text-text-muted")}>
          {label}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "tabular-nums",
            dominant ? "text-base font-semibold text-text" : "text-sm text-text"
          )}
        >
          {value}
        </span>
      </div>
      {children && <div className="col-span-2 mt-1">{children}</div>}
    </div>
  );
}
