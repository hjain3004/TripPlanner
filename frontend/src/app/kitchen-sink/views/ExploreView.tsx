"use client";
import React from 'react';
import { motion } from 'motion/react';
import { ArrowRight, Award } from 'lucide-react';
import { NotchLabel } from "@/components/product/notch-label";
import { MonumentIllustration } from '@/components/product/Illustrations';

export const ExploreView = () => (
  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-5xl">
    <header className="mb-12">
      <NotchLabel>Discover & Plan</NotchLabel>
      <h1 className="font-display text-4xl md:text-5xl font-bold leading-tight mt-4 mb-4">Japan Highlights</h1>
      <p className="text-lg text-text-muted max-w-2xl">Vector-inspired representations of key spots for your itinerary.</p>
    </header>
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
      <div className="group border border-border rounded-2xl bg-bg overflow-hidden cursor-pointer hover:shadow-lg transition-all hover:-translate-y-1">
        <div className="relative overflow-hidden">
          <MonumentIllustration type="mtFuji" />
          <div className="absolute inset-0 bg-gradient-to-t from-card to-transparent opacity-60" />
        </div>
        <div className="p-6 relative">
          <div className="absolute top-[-24px] right-6 w-12 h-12 bg-bg border border-border rounded-full flex items-center justify-center group-hover:bg-primary group-hover:text-bg group-hover:border-primary transition-all shadow-sm">
            <ArrowRight className="w-5 h-5" />
          </div>
          <h3 className="font-display font-bold text-2xl mb-1">Mount Fuji</h3>
          <p className="text-sm text-text-muted mb-5">Hakone Day Trip</p>
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-primary bg-primary/5 p-2 rounded-lg">
            <Award className="w-4 h-4" />
            <span>2 Premium Redemptions</span>
          </div>
        </div>
      </div>
      <div className="group border border-border rounded-2xl bg-bg overflow-hidden cursor-pointer hover:shadow-lg transition-all hover:-translate-y-1">
        <div className="relative overflow-hidden">
          <MonumentIllustration type="temple" />
          <div className="absolute inset-0 bg-gradient-to-t from-card to-transparent opacity-60" />
        </div>
        <div className="p-6 relative">
          <div className="absolute top-[-24px] right-6 w-12 h-12 bg-bg border border-border rounded-full flex items-center justify-center group-hover:bg-accent-4 group-hover:text-bg group-hover:border-accent-4 transition-all shadow-sm">
            <ArrowRight className="w-5 h-5" />
          </div>
          <h3 className="font-display font-bold text-2xl mb-1">Senso-ji Temple</h3>
          <p className="text-sm text-text-muted mb-5">Asakusa, Tokyo</p>
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-accent-4 bg-accent-4/5 p-2 rounded-lg">
            <Award className="w-4 h-4" />
            <span>Best value: Hyatt Centric</span>
          </div>
        </div>
      </div>
      <div className="group border border-border rounded-2xl bg-bg overflow-hidden cursor-pointer hover:shadow-lg transition-all hover:-translate-y-1">
        <div className="relative overflow-hidden">
          <MonumentIllustration type="tower" />
          <div className="absolute inset-0 bg-gradient-to-t from-card to-transparent opacity-60" />
        </div>
        <div className="p-6 relative">
          <div className="absolute top-[-24px] right-6 w-12 h-12 bg-bg border border-border rounded-full flex items-center justify-center group-hover:bg-primary group-hover:text-bg group-hover:border-primary transition-all shadow-sm">
            <ArrowRight className="w-5 h-5" />
          </div>
          <h3 className="font-display font-bold text-2xl mb-1">Tokyo Tower</h3>
          <p className="text-sm text-text-muted mb-5">Minato City, Tokyo</p>
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-primary bg-primary/5 p-2 rounded-lg">
            <Award className="w-4 h-4" />
            <span>Andaz Tokyo (UR points)</span>
          </div>
        </div>
      </div>
    </div>
  </motion.div>
);