"use client";

import { useEffect, useState, useRef } from "react";
import { useReducedMotionSafe } from "@/lib/motion/use-reduced-motion-safe";

interface CountUpProps {
  valueMinor: number;
  currency?: string;
  durationMs?: number;
}

function formatMoney(minor: number, currency: string): string {
  const major = minor / 100;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(major);
}

export function CountUp({ valueMinor, currency = "INR", durationMs = 800 }: CountUpProps) {
  const reduced = useReducedMotionSafe();
  const [display, setDisplay] = useState(() => reduced ? valueMinor : 0);
  const frameRef = useRef<number>(0);
  const startRef = useRef<number>(0);

  useEffect(() => {
    if (reduced) return;
    startRef.current = performance.now();
    const animate = (now: number) => {
      const elapsed = now - startRef.current;
      const progress = Math.min(elapsed / durationMs, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(Math.round(eased * valueMinor));
      if (progress < 1) {
        frameRef.current = requestAnimationFrame(animate);
      }
    };
    frameRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frameRef.current);
  }, [valueMinor, durationMs, reduced]);

  return <span className="tabular-nums" data-motion="count-up">{formatMoney(display, currency)}</span>;
}
