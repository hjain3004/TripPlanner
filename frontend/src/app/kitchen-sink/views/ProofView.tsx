"use client";

import React from 'react';
import { motion } from 'motion/react';
import { ArrowRight, BadgeAlert } from 'lucide-react';
import { NotchLabel } from "@/components/product/notch-label";
import { MoneyText } from "@/components/product/money-text";
import { TransferPlanPanel } from "@/components/product/transfer-plan-panel";
import { japanVisualFixture } from '@/mocks/japan-visual-fixture';

export const ProofView = () => {
  const advice = japanVisualFixture.report.transfer_advice;
  const plan = advice?.plans.find((candidate) => !candidate.dominated) ?? advice?.plans[0];
  const step = plan?.steps[0];

  if (!advice || !plan || !step) {
    return (
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-4xl">
        <NotchLabel>Transfer proof</NotchLabel>
        <p className="mt-6 text-text-muted">No typed transfer artifact exists in this sample.</p>
      </motion.div>
    );
  }

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-4xl">
      <header className="mb-12">
        <NotchLabel>Typed transfer chain</NotchLabel>
        <h1 className="font-display display-hero text-[56px] leading-[1.05] tracking-[-0.02em] mt-6 mb-6 text-text">
          Source → Partner → Redemption
        </h1>
        <p className="text-[17px] leading-[1.65] text-text-muted max-w-2xl font-ui">
          Rendered from `TransferAdvice` in the Japan fixture. It is sample evidence, not a live award search.
        </p>
      </header>

      <div className="rounded-none border-2 border-border bg-bg p-5 md:p-8 shadow-1 overflow-hidden relative">
        <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr_auto_1fr] gap-4 items-stretch">
          <div className="border-2 border-border p-4">
            <p className="font-mono text-xs text-text-muted uppercase tracking-wide">Source</p>
            <h3 className="font-ui font-semibold text-xl mt-2">{plan.source_currency}</h3>
            <p className="text-sm text-text-muted tabular-nums mt-2">{step.amount_source.toLocaleString()} pts</p>
          </div>
          <ArrowRight className="hidden md:block self-center w-5 h-5 text-primary" aria-hidden="true" />
          <div className="border-2 border-border p-4">
            <p className="font-mono text-xs text-text-muted uppercase tracking-wide">Partner</p>
            <h3 className="font-ui font-semibold text-xl mt-2">{step.to_id}</h3>
            <p className="text-sm text-text-muted tabular-nums mt-2">{step.amount_dest.toLocaleString()} pts</p>
          </div>
          <ArrowRight className="hidden md:block self-center w-5 h-5 text-primary" aria-hidden="true" />
          <div className="border-2 border-border p-4">
            <p className="font-mono text-xs text-text-muted uppercase tracking-wide">Redemption</p>
            <h3 className="font-ui font-semibold text-xl mt-2">{plan.award.origin} → {plan.award.destination}</h3>
            <p className="text-sm text-text-muted mt-2">{plan.award.cabin} · {plan.award.operating_airline_hint}</p>
          </div>
        </div>

        {/* token-lint-disable-next-line no-dead-classes -- arbitrary opacity values compile to direct CSS values, not class names */}
        <div className="mt-6 border-2 border-warning bg-warning/10 p-4 flex items-start gap-3">
          <BadgeAlert className="w-5 h-5 text-warning-text shrink-0" aria-hidden="true" />
          <div className="text-sm">
            <p className="font-ui font-semibold text-warning-text">Verify before transfer</p>
            <p className="text-text-muted mt-1">{plan.award.availability_note}</p>
            <p className="text-text mt-2">Fees shown in fixture: <MoneyText minor={plan.total_fees_minor} /></p>
          </div>
        </div>
      </div>

      <div className="mt-8">
        <TransferPlanPanel advice={advice} />
      </div>
    </motion.div>
  );
};
