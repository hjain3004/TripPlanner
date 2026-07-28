"use client";
import React from 'react';
import { motion } from 'motion/react';
import { Award, Globe } from 'lucide-react';
import { NotchLabel } from "@/components/product/notch-label";
import { MonumentIllustration } from '@/components/product/Illustrations';

export const ProfileView = () => (
  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-4xl">
    <header className="mb-12">
      <NotchLabel>Traveler Profile</NotchLabel>
      <h1 className="font-display text-4xl md:text-5xl font-bold leading-tight mt-4 mb-4">
        J. Smith
      </h1>
      <p className="text-lg text-text-muted max-w-2xl">
        Manage your secure travel documents, preferences, and linked loyalty accounts to speed up bookings.
      </p>
    </header>

    <div className="grid grid-cols-1 md:grid-cols-12 gap-8">
      <div className="md:col-span-4 flex flex-col gap-6">
        <div className="rounded-2xl border border-border bg-bg p-6 shadow-sm flex flex-col items-center text-center relative overflow-hidden">
          <div className="absolute top-0 w-full h-24 bg-accent-2/50" />
          <MonumentIllustration type="passport" />
          <h3 className="font-display font-bold text-xl mt-4">US Passport</h3>
          <p className="text-sm text-text-muted mt-1 tracking-widest uppercase">Expires 2031</p>
          <div className="mt-4 w-full bg-primary/5 text-primary text-xs font-bold py-2 rounded-lg border border-primary/20">
            TSA PreCheck Active
          </div>
        </div>
      </div>

      <div className="md:col-span-8 flex flex-col gap-8">
        <div>
          <h3 className="font-display font-bold text-2xl mb-4 flex items-center gap-2">
            <Award className="w-6 h-6 text-accent-4" /> Linked Loyalty Programs
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="rounded-xl border border-border bg-bg p-5 hover:border-border/80 transition-colors">
              <div className="flex justify-between items-center mb-4">
                <span className="font-bold">Delta SkyMiles</span>
                <span className="text-xs font-bold text-accent-4 bg-accent-4/10 px-2 py-1 rounded">Silver Medallion</span>
              </div>
              <p className="text-2xl font-display font-bold text-text">42,500</p>
              <p className="text-xs text-text-muted mt-1">Miles available</p>
            </div>
            <div className="rounded-xl border border-border bg-bg p-5 hover:border-border/80 transition-colors">
              <div className="flex justify-between items-center mb-4">
                <span className="font-bold">Marriott Bonvoy</span>
                <span className="text-xs font-bold text-primary bg-primary/10 px-2 py-1 rounded">Gold Elite</span>
              </div>
              <p className="text-2xl font-display font-bold text-text">118,000</p>
              <p className="text-xs text-text-muted mt-1">Points available</p>
            </div>
          </div>
        </div>

        <div>
           <h3 className="font-display font-bold text-2xl mb-4 flex items-center gap-2">
            <Globe className="w-6 h-6 text-primary" /> Preferences
          </h3>
          <div className="rounded-2xl border border-border bg-bg overflow-hidden">
            <div className="p-4 border-b border-border/50 flex justify-between items-center">
              <span className="font-medium text-text">Home Airport</span>
              <span className="text-sm text-text-muted font-bold tracking-widest">JFK, LGA, EWR</span>
            </div>
            <div className="p-4 border-b border-border/50 flex justify-between items-center">
              <span className="font-medium text-text">Seating Preference</span>
              <span className="text-sm text-text-muted">Aisle • Forward Cabin</span>
            </div>
            <div className="p-4 flex justify-between items-center">
              <span className="font-medium text-text">Dietary Requirements</span>
              <span className="text-sm text-text-muted">Vegetarian</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </motion.div>
);