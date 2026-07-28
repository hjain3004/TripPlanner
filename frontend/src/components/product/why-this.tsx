"use client";

import { useState, type ReactNode } from "react";
import { motion, AnimatePresence } from "motion/react";

interface WhyThisProps {
  summary: string;
  children: ReactNode;
}

export function WhyThis({ summary, children }: WhyThisProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border-b border-border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between py-2 px-0 text-left text-sm text-text-muted hover:text-text transition-colors"
      >
        <span>{summary}</span>
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.18 }}
          className="text-xs"
        >
          ▾
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <div className="pb-3 text-sm text-text">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
