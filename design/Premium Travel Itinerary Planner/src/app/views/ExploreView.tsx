"use client";
import React from 'react';
import { motion } from 'motion/react';
import { ArrowRight, Award } from 'lucide-react';
import { NotchLabel } from '../../components/product/SharedUI';
import { MonumentIllustration } from '../../components/product/Illustrations';

export const ExploreView = () => (
  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-5xl">
    <header className="mb-12">
      <NotchLabel>Discover & Plan</NotchLabel>
      <h1 className="font-display text-[56px] font-semibold leading-[1.05] tracking-[-0.02em] mt-6 mb-6 text-foreground">
        Japan Highlights
      </h1>
      <p className="text-[17px] leading-[1.65] text-muted-foreground max-w-2xl font-ui">
        Vector-inspired representations of key spots for your itinerary.
      </p>
    </header>
    
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
      {/* Card 1 */}
      <div className="group border border-border rounded-none bg-card shadow-sm hover:shadow-md transition-shadow cursor-pointer">
        <div className="relative overflow-hidden bg-secondary/30">
          <MonumentIllustration type="mtFuji" />
          <div className="absolute inset-0 bg-gradient-to-t from-card to-transparent opacity-60" />
        </div>
        <div className="p-6 relative">
          <div className="absolute top-[-24px] right-6 w-12 h-12 bg-card border border-border rounded-none flex items-center justify-center text-primary shadow-sm group-hover:bg-primary group-hover:text-primary-foreground transition-colors">
            <ArrowRight className="w-5 h-5" />
          </div>
          <h3 className="font-ui font-semibold text-[24px] leading-[1.15] tracking-[-0.005em] text-primary mb-1">
            Mount Fuji
          </h3>
          <p className="text-[14px] text-muted-foreground mb-6 font-ui">Hakone Day Trip</p>
          <div className="flex items-center gap-2 text-[11px] font-mono font-medium uppercase tracking-wide text-primary border-l-2 border-primary pl-2">
            <Award className="w-3.5 h-3.5" />
            <span>2 Premium Redemptions</span>
          </div>
        </div>
      </div>

      {/* Card 2 */}
      <div className="group border border-border rounded-none bg-card shadow-sm hover:shadow-md transition-shadow cursor-pointer">
        <div className="relative overflow-hidden bg-secondary/30">
          <MonumentIllustration type="temple" />
          <div className="absolute inset-0 bg-gradient-to-t from-card to-transparent opacity-60" />
        </div>
        <div className="p-6 relative">
          <div className="absolute top-[-24px] right-6 w-12 h-12 bg-card border border-border rounded-none flex items-center justify-center text-[var(--color-lacquer)] shadow-sm group-hover:bg-[var(--color-lacquer)] group-hover:text-background transition-colors">
            <ArrowRight className="w-5 h-5" />
          </div>
          <h3 className="font-ui font-semibold text-[24px] leading-[1.15] tracking-[-0.005em] text-primary mb-1">
            Senso-ji Temple
          </h3>
          <p className="text-[14px] text-muted-foreground mb-6 font-ui">Asakusa, Tokyo</p>
          <div className="flex items-center gap-2 text-[11px] font-mono font-medium uppercase tracking-wide text-[var(--color-lacquer)] border-l-2 border-[var(--color-lacquer)] pl-2">
            <Award className="w-3.5 h-3.5" />
            <span>Best value: Hyatt Centric</span>
          </div>
        </div>
      </div>

      {/* Card 3 */}
      <div className="group border border-border rounded-none bg-card shadow-sm hover:shadow-md transition-shadow cursor-pointer">
        <div className="relative overflow-hidden bg-secondary/30">
          <MonumentIllustration type="tower" />
          <div className="absolute inset-0 bg-gradient-to-t from-card to-transparent opacity-60" />
        </div>
        <div className="p-6 relative">
          <div className="absolute top-[-24px] right-6 w-12 h-12 bg-card border border-border rounded-none flex items-center justify-center text-primary shadow-sm group-hover:bg-primary group-hover:text-primary-foreground transition-colors">
            <ArrowRight className="w-5 h-5" />
          </div>
          <h3 className="font-ui font-semibold text-[24px] leading-[1.15] tracking-[-0.005em] text-primary mb-1">
            Tokyo Tower
          </h3>
          <p className="text-[14px] text-muted-foreground mb-6 font-ui">Minato City, Tokyo</p>
          <div className="flex items-center gap-2 text-[11px] font-mono font-medium uppercase tracking-wide text-primary border-l-2 border-primary pl-2">
            <Award className="w-3.5 h-3.5" />
            <span>Andaz Tokyo (UR points)</span>
          </div>
        </div>
      </div>
    </div>
  </motion.div>
);
