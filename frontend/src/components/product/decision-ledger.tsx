import type { ReactNode } from "react";
import { LedgerRow } from "./ledger-row";

interface LedgerItem {
  id: string;
  label: string;
  value: string;
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
    <div className="border border-border rounded-sm">
      {title && (
        <div className="px-4 py-2 border-b border-border">
          <span className="text-xs font-semibold uppercase tracking-wider text-text-muted">
            {title}
          </span>
        </div>
      )}
      <div className="px-4">
        {items.map((item) => (
          <LedgerRow key={item.id} {...item} />
        ))}
      </div>
      {children && <div className="px-4 py-2 border-t border-border">{children}</div>}
    </div>
  );
}
