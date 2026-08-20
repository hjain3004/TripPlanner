"use client";
import React from 'react';
import { motion } from 'motion/react';
import { Sparkles, PlaneTakeoff } from 'lucide-react';
import { NotchLabel, TrustChip, HighlightBox } from '../../components/product/SharedUI';

export const WalletView = () => (
  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-4xl">
    <header className="mb-12">
      <NotchLabel>Your Points Arsenal</NotchLabel>
      <h1 className="font-display text-[56px] font-semibold leading-[1.05] tracking-[-0.02em] mt-6 mb-6 text-foreground">Digital Wallet</h1>
      <p className="text-[17px] leading-[1.65] text-muted-foreground max-w-2xl font-ui">A real-time overview of your optimized cards and transferable reward balances.</p>
    </header>
    
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-12">
      <div className="relative overflow-hidden rounded-none border border-border p-8 bg-card shadow-sm hover:shadow-md transition-shadow">
        <svg className="absolute bottom-0 right-0 w-48 h-48 opacity-5" viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="40" stroke="var(--primary)" strokeWidth="10" fill="none" />
          <circle cx="50" cy="50" r="20" stroke="var(--primary)" strokeWidth="5" fill="none" />
        </svg>
        <div className="flex justify-between items-start mb-8 relative z-10">
          <div className="w-12 h-8 rounded-none bg-primary/20 border border-primary/30 flex items-center justify-center">
            <span className="text-[10px] font-bold text-primary font-mono">CHASE</span>
          </div>
          <span className="text-[11px] font-mono tracking-widest text-muted-foreground">•••• 4092</span>
        </div>
        <h3 className="font-ui text-2xl font-semibold relative z-10 text-primary tracking-[-0.005em]">Sapphire Reserve</h3>
        <div className="mt-8 flex items-end justify-between relative z-10">
          <div>
            <p className="text-[10px] font-mono font-bold uppercase tracking-widest text-muted-foreground mb-2">Ultimate Rewards</p>
            <p className="font-ui font-semibold text-2xl text-foreground tabular-nums">184,200 <span className="text-base text-muted-foreground font-normal">pts</span></p>
          </div>
          <TrustChip state="verified" verifier="Sync: 1h ago" />
        </div>
      </div>

      <div className="relative overflow-hidden rounded-none border border-border p-8 bg-card shadow-sm hover:shadow-md transition-shadow">
        <svg className="absolute top-0 right-0 w-48 h-48 opacity-5 transform translate-x-4 -translate-y-4" viewBox="0 0 100 100">
          <rect x="20" y="20" width="60" height="60" stroke="var(--lacquer)" strokeWidth="10" fill="none" transform="rotate(45 50 50)" />
        </svg>
        <div className="flex justify-between items-start mb-8 relative z-10">
          <div className="w-12 h-8 rounded-none bg-lacquer/20 border border-lacquer/30 flex items-center justify-center">
            <span className="text-[10px] font-bold text-lacquer font-mono">AMEX</span>
          </div>
          <span className="text-[11px] font-mono tracking-widest text-muted-foreground">•••• 9011</span>
        </div>
        <h3 className="font-ui text-2xl font-semibold relative z-10 text-primary tracking-[-0.005em]">Platinum Card</h3>
        <div className="mt-8 flex items-end justify-between relative z-10">
          <div>
            <p className="text-[10px] font-mono font-bold uppercase tracking-widest text-muted-foreground mb-2">Membership Rewards</p>
            <p className="font-ui font-semibold text-2xl text-foreground tabular-nums">215,000 <span className="text-base text-muted-foreground font-normal">pts</span></p>
          </div>
          <TrustChip state="verified" verifier="Sync: 1h ago" />
        </div>
      </div>
    </div>
    
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
      <div className="md:col-span-2">
        <NotchLabel>Active Perks & Credits</NotchLabel>
        <div className="mt-4 border border-border rounded-none bg-card overflow-hidden shadow-sm">
           <div className="p-6 border-b border-border/40 flex justify-between items-center hover:bg-secondary/30 transition-colors">
              <div className="flex items-center gap-5">
                <div className="w-10 h-10 rounded-none bg-lacquer/10 flex items-center justify-center text-lacquer">
                  <Sparkles className="w-4 h-4" />
                </div>
                <div>
                  <p className="font-ui font-semibold text-foreground text-[16px]">Amex FHR Hotel Credit</p>
                  <p className="text-[13px] text-muted-foreground font-ui mt-1">Applied to Aman Tokyo</p>
                </div>
              </div>
              <span className="text-[14px] font-ui font-semibold text-muted-foreground bg-background px-3 py-1.5 rounded-none border border-border tabular-nums">$200 / $200</span>
           </div>
           <div className="p-6 flex justify-between items-center hover:bg-secondary/30 transition-colors">
              <div className="flex items-center gap-5">
                <div className="w-10 h-10 rounded-none bg-primary/10 flex items-center justify-center text-primary">
                  <PlaneTakeoff className="w-4 h-4" />
                </div>
                <div>
                  <p className="font-ui font-semibold text-foreground text-[16px]">Chase Travel Credit</p>
                  <p className="text-[13px] text-muted-foreground font-ui mt-1">Available to use</p>
                </div>
              </div>
              <span className="text-[14px] font-ui font-semibold text-primary bg-primary/10 px-3 py-1.5 rounded-none border border-primary/20 tabular-nums">$300 / $300</span>
           </div>
        </div>
      </div>
      
      <div className="flex flex-col gap-6 pt-10">
        <HighlightBox 
          title="Transfer Bonus" 
          subtitle="Amex to Virgin Atlantic is currently offering a 30% bonus." 
          value="Ends in 2 days"
          actionLabel="View" 
          accent="lacquer"
        />
        <HighlightBox 
          title="Global Entry" 
          subtitle="Your Platinum credit for Global Entry is unused this year." 
          value="$100 Credit"
          actionLabel="Redeem" 
          accent="primary"
        />
      </div>
    </div>
  </motion.div>
);