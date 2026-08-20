"use client";
import React from 'react';
import { motion } from 'motion/react';
import { Star, PlaneTakeoff } from 'lucide-react';
import { NotchLabel, HighlightBox } from '../../components/product/SharedUI';
import { MonumentIllustration } from '../../components/product/Illustrations';

export const DealsView = () => (
  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-5xl">
    <header className="mb-12">
      <NotchLabel>Card Synergy</NotchLabel>
      <h1 className="font-display text-[56px] font-semibold leading-[1.05] tracking-[-0.02em] mt-6 mb-6 text-foreground">
        Curated Opportunities
      </h1>
      <p className="text-[17px] leading-[1.65] text-muted-foreground max-w-2xl font-ui">
        We constantly monitor transfer bonuses and award availability that perfectly align with your Ultimate Rewards and Membership Rewards balances.
      </p>
    </header>

    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-12">
      <div className="lg:col-span-2 rounded-none border border-border bg-card shadow-sm overflow-hidden">
        <div className="border-b border-border">
          <MonumentIllustration type="synergy" />
        </div>
        <div className="p-8 md:p-10">
          <h3 className="font-ui font-semibold text-[24px] leading-[1.15] tracking-[-0.005em] text-primary mb-3">
            Amex + Chase Sweet Spot
          </h3>
          <p className="text-[16px] leading-[1.6] text-muted-foreground mb-8 font-ui">
            You currently hold both UR and MR points. You can pool these points by transferring them to shared transfer partners like Virgin Atlantic, Air France/KLM Flying Blue, or British Airways Flying Club.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            <div className="p-5 border-l-2 border-primary bg-primary/5 flex flex-col gap-3">
              <div className="w-8 h-8 bg-card border border-border flex items-center justify-center text-primary shrink-0 shadow-sm"><Star className="w-4 h-4"/></div>
              <div>
                <p className="font-ui font-semibold text-[16px] text-foreground">Flying Blue Pools</p>
                <p className="text-[13px] text-muted-foreground mt-1 leading-[1.5]">Combine points for business class to Europe.</p>
              </div>
            </div>
            <div className="p-5 border-l-2 border-lacquer bg-lacquer/5 flex flex-col gap-3">
              <div className="w-8 h-8 bg-card border border-border flex items-center justify-center text-lacquer shrink-0 shadow-sm"><PlaneTakeoff className="w-4 h-4"/></div>
              <div>
                <p className="font-ui font-semibold text-[16px] text-foreground">Virgin Atlantic (ANA)</p>
                <p className="text-[13px] text-muted-foreground mt-1 leading-[1.5]">Both cards transfer 1:1 to Virgin for ANA flights.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
      
      <div className="flex flex-col gap-6">
        <h4 className="font-mono text-[11px] uppercase tracking-[0.14em] text-text-faint mb-2">Active Multipliers</h4>
        <HighlightBox 
          title="Virgin Atlantic Bonus" 
          subtitle="Amex is offering a 30% transfer bonus to Virgin Atlantic Flying Club." 
          value="1,000 → 1,300"
          actionLabel="Transfer" 
          accent="lacquer"
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