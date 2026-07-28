"use client";
import React from 'react';
import { motion } from 'motion/react';
import { Star, PlaneTakeoff } from 'lucide-react';
import { HighlightBox } from "@/components/product/SharedUI";
import { NotchLabel } from "@/components/product/notch-label";
import { MonumentIllustration } from '@/components/product/Illustrations';

export const DealsView = () => (
  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-5xl">
    <header className="mb-12">
      <NotchLabel>Card Synergy</NotchLabel>
      <h1 className="font-display text-4xl md:text-5xl font-bold leading-tight mt-4 mb-4">
        Curated Opportunities
      </h1>
      <p className="text-lg text-text-muted max-w-2xl">
        We constantly monitor transfer bonuses and award availability that perfectly align with your Ultimate Rewards and Membership Rewards balances.
      </p>
    </header>

    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-12">
      <div className="lg:col-span-2 rounded-2xl border border-border bg-bg overflow-hidden shadow-sm">
        <MonumentIllustration type="synergy" />
        <div className="p-6 md:p-8">
          <h3 className="font-display font-bold text-2xl mb-2">Amex + Chase Sweet Spot</h3>
          <p className="text-text-muted mb-6">
            You currently hold both UR and MR points. You can pool these points by transferring them to shared transfer partners like Virgin Atlantic, Air France/KLM Flying Blue, or British Airways Flying Club.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="p-4 rounded-xl border border-border bg-accent-2/30 flex items-start gap-3">
              <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-primary shrink-0"><Star className="w-4 h-4"/></div>
              <div>
                <p className="font-bold text-sm">Flying Blue Pools</p>
                <p className="text-xs text-text-muted mt-1">Combine points for business class to Europe.</p>
              </div>
            </div>
            <div className="p-4 rounded-xl border border-border bg-accent-2/30 flex items-start gap-3">
              <div className="w-8 h-8 rounded-full bg-accent-4/10 flex items-center justify-center text-accent-4 shrink-0"><PlaneTakeoff className="w-4 h-4"/></div>
              <div>
                <p className="font-bold text-sm">Virgin Atlantic (ANA)</p>
                <p className="text-xs text-text-muted mt-1">Both cards transfer 1:1 to Virgin for ANA flights.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
      
      <div className="flex flex-col gap-4">
        <h4 className="font-display font-bold text-lg text-text mb-2">Active Multipliers</h4>
        <HighlightBox 
          title="Virgin Atlantic Bonus" 
          subtitle="Amex is offering a 30% transfer bonus to Virgin Atlantic Flying Club." 
          value="1,000 → 1,300"
          actionLabel="Transfer" 
          accent="accent-4"
        />
        <HighlightBox 
          title="Marriott Bonvoy Bonus" 
          subtitle="Chase UR is offering a 50% transfer bonus to Marriott Bonvoy." 
          value="1,000 → 1,500"
          actionLabel="Transfer" 
          accent="primary"
        />
      </div>
    </div>
  </motion.div>
);