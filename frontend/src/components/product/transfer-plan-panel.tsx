"use client";

import type { TransferAdvice } from "@/lib/api/types.gen";
import { MoneyText } from "./money-text";
import { TrustChip } from "./trust-chip";
import { WhyThis } from "./why-this";

interface TransferPlanPanelProps {
  advice: TransferAdvice;
}

export function TransferPlanPanel({ advice }: TransferPlanPanelProps) {
  const kind = advice.recommendation.kind;

  if (kind === "NO_DATA") {
    return (
      <div className="register-issue space-y-3">
        <p className="text-sm text-text-muted">{advice.recommendation.reason}</p>
        {advice.infeasible.length > 0 && (
          <div className="space-y-1.5 text-xs">
            <span className="text-xs font-medium text-text">What fell short</span>
            {advice.infeasible.map((inf, i) => (
              <div key={i} className="flex items-start gap-2 text-text-muted">
                <span className="shrink-0 mt-0.5">&rarr;</span>
                <span>{inf.note}</span>
              </div>
            ))}
          </div>
        )}
        <p className="text-xs text-text-muted">Share your points balances to unlock transfer options.</p>
      </div>
    );
  }

  return (
    <div className="register-issue space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-text">{advice.recommendation.kind}</span>
        <span className="text-xs text-text-muted">{advice.recommendation.reason}</span>
      </div>

      {advice.plans.map((plan) => (
        <div key={plan.id} className="border border-border rounded-sm">
          <div className="px-4 py-3 border-b border-border">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-text">{plan.source_currency}</span>
              <span className="text-sm text-savings-text tabular-nums">{plan.points_consumed.toLocaleString()} pts</span>
            </div>
            {plan.award && (
              <p className="text-xs text-text-muted mt-0.5">
                {plan.award.origin} &rarr; {plan.award.destination} · {plan.award.cabin} · {plan.award.operating_airline_hint}
              </p>
            )}
          </div>
          <div className="px-4 py-2 space-y-1.5 text-xs">
            {plan.award?.provenance?.needs_verification && (
              <div className="mb-2">
                <TrustChip variant="warning" label="Verify award availability before transferring" />
              </div>
            )}
            {plan.steps.length > 0 && (
              <div className="space-y-1">
                <span className="text-text-muted text-xs font-medium">Transfer path</span>
                {plan.steps.map((step, i) => (
                  <div key={i} className="flex items-center gap-1 text-text-muted">
                    <span className="text-text">{step.from_id}</span>
                    <span className="text-text-muted">&rarr;</span>
                    <span className="text-text">{step.to_id}</span>
                    <span className="ml-auto">
                      {step.amount_source.toLocaleString()} pts · {step.transfer_time_hours_typical}h
                    </span>
                  </div>
                ))}
              </div>
            )}
            {plan.value_per_point_micro > 0 && (
              <div className="flex justify-between">
                <span className="text-text-muted">Value per point</span>
                <span className="text-text tabular-nums">{plan.value_per_point_micro / 100} paise</span>
              </div>
            )}
            {plan.savings_vs_cash_minor > 0 && (
              <div className="flex justify-between">
                <span className="text-text-muted">Savings vs cash</span>
                <MoneyText minor={plan.savings_vs_cash_minor} />
              </div>
            )}
            {plan.effective_redemption_cost_minor > 0 && (
              <div className="flex justify-between">
                <span className="text-text-muted">Effective cost</span>
                <MoneyText minor={plan.effective_redemption_cost_minor} />
              </div>
            )}
            {plan.total_fees_minor > 0 && (
              <div className="flex justify-between">
                <span className="text-text-muted">Fees</span>
                <MoneyText minor={plan.total_fees_minor} />
              </div>
            )}
            {plan.leftover_miles > 0 && (
              <div className="flex justify-between">
                <span className="text-text-muted">Leftover miles</span>
                <span className="text-text tabular-nums">{plan.leftover_miles.toLocaleString()}</span>
              </div>
            )}
          </div>
          {plan.checklist_steps && plan.checklist_steps.length > 0 && (
            /* token-lint-disable-next-line no-dead-classes -- arbitrary opacity values compile to direct CSS values, not class names */
            <div className="px-4 py-2 border-t border-border bg-warning/5">
              <p className="text-xs font-medium text-warning-text mb-1">Before you transfer</p>
              <ul className="space-y-0.5">
                {plan.checklist_steps.map((step, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-xs text-text-muted">
                    <span className="text-warning-text mt-0.5">&#9632;</span>
                    <span>{step}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <WhyThis summary="How this recommendation was calculated">
            <div className="space-y-0.5 text-xs">
              {plan.explanation && plan.explanation.length > 0 ? (
                plan.explanation.map((e, i) => (
                  <p key={i} className="text-text-muted">{e}</p>
                ))
              ) : (
                <p className="text-text-muted">No detailed breakdown available.</p>
              )}
            </div>
          </WhyThis>
        </div>
      ))}

      {advice.infeasible.length > 0 && (
        <div className="space-y-1.5">
          <span className="text-xs font-medium text-text-muted">Infeasible options</span>
          {advice.infeasible.map((inf, i) => (
            <div key={i} className="text-xs text-text-muted flex items-start gap-2">
              <span className="shrink-0">&rarr;</span>
              <span>{inf.note}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
