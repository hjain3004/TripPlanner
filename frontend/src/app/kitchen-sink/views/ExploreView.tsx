"use client";

import React from 'react';
import { motion } from 'motion/react';
import { NotchLabel } from "@/components/product/notch-label";
import { MonumentIllustration } from '@/components/product/Illustrations';
import { DestinationStamp } from '@/components/product/destination-stamp';
import { JAPAN_ATLAS_STAMP } from '@/lib/design/philatelic-assets';

const DESTINATIONS = [
  {
    title: "Mount Fuji",
    subtitle: "Day-trip composition",
    description: "A calm destination card for mountain-and-rail planning. No redemption value is implied here.",
    type: "mtFuji",
  },
  {
    title: "Senso-ji Temple",
    subtitle: "Asakusa walking route",
    description: "A historic-city composition for itinerary curation, separated from prices and transfer claims.",
    type: "temple",
  },
  {
    title: "Tokyo Tower",
    subtitle: "Evening city landmark",
    description: "A skyline composition for orientation and rhythm; provider evidence appears in the results preview.",
    type: "tower",
  },
] as const;

export const ExploreView = () => (
  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-5xl">
    <header className="mb-12">
      <NotchLabel>Destination compositions</NotchLabel>
      <h1 className="font-display display-hero text-4xl md:text-5xl leading-tight mt-4 mb-4">Japan Highlights</h1>
      <p className="text-lg text-text-muted max-w-2xl">
        Three visual waypoints for the Japan preview. These are editorial destination surfaces, not deal cards.
      </p>
    </header>

    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
      {DESTINATIONS.map((destination, index) => (
        <article key={destination.title} className="border-2 border-border rounded-none bg-bg overflow-hidden shadow-1">
          <div className="relative overflow-hidden">
            <MonumentIllustration type={destination.type} />
            <div className="absolute inset-x-0 bottom-0 h-1 bg-primary" />
          </div>
          <div className="p-6">
            <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-text-muted mb-3">
              {destination.subtitle}
            </p>
            <h2 className="font-ui font-semibold text-2xl mb-2">{destination.title}</h2>
            <p className="text-sm text-text-muted leading-relaxed">{destination.description}</p>
            {index === 0 ? (
              <div className="mt-5 grid grid-cols-[1fr_auto] items-end gap-4 border-t-2 border-border pt-4">
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-text-muted">
                    Japan artifact
                  </p>
                  <p className="mt-1 text-xs leading-relaxed text-text-muted">
                    Decorative destination identity only. It does not imply verified availability.
                  </p>
                </div>
                <DestinationStamp asset={JAPAN_ATLAS_STAMP} size="thumbnail" decorative />
              </div>
            ) : null}
          </div>
        </article>
      ))}
    </div>
  </motion.div>
);
