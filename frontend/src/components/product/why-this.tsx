"use client";

import { useState, type ReactNode } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Info, ChevronDown } from "lucide-react";

interface WhyThisProps {
  summary: string;
  children: ReactNode;
}

export function WhyThis({ summary, children }: WhyThisProps) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="mt-4">
      <button 
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 text-sm font-medium text-primary hover:opacity-80 transition-opacity bg-primary/5 px-3 py-2 rounded-lg w-full"
      >
        <Info className="w-4 h-4" />
        {summary}
        <motion.div animate={{ rotate: isOpen ? 180 : 0 }} className="ml-auto">
          <ChevronDown className="w-4 h-4" />
        </motion.div>
      </button>
      <AnimatePresence>
        {isOpen && (
          <motion.div animate={{ height: "auto", opacity: 1 }} initial={{ height: 0, opacity: 0 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="p-3 text-sm text-text-muted leading-relaxed bg-primary/5 rounded-b-lg border-t border-primary/10 text-left">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
