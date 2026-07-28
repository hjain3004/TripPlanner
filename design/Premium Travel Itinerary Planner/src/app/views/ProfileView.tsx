"use client";
import React from 'react';
import { motion } from 'motion/react';
import { Award, Globe } from 'lucide-react';
import { NotchLabel } from '../../components/product/SharedUI';
import { MonumentIllustration } from '../../components/product/Illustrations';

export const ProfileView = () => (
  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-4xl">
    <header className="mb-12">
      <NotchLabel>Traveler Profile</NotchLabel>
      <h1 className="font-display text-[56px] font-semibold leading-[1.05] tracking-[-0.02em] mt-6 mb-6 text-foreground">
        J. Smith
      </h1>
      <p className="text-[17px] leading-[1.65] text-muted-foreground max-w-2xl font-ui">
        Manage your secure travel documents, preferences, and linked loyalty accounts to speed up bookings.
      </p>
    </header>

    <div className="grid grid-cols-1 md:grid-cols-12 gap-8">
      <div className="md:col-span-4 flex flex-col gap-6">
        <div className="rounded-none border border-border bg-card p-6 shadow-sm flex flex-col items-center text-center relative overflow-hidden">
          <div className="absolute top-0 w-full h-24 bg-secondary/50" />
          <MonumentIllustration type="passport" />
          <h3 className="font-ui font-semibold text-2xl mt-6 tracking-[-0.005em]">US Passport</h3>
          <p className="text-[11px] font-mono text-muted-foreground mt-2 tracking-widest uppercase">Expires 2031</p>
          <div className="mt-6 w-full bg-primary/5 text-primary text-[11px] font-mono tracking-widest uppercase font-semibold py-3 rounded-none border border-primary/20">
            TSA PreCheck Active
          </div>
        </div>
      </div>

      <div className="md:col-span-8 flex flex-col gap-8">
        <div>
          <h3 className="font-ui font-semibold text-[24px] mb-4 flex items-center gap-2 text-foreground tracking-[-0.005em]">
            <Award className="w-5 h-5 text-lacquer" /> Linked Loyalty Programs
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="rounded-none border border-border bg-card p-6 hover:bg-secondary/30 transition-colors">
              <div className="flex justify-between items-center mb-6">
                <span className="font-ui font-semibold text-[16px]">Delta SkyMiles</span>
                <span className="text-[10px] font-mono font-bold text-lacquer bg-lacquer/10 px-2 py-1 uppercase tracking-widest">Silver Medallion</span>
              </div>
              <p className="text-[28px] font-ui font-semibold text-primary tabular-nums">42,500</p>
              <p className="text-[11px] font-mono text-muted-foreground mt-2 uppercase tracking-wide">Miles available</p>
            </div>
            <div className="rounded-none border border-border bg-card p-6 hover:bg-secondary/30 transition-colors">
              <div className="flex justify-between items-center mb-6">
                <span className="font-ui font-semibold text-[16px]">Marriott Bonvoy</span>
                <span className="text-[10px] font-mono font-bold text-primary bg-primary/10 px-2 py-1 uppercase tracking-widest">Gold Elite</span>
              </div>
              <p className="text-[28px] font-ui font-semibold text-primary tabular-nums">118,000</p>
              <p className="text-[11px] font-mono text-muted-foreground mt-2 uppercase tracking-wide">Points available</p>
            </div>
          </div>
        </div>

        <div>
           <h3 className="font-ui font-semibold text-[24px] mb-4 flex items-center gap-2 text-foreground tracking-[-0.005em]">
            <Globe className="w-5 h-5 text-primary" /> Preferences
          </h3>
          <div className="rounded-none border border-border bg-card overflow-hidden">
            <div className="p-5 border-b border-border/50 flex justify-between items-center">
              <span className="font-ui font-semibold text-[15px] text-foreground">Home Airport</span>
              <span className="text-[11px] text-muted-foreground font-mono font-medium uppercase tracking-[0.16em]">JFK, LGA, EWR</span>
            </div>
            <div className="p-5 border-b border-border/50 flex justify-between items-center">
              <span className="font-ui font-semibold text-[15px] text-foreground">Seating Preference</span>
              <span className="text-[14px] font-ui text-muted-foreground">Aisle • Forward Cabin</span>
            </div>
            <div className="p-5 flex justify-between items-center">
              <span className="font-ui font-semibold text-[15px] text-foreground">Dietary Requirements</span>
              <span className="text-[14px] font-ui text-muted-foreground">Vegetarian</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </motion.div>
);