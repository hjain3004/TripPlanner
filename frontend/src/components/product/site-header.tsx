import Link from "next/link";

/**
* Topbar from the approved Phase 0 composition
 * (design/refs/palette/celadon-mangrove-forward.html, .topbar).
 *
 * The wordmark is the UI face, not the display face: a logotype/lockup is not a
 * "heading context" under CONTRACT.md §2's allowed-contexts rule. The slash is the
 * one deliberate accent-4 (accent-4) use in this composition, well inside the <2%
 * surface budget.
 *
 * "Your wallet" / "How it works" render as plain text, not links: those routes do
 * not exist yet, and the reference marks them up as spans. Only real destinations
 * are interactive.
 */
export function SiteHeader() {
  return (
    <header className="grid grid-cols-[1fr_auto_1fr] items-center min-h-[76px] px-[38px] border-b border-border max-[960px]:grid-cols-[1fr_auto] max-[650px]:min-h-[64px] max-[650px]:px-[18px]">
      <Link
        href="/"
        className="text-[20px] font-semibold leading-none tracking-[-0.01em] text-text"
      >
        TripPlanner<span className="text-accent-4">/</span>
      </Link>

      <div className="flex gap-[30px] text-[12px] font-semibold text-text-muted max-[960px]:hidden">
        <span>Plan a trip</span>
        <span>Your wallet</span>
        <span>How it works</span>
      </div>

      <div className="justify-self-end flex items-center gap-[18px] text-[12px] font-semibold">
        <span className="text-text-muted max-[650px]:hidden">
          Student prototype · sample data
        </span>
        <Link
          href="/plan"
          /* token-lint-disable-next-line no-dead-classes -- primary-hover token valid in theme but not auto-generated as hover utility; suppress for hover state */
          className="border-b border-primary text-primary hover:text-primary-hover hover:border-primary-hover transition-colors"
        >
          Start planning
        </Link>
      </div>
    </header>
  );
}
