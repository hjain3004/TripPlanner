"use client";
import React from 'react';
import { motion } from 'motion/react';
import { Tags, Award } from 'lucide-react';
import { NotchLabel } from "@/components/product/notch-label";
import { OffsetPlate } from "@/components/product/offset-plate";
import { SplitFlap } from "@/components/product/split-flap";
import { useReducedMotionSafe } from "@/lib/motion/use-reduced-motion-safe";

export const ProofView = () => {
  const reduced = useReducedMotionSafe();
  return (
  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-4xl">
    <header className="mb-12">
      <NotchLabel>Points Transfer Graph</NotchLabel>
      <h1 className="font-display text-[56px] font-semibold leading-[1.05] tracking-[-0.02em] mt-6 mb-6 text-text">
        The Anatomy of a Deal
      </h1>
      <p className="text-[17px] leading-[1.65] text-text-muted max-w-2xl font-ui">
        How we constructed your First Class redemption. Hand-authored line diagrams tracing the exact points flow, step by step.
      </p>
    </header>

    <div className="rounded-none border border-border bg-bg p-8 md:p-12 shadow-sm overflow-hidden relative">
      <div className="flex flex-col gap-12 relative z-10">
        
        {/* Step 1: Sources */}
        <div className="flex justify-between items-center relative">
          <div className="w-1/3">
            <h3 className="font-ui font-semibold text-[18px] text-text mb-1">Chase Ultimate Rewards</h3>
            <p className="font-mono text-[11px] text-text-muted uppercase tracking-wide">Source Account</p>
            <div className="text-[24px] font-ui font-semibold text-primary mt-2 tabular-nums">100,000 pts</div>
          </div>
          
          <div className="w-1/3 text-center">
            <h3 className="font-ui font-semibold text-[18px] text-text mb-1">Amex Membership Rewards</h3>
            <p className="font-mono text-[11px] text-text-muted uppercase tracking-wide">Source Account</p>
            <div className="text-[24px] font-ui font-semibold text-accent-4 mt-2 tabular-nums">10,000 pts</div>
          </div>
        </div>

        {/* Step 2: Transfer Graph Lines */}
        <div className="h-32 relative w-full flex justify-center items-center">
          {/* token-lint-disable-next-line no-inline-svg -- Hand-authored SVG */}
          <svg className="absolute inset-0 w-full h-full" preserveAspectRatio="none" viewBox="0 0 400 100" fill="none">
            {/* Draw-on motion lines. Exactly touching the center node. */}
            <motion.path 
              initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: reduced ? 0 : 1.5, ease: "easeInOut" }} 
              d="M 66 0 C 66 60, 200 60, 200 100" className="stroke-primary" strokeWidth="1.5" strokeDasharray="4 4" 
            />
            <motion.path 
              initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: reduced ? 0 : 1.5, ease: "easeInOut", delay: reduced ? 0 : 0.5 }} 
              d="M 334 0 C 334 60, 200 60, 200 100" className="stroke-accent-4" strokeWidth="1.5" strokeDasharray="4 4" 
            />
          </svg>
          <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: reduced ? 0 : 1.5 }} className="bg-bg border border-border rounded-none p-3 shadow-sm z-10">
            <Tags className="w-4 h-4 text-text-muted" />
          </motion.div>
        </div>

        {/* Step 3: Destination Hub */}
        <div className="flex justify-center text-center">
          <div className="w-1/2">
            <h3 className="font-ui font-semibold text-[18px] text-text mb-1">Virgin Atlantic Flying Club</h3>
            <p className="font-mono text-[11px] text-text-muted uppercase tracking-wide">Transfer Partner</p>
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: reduced ? 0 : 1.8 }} className="text-[28px] font-ui font-semibold text-text mt-4 border-b-2 border-accent-4 inline-block pb-1 tabular-nums">
              110,000 pts
            </motion.div>
          </div>
        </div>

        {/* Step 4: Final Route Line */}
        <div className="h-24 relative w-full flex justify-center items-center">
          {/* token-lint-disable-next-line no-inline-svg -- Hand-authored SVG */}
          <svg className="absolute inset-0 w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 60" fill="none">
            <motion.path 
              initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: reduced ? 0 : 1, ease: "easeInOut", delay: reduced ? 0 : 2.0 }} 
              d="M 50 0 L 50 60" className="stroke-border" strokeWidth="1.5" 
            />
            <motion.circle initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: reduced ? 0 : 3.0 }} cx="50" cy="60" r="4" className="fill-primary" />
          </svg>
        </div>

        {/* Step 5: Final Redemption */}
        <div className="flex justify-center text-center">
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: reduced ? 0 : 3.2 }} className="w-full md:w-2/3 border border-border bg-accent-2/30 p-8">
            <h3 className="font-ui font-semibold text-[24px] text-primary mb-2 tracking-[-0.005em]">ANA First Class (JFK → HND)</h3>
            <p className="text-[14px] text-text-muted mb-6 font-mono uppercase tracking-wide">Round trip retail value: $22,400</p>
            <div className="flex items-center justify-center gap-2 font-mono text-[var(--savings-text)] bg-[var(--savings)]/10 border border-[var(--savings)]/20 py-2 px-4 inline-flex uppercase text-[11px] tracking-widest font-medium">
              <Award className="w-4 h-4" />
              Outstanding Redemption Value: 20.3¢ / pt
            </div>
          </motion.div>
        </div>

      </div>
    </div>
    <div className="mt-16 mb-8">
      <h2 className="font-display text-2xl font-semibold mb-6">Primitives (Issue Register)</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <div className="register-issue p-6 bg-bg flex items-center justify-center">
          <OffsetPlate className="p-8 border-2 border-border bg-bg">
            <h3 className="font-display display-stroked text-3xl mb-4">Offset Plate</h3>
            <p className="font-mono text-sm text-text-muted">A document container</p>
          </OffsetPlate>
        </div>
        <div className="register-issue p-6 bg-bg flex flex-col items-center justify-center gap-4 border-2 border-border">
          <h3 className="font-display display-stroked text-3xl">Split Flap</h3>
          <SplitFlap value="$22,400" className="text-2xl" />
        </div>
      </div>
    </div>
  </motion.div>
  );
};