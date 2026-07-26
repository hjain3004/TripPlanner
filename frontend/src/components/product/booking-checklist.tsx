"use client";

import { useState, useEffect, useRef } from "react";
import { useReducedMotionSafe } from "@/lib/motion/use-reduced-motion-safe";
import confetti from "canvas-confetti";
import { ProgressRing } from "@/components/ui/progress-ring";

interface BookingChecklistProps {
  steps: string[];
}

export function BookingChecklist({ steps }: BookingChecklistProps) {
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const reduced = useReducedMotionSafe();
  const completedRef = useRef(false);

  const allComplete = checked.size === steps.length && steps.length > 0;
  const progress = steps.length > 0 ? (checked.size / steps.length) * 100 : 0;

  useEffect(() => {
    if (allComplete && !completedRef.current && !reduced) {
      completedRef.current = true;
      confetti({
        particleCount: 50,
        spread: 60,
        origin: { y: 0.4 },
        disableForReducedMotion: true,
      });
    }
  }, [allComplete, reduced]);

  const toggle = (i: number) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <div className="relative w-8 h-8" data-motion="checklist-progress">
          <ProgressRing progress={progress} />
          <span className="absolute inset-0 flex items-center justify-center text-[10px] font-mono tabular-nums text-text-muted">
            {Math.round(progress)}%
          </span>
        </div>
        <span className="text-sm font-medium text-text">Booking checklist</span>
      </div>
      {steps.length === 0 ? (
        <p className="text-xs text-text-muted italic">No checklist items for this booking.</p>
      ) : (
        <ul className="space-y-1.5">
          {steps.map((step, i) => (
            <li key={i} className="flex items-start gap-2">
              <button
                type="button"
                onClick={() => toggle(i)}
                className={`shrink-0 w-4 h-4 mt-0.5 rounded border text-xs flex items-center justify-center transition-colors ${
                  checked.has(i)
                    ? "bg-primary border-primary text-on-primary"
                    : "border-border text-text-muted hover:border-primary"
                }`}
                aria-label={`${checked.has(i) ? "Uncheck" : "Check"}: ${step}`}
              >
                {checked.has(i) ? "✓" : ""}
              </button>
              <span className={`text-sm ${checked.has(i) ? "text-text-muted line-through" : "text-text"}`}>
                {step}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
