"use client";

import React from 'react';
import { motion } from 'motion/react';
import { CreditCard, Lock, PlusCircle } from 'lucide-react';
import { NotchLabel } from "@/components/product/notch-label";

const PLACEHOLDERS = [
  {
    title: "Cards",
    description: "Future account persistence will store held cards after spec 17 lands.",
    icon: CreditCard,
  },
  {
    title: "Points balances",
    description: "No loyalty program is connected in this preview. Balances must come from an explicit user/account record later.",
    icon: PlusCircle,
  },
  {
    title: "Security boundary",
    description: "This branch does not request card numbers, bank credentials, loyalty logins, or synchronization tokens.",
    icon: Lock,
  },
] as const;

export const WalletView = () => (
  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-4xl">
    <header className="mb-12">
      <NotchLabel>Preview only</NotchLabel>
      <h1 className="font-display display-hero text-4xl md:text-5xl leading-tight mt-4 mb-4">Wallet Preview</h1>
      <p className="text-lg text-text-muted max-w-2xl">
        Empty-state anatomy for future cards, points, and offers. Specs 17/18 must land before this becomes account behavior.
      </p>
    </header>

    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
      {PLACEHOLDERS.map((item) => {
        const Icon = item.icon;
        return (
          <article key={item.title} className="border-2 border-border bg-bg p-6 shadow-1">
            <Icon className="w-6 h-6 text-primary" aria-hidden="true" />
            <h3 className="font-ui text-2xl font-semibold mt-6">{item.title}</h3>
            <p className="text-sm text-text-muted mt-3 leading-relaxed">{item.description}</p>
          </article>
        );
      })}
    </div>

    {/* token-lint-disable-next-line no-dead-classes -- arbitrary opacity values compile to direct CSS values, not class names */}
    <div className="mt-8 border-2 border-warning bg-warning/10 p-5">
      <p className="font-ui font-semibold text-warning-text">Preview only · no accounts connected</p>
      <p className="text-sm text-text-muted mt-2">
        The UI intentionally avoids masked digits, fake sync timestamps, fabricated balances, or redemption controls.
      </p>
    </div>
  </motion.div>
);
