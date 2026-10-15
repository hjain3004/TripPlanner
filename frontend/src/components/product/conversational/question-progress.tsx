import type { ReactNode } from "react";
import { progressLabel } from "./conversational-types";

interface QuestionProgressProps {
  current: number;
  total: number;
  context?: ReactNode;
}
export function QuestionProgress({ current, total, context }: QuestionProgressProps) {
  const percent = Math.round((Math.min(Math.max(current, 0), Math.max(total, 1)) / Math.max(total, 1)) * 100);

  return (
    <div className="space-y-2" data-testid="question-progress">
      <div className="flex items-baseline justify-between gap-4 font-mono text-[11px] uppercase tracking-[0.11em] text-text-muted">
        <span>
          <span className="text-primary">{progressLabel(current, total)}</span> questions
        </span>
        {context ? <span className="text-right normal-case tracking-normal">{context}</span> : null}
      </div>
      <div
        className="h-2 overflow-hidden rounded-full border border-border bg-accent-2"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-label={`Interview progress: ${progressLabel(current, total)} questions`}
      >
        <div
          className="h-full bg-primary transition-[width] duration-180 ease-out motion-reduce:transition-none"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}
