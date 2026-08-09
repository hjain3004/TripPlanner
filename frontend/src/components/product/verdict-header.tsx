"use client";

import { useEffect, useRef } from "react";
import type { BudgetTotals } from "@/lib/api/types.gen";
import { CountUp } from "./count-up";
import { useReducedMotionSafe } from "@/lib/motion/use-reduced-motion-safe";
import confetti from "canvas-confetti";

interface VerdictHeaderProps {
  totals: BudgetTotals;
  destination: string;
  days: number;
  confidence?: number;
}

function confidenceLabel(score?: number): string {
  if (score == null) return "Unknown";
  if (score >= 0.8) return "High";
  if (score >= 0.5) return "Medium";
  return "Low";
}

export function VerdictHeader({ totals, destination, days, confidence }: VerdictHeaderProps) {
  const reduced = useReducedMotionSafe();
  const triggeredRef = useRef(false);

  useEffect(() => {
    const savingsPct = totals.savings_pct_bp / 100;
    if (!reduced && savingsPct >= 3.0 && !triggeredRef.current) {
      triggeredRef.current = true;
      confetti({
        particleCount: 80,
        spread: 70,
        origin: { y: 0.6 },
        disableForReducedMotion: true,
      });
      setTimeout(() => {
        document.querySelectorAll("body > canvas").forEach((c) => {
          c.setAttribute("aria-hidden", "true");
          const main = document.querySelector("main");
          if (main && c.parentElement !== main) {
            main.appendChild(c);
          }
        });
      }, 0);
    }
  }, [totals.savings_pct_bp, reduced]);

  return (
    <div className="register-issue text-center py-12 border-b-2 border-border" data-motion="verdict">
      <h1 className="font-display display-stroked text-h1 mb-4">
        Your {days}-day {destination} plan
      </h1>
      <div className="flex flex-wrap justify-center gap-8 text-sm">
        <div>
          <span className="block text-xs text-text-muted">Gross cost</span>
          <span className="block text-2xl font-ui tabular-nums">
            <CountUp valueMinor={totals.gross_minor} />
          </span>
        </div>
        <div>
          <span className="block text-xs text-text-muted">Effective cost</span>
          <span className="block text-2xl font-ui tabular-nums">
            <CountUp valueMinor={totals.effective_cost_minor} />
          </span>
        </div>
        <div>
          <span className="block text-xs text-text-muted">Savings</span>
          <span className="block text-2xl font-ui tabular-nums text-savings-text">
            <CountUp valueMinor={totals.gross_minor - totals.effective_cost_minor} />
          </span>
        </div>
      </div>
      {confidence != null && (
        <p className="text-xs text-text-muted mt-2">
          Confidence: <span className="font-medium">{confidenceLabel(confidence)}</span>
        </p>
      )}
    </div>
  );
}
