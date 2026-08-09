import type { ReactNode } from "react";
import { LedgerRow } from "./ledger-row";

interface LedgerItem {
  id: string;
  label: string;
  value: string | ReactNode;
  cost?: string | ReactNode;
  dominant?: boolean;
  notch?: string;
  content?: ReactNode;
}

interface DecisionLedgerProps {
  title?: string;
  items: LedgerItem[];
  children?: ReactNode;
}

export function DecisionLedger({ title, items, children }: DecisionLedgerProps) {
  return (
    <div className="register-issue border-2 border-border rounded-md bg-bg overflow-hidden shadow-1 mt-6">
      <div className="hidden md:grid grid-cols-[2fr_1fr_1fr] gap-4 py-3 px-6 bg-accent-2/30 border-b-2 border-border text-[10px] font-mono font-medium text-text-muted uppercase tracking-wider">
        <div className="pl-1">Payment Method</div>
        <div className="text-right pr-1">Points Value</div>
        <div className="text-right pr-1">Net Cost</div>
      </div>
      <div className="flex flex-col bg-bg">
        {items.map((item) => (
          <LedgerRow key={item.id} {...item} />
        ))}
      </div>
      {children && <div className="px-4 py-2 border-t border-border">{children}</div>}
    </div>
  );
}
