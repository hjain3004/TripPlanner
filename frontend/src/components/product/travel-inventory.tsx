import type { InventoryQuoteSummary, TravelInventorySummary } from "@/lib/api";
import { MoneyText } from "./money-text";
import { TrustChip } from "./trust-chip";

function Quote({ quote, label }: { quote: InventoryQuoteSummary; label: string }) {
  const trust = quote.needs_verification || quote.status === "stale" || quote.status === "verify_required" ? "needs-verification" : quote.status === "live" ? "verified" : "warning";
  return (
    <article className="border border-border p-4 space-y-2" data-testid={`inventory-${quote.domain}`}>
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-medium text-text">{label}</h3>
        <TrustChip variant={trust} label={quote.status.replaceAll("_", " ")} />
      </div>
      <p className="text-sm text-text-muted">{quote.attribution ?? quote.provider_id}</p>
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
        <span>Source: <MoneyText minor={quote.source_amount_minor} currency={quote.source_currency} /></span>
        {quote.converted_amount_minor != null && <span>Computed line: <MoneyText minor={quote.converted_amount_minor} /></span>}
        <span>Scope: {quote.price_scope.basis.replaceAll("_", " ")}</span>
      </div>
      <p className="text-xs text-text-muted">Retrieved {new Date(quote.retrieved_at).toLocaleString()}.</p>
      {(quote.limitations ?? []).map((limitation) => <p key={limitation} className="text-xs text-text-muted">{limitation}</p>)}
      {quote.deep_link_url && <a className="text-xs underline" href={quote.deep_link_url} target="_blank" rel="noopener noreferrer">View provider details</a>}
    </article>
  );
}

export function TravelInventory({ inventory }: { inventory: TravelInventorySummary }) {
  const quotes = [
    inventory.flight ? <Quote key="flight" quote={inventory.flight} label="Flight evidence" /> : null,
    inventory.hotel ? <Quote key="hotel" quote={inventory.hotel} label="Stay evidence" /> : null,
  ].filter(Boolean);
  return (
    <section aria-label="Travel inventory evidence" className="space-y-4" data-testid="travel-inventory">
      <div>
        <h2 className="font-ui font-semibold text-h2">Travel inventory evidence</h2>
        <p className="text-sm text-text-muted mt-1">These bounded quotes inform the plan; verify price, fees, and availability before booking.</p>
      </div>
      <div className="space-y-3">{quotes}</div>
      {inventory.limitations?.map((limitation) => <p key={limitation} className="text-xs text-text-muted">{limitation}</p>)}
      {inventory.alternatives?.length ? <p className="text-xs text-text-muted">{inventory.alternatives.length} alternative quote(s) retained for comparison.</p> : null}
    </section>
  );
}
