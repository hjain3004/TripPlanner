"use client";
import React from 'react';
import { motion } from 'motion/react';
import { Tags, Award } from 'lucide-react';
import { NotchLabel } from '../../components/product/SharedUI';

export const ProofView = () => (
  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-4xl">
    <header className="mb-12">
      <NotchLabel>Points Transfer Graph</NotchLabel>
      <h1 className="font-display text-4xl md:text-5xl font-bold leading-tight mt-4 mb-4">
        The Anatomy of a Deal
      </h1>
      <p className="text-lg text-muted-foreground max-w-2xl">
        How we constructed your First Class redemption. Hand-authored line diagrams tracing the exact points flow, step by step.
      </p>
    </header>

    <div className="rounded-2xl border border-border bg-card p-8 md:p-12 shadow-sm overflow-hidden relative">
      <div className="flex flex-col gap-12 relative z-10">
        
        {/* Step 1: Sources */}
        <div className="flex justify-between items-center relative">
          <div className="w-1/3">
            <h3 className="font-bold text-foreground mb-1">Chase Ultimate Rewards</h3>
            <p className="text-sm text-muted-foreground">Source Account</p>
            <div className="text-xl font-display font-bold text-primary mt-2">100,000 pts</div>
          </div>
          
          <div className="w-1/3 text-center">
            <h3 className="font-bold text-foreground mb-1">Amex Membership Rewards</h3>
            <p className="text-sm text-muted-foreground">Source Account</p>
            <div className="text-xl font-display font-bold text-lacquer mt-2">10,000 pts</div>
          </div>
        </div>

        {/* Step 2: Transfer Graph Lines */}
        <div className="h-32 relative w-full flex justify-center items-center">
          <svg className="absolute inset-0 w-full h-full" preserveAspectRatio="none" viewBox="0 0 400 100" fill="none">
            {/* Draw-on motion lines */}
            <motion.path 
              initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.5, ease: "easeInOut" }} 
              d="M 65 0 C 65 50, 190 50, 190 100" stroke="var(--primary)" strokeWidth="2" strokeDasharray="4 4" 
            />
            <motion.path 
              initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.5, ease: "easeInOut", delay: 0.5 }} 
              d="M 335 0 C 335 50, 210 50, 210 100" stroke="var(--lacquer)" strokeWidth="2" strokeDasharray="4 4" 
            />
          </svg>
          <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: 1.5 }} className="bg-background border-2 border-border rounded-full p-2 z-10">
            <Tags className="w-5 h-5 text-muted-foreground" />
          </motion.div>
        </div>

        {/* Step 3: Destination Hub */}
        <div className="flex justify-center text-center">
          <div className="w-1/2">
            <h3 className="font-bold text-foreground mb-1">Virgin Atlantic Flying Club</h3>
            <p className="text-sm text-muted-foreground">Transfer Partner</p>
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 1.8 }} className="text-3xl font-display font-bold text-foreground mt-2 border-b-2 border-lacquer inline-block pb-1">
              110,000 pts
            </motion.div>
          </div>
        </div>

        {/* Step 4: Final Route Line */}
        <div className="h-24 relative w-full flex justify-center items-center">
          <svg className="absolute inset-0 w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 60" fill="none">
            <motion.path 
              initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1, ease: "easeInOut", delay: 2.0 }} 
              d="M 50 0 L 50 60" stroke="var(--foreground)" strokeWidth="2" 
            />
            <motion.circle initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: 3.0 }} cx="50" cy="60" r="4" fill="var(--lacquer)" />
          </svg>
        </div>

        {/* Step 5: Final Redemption */}
        <div className="flex justify-center text-center">
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 3.2 }} className="w-full md:w-2/3 border border-border bg-secondary/20 p-6 rounded-xl">
            <h3 className="font-display font-bold text-2xl text-foreground mb-2">ANA First Class (JFK → HND)</h3>
            <p className="text-sm text-muted-foreground mb-4">Round trip retail value: $22,400</p>
            <div className="flex items-center justify-center gap-2 font-medium text-lacquer bg-lacquer/10 py-2 px-4 rounded-lg inline-flex">
              <Award className="w-5 h-5" />
              Outstanding Redemption Value: 20.3¢ / pt
            </div>
          </motion.div>
        </div>

      </div>
    </div>
  </motion.div>
);