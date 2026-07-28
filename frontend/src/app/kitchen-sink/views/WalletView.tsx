"use client";
import React from 'react';
import { motion } from 'motion/react';
import { Sparkles, PlaneTakeoff } from 'lucide-react';
import { NotchLabel, TrustChip, HighlightBox } from '../../components/product/SharedUI';

export const WalletView = () => (
  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-4xl">
    <header className="mb-12">
      <NotchLabel>Your Points Arsenal</NotchLabel>
      <h1 className="font-display text-4xl md:text-5xl font-bold leading-tight mt-4 mb-4">Digital Wallet</h1>
      <p className="text-lg text-muted-foreground max-w-2xl">A real-time overview of your optimized cards and transferable reward balances.</p>
    </header>
    
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-12">
      <div className="relative overflow-hidden rounded-2xl border border-border p-6 bg-card shadow-sm hover:shadow-md transition-shadow">
        <svg className="absolute bottom-0 right-0 w-48 h-48 opacity-5" viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="40" stroke="var(--primary)" strokeWidth="10" fill="none" />
          <circle cx="50" cy="50" r="20" stroke="var(--primary)" strokeWidth="5" fill="none" />
        </svg>
        <div className="flex justify-between items-start mb-8 relative z-10">
          <div className="w-12 h-8 rounded bg-primary/20 border border-primary/30 flex items-center justify-center">
            <span className="text-[10px] font-bold text-primary">CHASE</span>
          </div>
          <span className="text-sm font-medium tracking-widest text-muted-foreground">•••• 4092</span>
        </div>
        <h3 className="font-display text-2xl font-bold relative z-10">Sapphire Reserve</h3>
        <div className="mt-6 flex items-end justify-between relative z-10">
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-1">Ultimate Rewards</p>
            <p className="font-medium text-2xl text-primary">184,200 <span className="text-base text-muted-foreground">pts</span></p>
          </div>
          <TrustChip state="verified" verifier="Sync: 1h ago" />
        </div>
      </div>

      <div className="relative overflow-hidden rounded-2xl border border-border p-6 bg-card shadow-sm hover:shadow-md transition-shadow">
        <svg className="absolute top-0 right-0 w-48 h-48 opacity-5 transform translate-x-4 -translate-y-4" viewBox="0 0 100 100">
          <rect x="20" y="20" width="60" height="60" stroke="var(--lacquer)" strokeWidth="10" fill="none" transform="rotate(45 50 50)" />
        </svg>
        <div className="flex justify-between items-start mb-8 relative z-10">
          <div className="w-12 h-8 rounded bg-lacquer/20 border border-lacquer/30 flex items-center justify-center">
            <span className="text-[10px] font-bold text-lacquer">AMEX</span>
          </div>
          <span className="text-sm font-medium tracking-widest text-muted-foreground">•••• 9011</span>
        </div>
        <h3 className="font-display text-2xl font-bold relative z-10">Platinum Card</h3>
        <div className="mt-6 flex items-end justify-between relative z-10">
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-1">Membership Rewards</p>
            <p className="font-medium text-2xl text-lacquer">215,000 <span className="text-base text-muted-foreground">pts</span></p>
          </div>
          <TrustChip state="verified" verifier="Sync: 1h ago" />
        </div>
      </div>
    </div>
    
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
      <div className="md:col-span-2">
        <NotchLabel>Active Perks & Credits</NotchLabel>
        <div className="mt-4 border border-border rounded-xl bg-card overflow-hidden shadow-sm">
           <div className="p-5 border-b border-border/40 flex justify-between items-center hover:bg-secondary/50 transition-colors">
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-full bg-lacquer/10 flex items-center justify-center text-lacquer">
                  <Sparkles className="w-5 h-5" />
                </div>
                <div>
                  <p className="font-bold text-foreground">Amex FHR Hotel Credit</p>
                  <p className="text-sm text-muted-foreground">Applied to Aman Tokyo</p>
                </div>
              </div>
              <span className="text-sm font-bold text-muted-foreground bg-background px-3 py-1 rounded-full border border-border">$200 / $200</span>
           </div>
           <div className="p-5 flex justify-between items-center hover:bg-secondary/50 transition-colors">
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center text-primary">
                  <PlaneTakeoff className="w-5 h-5" />
                </div>
                <div>
                  <p className="font-bold text-foreground">Chase Travel Credit</p>
                  <p className="text-sm text-muted-foreground">Available to use</p>
                </div>
              </div>
              <span className="text-sm font-bold text-primary bg-primary/10 px-3 py-1 rounded-full border border-primary/20">$300 / $300</span>
           </div>
        </div>
      </div>
      
      <div className="flex flex-col gap-4 pt-10">
        <HighlightBox 
          title="Transfer Bonus" 
          subtitle="Amex to Virgin Atlantic is currently offering a 30% bonus." 
          value="Ends in 2 days"
          actionLabel="View" 
        />
        <HighlightBox 
          title="Global Entry" 
          subtitle="Your Platinum credit for Global Entry is unused this year." 
          value="$100 Credit"
          actionLabel="Redeem" 
        />
      </div>
    </div>
  </motion.div>
);