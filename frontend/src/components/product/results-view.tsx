"use client";

import dynamic from "next/dynamic";
import type { FinalReport } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { VerdictHeader } from "@/components/product/verdict-header";
import { ItineraryTimeline } from "@/components/product/itinerary-timeline";
import { MoneyText } from "@/components/product/money-text";
import { PaymentStrategyCard } from "@/components/product/payment-strategy-card";
import { TransferPlanPanel } from "@/components/product/transfer-plan-panel";
import { BookingChecklist } from "@/components/product/booking-checklist";
import { TrustChip } from "@/components/product/trust-chip";
import { AssumptionsFooter } from "@/components/product/assumptions-footer";
import { DestinationStamp } from "@/components/product/destination-stamp";
import type { ApprovedPhilatelicAsset } from "@/lib/design/philatelic-assets";

const GsapEntrance = dynamic(
  () => import("@/components/product/gsap-entrance").then((m) => ({ default: m.GsapEntrance })),
  { ssr: false }
);

type ResultsViewProps = {
  report: FinalReport;
  onRetry?: () => void;
  destinationArtifact?: {
    asset: ApprovedPhilatelicAsset;
    routeLabel: string;
    dateLabel: string;
    issued?: boolean;
  };
};

export function ResultsView({ report, onRetry, destinationArtifact }: ResultsViewProps) {
  const bt = report.budget_totals;
  const destination = report.trip_spec?.destination_city ?? "destination";
  const numDays = report.itinerary?.days?.length ?? 0;

  return (
    <div className="min-h-screen bg-bg font-ui text-text" data-testid="results-view">
      <div className="mx-auto max-w-2xl px-6 py-12 space-y-8">

        {destinationArtifact ? (
          <section className="grid items-center gap-8 border-2 border-border bg-surface p-5 shadow-1 md:grid-cols-[1fr_auto]">
            <div className="min-w-0">
              <VerdictHeader
                totals={bt}
                destination={destination}
                days={numDays}
                confidence={report.confidence}
              />
            </div>
            <div className="justify-self-center md:justify-self-end">
              <DestinationStamp
                asset={destinationArtifact.asset}
                size="feature"
                routeLabel={destinationArtifact.routeLabel}
                dateLabel={destinationArtifact.dateLabel}
                issued={destinationArtifact.issued}
              />
            </div>
          </section>
        ) : (
          <VerdictHeader
            totals={bt}
            destination={destination}
            days={numDays}
            confidence={report.confidence}
          />
        )}

        {report.summary && (
          <p className="text-sm text-text-muted text-center -mt-4">{report.summary}</p>
        )}

        <GsapEntrance />

        {/* Itinerary */}
        <section className="gsap-section">
          <h2 className="font-ui font-semibold text-h2 mb-4">Itinerary</h2>
          {report.itinerary_overview && <p className="text-sm text-text-muted mb-4">{report.itinerary_overview}</p>}
          <ItineraryTimeline itinerary={report.itinerary} />
        </section>

        <hr className="border-border" />

        {/* Budget breakdown */}
        <section className="gsap-section">
          <h2 className="font-ui font-semibold text-h2 mb-4">Budget</h2>
          <div className="border border-border rounded-sm">
            <div className="px-4 py-2 border-b border-border">
              <span className="text-xs font-semibold uppercase tracking-wider text-text-muted">Cost breakdown</span>
            </div>
            <div className="px-4 space-y-1 py-2">
              <Row label="Gross cost" minor={bt.gross_minor} />
              <Row label="Discounts" minor={bt.discounts_minor} />
              <Row label="Rewards value" minor={bt.rewards_value_minor} />
              <Row label="Forex fees" minor={bt.forex_fees_minor} />
              <Row label="Effective cost" minor={bt.effective_cost_minor} bold />
              <Row label="Cash outlay now" minor={bt.cash_outlay_now_minor} />
              <Row label="Deferred value" minor={bt.deferred_value_minor} />
            </div>
          </div>
          {bt.savings_pct_bp != null && (
            /* token-lint-disable-next-line no-dead-classes -- arbitrary opacity values compile to direct CSS values, not class names */
            <div className="flex items-center justify-between px-4 py-3 mt-2 bg-accent-2/50 rounded-sm">
              <span className="text-sm font-medium text-text">Total savings</span>
              <span className="text-lg font-semibold text-savings-text tabular-nums">
                {(bt.savings_pct_bp / 100).toFixed(1)}%
              </span>
            </div>
          )}
          {report.payment_overview && <p className="text-xs text-text-muted mt-4">{report.payment_overview}</p>}
        </section>

        <hr className="border-border" />

        {/* Payment strategy */}
        {report.optimizer_result?.assignments && report.optimizer_result.assignments.length > 0 && (
          <section className="gsap-section">
            <h2 className="font-ui font-semibold text-h2 mb-4">Payment strategy</h2>
            <div className="space-y-3">
              {report.optimizer_result.assignments.map((assignment) => (
                <PaymentStrategyCard key={assignment.line.id} assignment={assignment} />
              ))}
            </div>
          </section>
        )}
        {report.payment_strategy && report.payment_strategy.length > 0 && !report.optimizer_result?.assignments?.length && (
          <section className="gsap-section">
            <h2 className="font-ui font-semibold text-h2 mb-4">Payment strategy</h2>
            <div className="space-y-2 text-sm">
              {report.payment_strategy.map((row, i) => (
                <div key={i} className="flex items-start gap-2">
                  <span className="font-mono text-xs text-text-muted w-16 shrink-0">{row.line_id}</span>
                  <span className="flex-1">{row.action_sentence}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Transfer advice */}
        {report.transfer_advice && (
          <>
            <hr className="border-border" />
            <section className="gsap-section">
              <h2 className="font-ui font-semibold text-h2 mb-4">Points & transfers</h2>
              <TransferPlanPanel advice={report.transfer_advice} />
            </section>
          </>
        )}

        {/* Booking checklist */}
        {report.booking_checklist && report.booking_checklist.length > 0 && (
          <>
            <hr className="border-border" />
            <section className="gsap-section">
              <BookingChecklist steps={report.booking_checklist} />
            </section>
          </>
        )}

        {/* Provenance warnings */}
        {report.provenance_warnings && report.provenance_warnings.length > 0 && (
          <>
            <hr className="border-border" />
            <section className="gsap-section">
              <h2 className="font-ui font-semibold text-h2 mb-4">Data quality</h2>
              <div className="space-y-2">
                {report.provenance_warnings.map((w, i) => (
                  <div key={i} className="flex items-start gap-2 text-sm">
                    <TrustChip variant="warning" label="needs verification" />
                    <span className="text-text-muted">{w}</span>
                  </div>
                ))}
              </div>
            </section>
          </>
        )}

        {/* Assumptions and footer */}
        <AssumptionsFooter
          assumptions={report.assumptions ?? []}
          disclaimers={report.caveats}
          minVerifiedDate={report.trip_spec?.start_date}
          footer={report.footer}
        />

        {/* Transfer advice NO_DATA note */}
        {report.transfer_advice?.recommendation?.kind === "NO_DATA" && !report.transfer_advice?.plans?.length && (
          <div className="text-center">
            <p className="text-sm text-text-muted">Share your points balances to unlock transfer recommendations.</p>
          </div>
        )}

        {onRetry && (
          <div className="text-center py-4">
            <Button variant="outline" onClick={onRetry}>Plan another trip</Button>
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, minor, bold }: { label: string; minor: number; bold?: boolean }) {
  return (
    <div className="flex justify-between py-1.5">
      <span className="text-sm text-text-muted">{label}</span>
      <span className={`tabular-nums text-sm ${bold ? "font-semibold text-text" : "text-text"}`}>
        <MoneyText minor={minor} />
      </span>
    </div>
  );
}
