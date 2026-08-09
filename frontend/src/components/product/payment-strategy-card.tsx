"use client";

import type { LineAssignment } from "@/lib/api/types.gen";
import { MoneyText } from "./money-text";
import { WhyThis } from "./why-this";
import { TrustChip } from "./trust-chip";

interface PaymentStrategyCardProps {
  assignment: LineAssignment;
}

export function PaymentStrategyCard({ assignment }: PaymentStrategyCardProps) {
  const hasRunnerUp = assignment.runner_up;
  const runnerUp = assignment.runner_up;

  return (
    <div className="border-2 border-border rounded-none shadow-1 bg-bg">
      <div className="px-4 py-3 border-b border-border">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-sm font-medium text-text">{assignment.line.label}</span>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-xs text-text-muted">{assignment.card_id}</span>
              <span className="text-xs text-text-muted">·</span>
              <span className="text-xs text-text-muted">{assignment.channel}</span>
            </div>
          </div>
          <MoneyText minor={assignment.line.amount_minor} />
        </div>
      </div>
      <div className="px-4 py-2 space-y-1.5 text-xs">
        {assignment.offers_applied && assignment.offers_applied.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {assignment.offers_applied.map((offer, i) => (
              <TrustChip key={i} variant="verified" label={`${offer.offer_id}: -₹${(offer.discount_minor / 100).toFixed(0)}`} />
            ))}
          </div>
        )}
        {assignment.points_earned > 0 && (
          <div className="flex justify-between">
            <span className="text-text-muted">Points earned</span>
            <span className="text-text tabular-nums">{assignment.points_earned.toLocaleString()}</span>
          </div>
        )}
        {assignment.points_value_minor > 0 && (
          <div className="flex justify-between">
            <span className="text-text-muted">Points value</span>
            <MoneyText minor={assignment.points_value_minor} />
          </div>
        )}
        {assignment.forex_fee_minor > 0 && (
          <div className="flex justify-between">
            <span className="text-text-muted">Forex fee</span>
            <MoneyText minor={assignment.forex_fee_minor} />
          </div>
        )}
        <div className="flex justify-between font-medium">
          <span className="text-text">Benefit</span>
          <MoneyText minor={assignment.benefit_minor} />
        </div>
      </div>
      {assignment.provenance_flags && assignment.provenance_flags.length > 0 && (
        <div className="px-4 py-1.5 border-t border-border">
          <div className="flex flex-wrap gap-1">
            {assignment.provenance_flags.map((flag, i) => (
              <TrustChip key={i} variant="needs-verification" label={flag} />
            ))}
          </div>
        </div>
      )}
      {hasRunnerUp && runnerUp && (
        <WhyThis summary={`Why not ${runnerUp.card_id}?`}>
          <div className="space-y-1 text-xs">
            <p className="text-text-muted">{runnerUp.summary}</p>
            <div className="flex justify-between">
              <span className="text-text-muted">Delta</span>
              <MoneyText minor={runnerUp.delta_minor} />
            </div>
          </div>
        </WhyThis>
      )}
      {assignment.explanation && assignment.explanation.length > 0 && (
        <WhyThis summary="How we got here">
          <ul className="space-y-0.5 text-xs">
            {assignment.explanation.map((e, i) => (
              <li key={i} className="text-text-muted">{e}</li>
            ))}
          </ul>
        </WhyThis>
      )}
    </div>
  );
}
