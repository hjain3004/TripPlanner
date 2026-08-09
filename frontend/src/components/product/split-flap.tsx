import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface SplitFlapProps {
  value: string;
  className?: string;
}

export function SplitFlap({ value, className }: SplitFlapProps) {
  return (
    <div className={cn("inline-flex items-center gap-[2px]", className)}>
      {value.split("").map((char, i) => (
        <span
          key={i}
          className="relative inline-flex items-center justify-center bg-[var(--th-board)] text-[var(--th-board-text)] px-[0.1em] py-[0.1em] min-w-[0.9em] h-[1.3em] overflow-hidden"
          data-motion="split-flap"
        >
          <span className="relative z-10 tabular-nums leading-none">{char}</span>
          {/* Hairline across vertical center */}
          <div className="absolute top-1/2 left-0 right-0 h-[1px] bg-[var(--th-bg)]/20 -translate-y-1/2 z-20" />
        </span>
      ))}
    </div>
  );
}
