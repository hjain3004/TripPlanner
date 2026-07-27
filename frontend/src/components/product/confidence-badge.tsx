interface ConfidenceBadgeProps {
  score: number;
}

function confidenceLabel(score: number): string {
  if (score >= 0.8) return "High";
  if (score >= 0.5) return "Medium";
  return "Low";
}

function confidenceLevel(score: number): "high" | "medium" | "low" {
  if (score >= 0.8) return "high";
  if (score >= 0.5) return "medium";
  return "low";
}

const levelStyles: Record<string, string> = {
  /* token-lint-disable-next-line no-dead-classes -- arbitrary opacity values compile to direct CSS values, not class names */
  high: "bg-success/20 text-success-text border-success/30",
  /* token-lint-disable-next-line no-dead-classes -- arbitrary opacity values compile to direct CSS values, not class names */
  medium: "bg-warning/20 text-warning-text border-warning/30",
  low: "bg-accent-2 text-text-muted border-border",
};

export function ConfidenceBadge({ score }: ConfidenceBadgeProps) {
  const level = confidenceLevel(score);
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border leading-none ${levelStyles[level]}`}>
      {confidenceLabel(score)}
    </span>
  );
}
