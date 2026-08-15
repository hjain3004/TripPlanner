import { cn } from "@/lib/utils";

type TrustChipVariant = "verified" | "warning" | "needs-verification";

interface TrustChipProps {
  variant: TrustChipVariant;
  label: string;
}

const variantStyles: Record<TrustChipVariant, string> = {
  /* token-lint-disable-next-line no-dead-classes -- arbitrary opacity values compile to direct CSS values, not class names */
  verified: "bg-success/20 text-success-text border-border",
  /* token-lint-disable-next-line no-dead-classes -- arbitrary opacity values compile to direct CSS values, not class names */
  warning: "bg-warning/20 text-warning-text border-border",
  // text-text, not text-text-muted: this chip renders 11px, which is AA small
  // text needing 4.5:1. muted-on-accent-2 is 4.35:1 and failed aXe; text is
  // 6.95:1. Pinned in tests/contrast.test.ts.
  "needs-verification": "bg-accent-2 text-text border-border",
};

export function TrustChip({ variant, label }: TrustChipProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border leading-none",
        variantStyles[variant]
      )}
    >
      {label}
    </span>
  );
}
