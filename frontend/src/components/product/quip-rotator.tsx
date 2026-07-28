"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useReducedMotionSafe } from "@/lib/motion/use-reduced-motion-safe";
import type { Quip } from "@/lib/quips/types";

interface QuipRotatorProps {
  quips: Quip[];
  intervalMs?: number;
}

export function QuipRotator({ quips, intervalMs = 6000 }: QuipRotatorProps) {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const reduced = useReducedMotionSafe();
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const advance = useCallback(() => {
    setIndex((prev) => (prev + 1) % quips.length);
  }, [quips.length]);

  useEffect(() => {
    if (paused || quips.length <= 1) return;
    intervalRef.current = setInterval(advance, intervalMs);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [advance, intervalMs, paused, quips.length]);

  return (
    <div
      aria-live="off"
      className="relative h-8 flex items-center justify-center text-sm text-text-muted"
      onMouseEnter={() => setPaused(true)}
      onFocus={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onBlur={() => setPaused(false)}
    >
      {quips.length > 0 && (
        <AnimatePresence mode="wait">
          <motion.p
            key={`${quips[index]?.id}-${index}`}
            initial={reduced ? { opacity: 0 } : { opacity: 0, y: 6 }}
            animate={reduced ? { opacity: 1 } : { opacity: 1, y: 0 }}
            exit={reduced ? { opacity: 0 } : { opacity: 0, y: -6 }}
            transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
            className="absolute inset-0 flex items-center justify-center text-center px-4"
          >
            {quips[index]?.text}
          </motion.p>
        </AnimatePresence>
      )}
    </div>
  );
}
