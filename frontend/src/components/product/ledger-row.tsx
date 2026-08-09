import type { ReactNode } from "react";
import { CreditCard } from "lucide-react";
import { cn } from "@/lib/utils";

interface LedgerRowProps {
  label: string;
  value: string | ReactNode;
  cost?: string | ReactNode;
  dominant?: boolean;
  notch?: string;
  children?: ReactNode;
}

export function LedgerRow({ label, value, cost, dominant, notch, children }: LedgerRowProps) {
  return (
    <div className={cn(
      "relative grid grid-cols-12 md:grid-cols-[2fr_1fr_1fr] gap-4 py-4 px-6 items-center border-b border-border/40 last:border-0 bg-bg",
      dominant ? "bg-accent-2/50 border-l-[3px] border-l-primary" : "hover:bg-accent-2/30 transition-colors border-l-[3px] border-l-transparent"
    )}>
      {notch && (
        <span className="absolute -top-[10px] left-[20px] inline-block px-[8px] py-[4px] text-bg bg-accent-4 font-mono font-medium text-[9px] uppercase tracking-[.06em] leading-none z-10">
          {notch}
        </span>
      )}
      <div className="col-span-12 md:col-span-1 flex flex-col">
        <span className="font-ui font-semibold text-[18px] text-primary flex items-center gap-3">
          <CreditCard className="w-4 h-4 text-text-muted" />
          {label}
        </span>
      </div>
      <div className="col-span-6 md:col-span-1 text-right flex flex-col items-end">
        <span className="font-ui font-semibold text-[18px] text-text">
          {value}
        </span>
      </div>
      {cost && (
        <div className="col-span-6 md:col-span-1 text-right flex flex-col items-end">
          <span className="font-ui font-semibold text-[18px] text-primary">
            {cost}
          </span>
        </div>
      )}
      {children && <div className="col-span-12 mt-1">{children}</div>}
    </div>
  );
}
