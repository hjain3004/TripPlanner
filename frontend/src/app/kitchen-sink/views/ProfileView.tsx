"use client";

import React from 'react';
import { motion } from 'motion/react';
import { Globe, ShieldCheck, UserRound } from 'lucide-react';
import { NotchLabel } from "@/components/product/notch-label";

const PROFILE_SECTIONS = [
  {
    title: "Traveler basics",
    description: "A future persisted profile can hold explicit user-provided preferences after spec 17.",
    icon: UserRound,
  },
  {
    title: "Travel preferences",
    description: "Preference fields are placeholders only; no profile is stored in this frontend preview.",
    icon: Globe,
  },
  {
    title: "Sensitive documents",
    description: "No identity document, payment card, loyalty credential, or traveler secret storage exists in this branch.",
    icon: ShieldCheck,
  },
] as const;

export const ProfileView = () => (
  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-4xl">
    <header className="mb-12">
      <NotchLabel>Preview only</NotchLabel>
      <h1 className="font-display display-hero text-4xl md:text-5xl leading-tight mt-4 mb-4">
        Profile Preview
      </h1>
      <p className="text-lg text-text-muted max-w-2xl">
        Static profile anatomy for future account work. It does not store identity documents, loyalty accounts, or traveler secrets.
      </p>
    </header>

    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
      {PROFILE_SECTIONS.map((section) => {
        const Icon = section.icon;
        return (
          <article key={section.title} className="border-2 border-border bg-bg p-6 shadow-1">
            <Icon className="w-6 h-6 text-primary" aria-hidden="true" />
            <h3 className="font-ui font-semibold text-2xl mt-6">{section.title}</h3>
            <p className="text-sm text-text-muted mt-3 leading-relaxed">{section.description}</p>
          </article>
        );
      })}
    </div>

    {/* token-lint-disable-next-line no-dead-classes -- arbitrary opacity values compile to direct CSS values, not class names */}
    <div className="mt-8 border-2 border-warning bg-warning/10 p-5">
      <p className="font-ui font-semibold text-warning-text">Preview only · specs 17/18 required</p>
      <p className="text-sm text-text-muted mt-2">
        Account persistence, card acquisition, and secure profile behavior are intentionally outside this reconciliation branch.
      </p>
    </div>
  </motion.div>
);
