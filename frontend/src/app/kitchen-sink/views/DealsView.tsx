"use client";

import React from 'react';
import { motion } from 'motion/react';
import { ArrowRight, BadgeAlert } from 'lucide-react';
import { NotchLabel } from "@/components/product/notch-label";
import { MonumentIllustration } from '@/components/product/Illustrations';
import { japanVisualFixture } from '@/mocks/japan-visual-fixture';

export const DealsView = () => {
  const report = japanVisualFixture.report;
  const plan = report.transfer_advice?.plans[0];
  const step = plan?.steps[0];

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-5xl">
      <header className="mb-12">
        <NotchLabel>Sample evidence</NotchLabel>
        <h1 className="font-display display-hero text-4xl md:text-5xl leading-tight mt-4 mb-4">
          Transfer opportunities preview
        </h1>
        <p className="text-lg text-text-muted max-w-2xl">
          This surface reads the type-valid Japan fixture. It does not monitor providers or claim a live transfer promotion.
        </p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-12">
        <article className="lg:col-span-2 rounded-none border-2 border-border bg-bg overflow-hidden shadow-1">
          <MonumentIllustration type="synergy" />
          <div className="p-6 md:p-8">
            <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-text-muted mb-3">
              Frontend visual fixture · sample evidence
            </p>
            <h3 className="font-ui font-semibold text-2xl mb-3">{report.transfer_advice?.recommendation.reason}</h3>
            {step && plan && (
              <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 text-sm">
                <div className="border-2 border-border p-4">
                  <p className="font-mono text-xs text-text-muted uppercase">Source</p>
                  <p className="font-ui font-semibold text-text">{plan.source_currency}</p>
                </div>
                <ArrowRight className="w-5 h-5 text-primary" aria-hidden="true" />
                <div className="border-2 border-border p-4">
                  <p className="font-mono text-xs text-text-muted uppercase">Partner</p>
                  <p className="font-ui font-semibold text-text">{step.to_id}</p>
                </div>
              </div>
            )}
          </div>
        </article>

        <aside className="flex flex-col gap-4">
          <h4 className="font-ui font-semibold text-lg text-text">Evidence rail</h4>
          <div className="border-2 border-border bg-bg p-5 shadow-1">
            <div className="flex items-start gap-3">
              <BadgeAlert className="w-5 h-5 text-warning-text shrink-0" aria-hidden="true" />
              <div>
                <p className="font-ui font-semibold text-text">No verified live bonuses in this sample</p>
                <p className="text-sm text-text-muted mt-2">
                  Use the transfer path as a UI proof only. Verify ratios, timing, award space, and fees before action.
                </p>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </motion.div>
  );
};
