import Link from "next/link";
import { SiteHeader } from "@/components/product/site-header";
import { TrustChip } from "@/components/product/trust-chip";

export default function Home() {
  return (
    <div className="min-h-screen bg-bg font-ui text-text">
      <SiteHeader />

      <main className="w-full max-w-[1440px] mx-auto bg-surface shadow-3">
        {/* ── Hero ── */}
        <section className="grid grid-cols-[53%_47%] min-h-[630px] border-b border-border max-[960px]:grid-cols-1">
          {/* Left: Hero Copy */}
          <div className="flex flex-col pr-[62px] pl-[62px] pt-[74px] pb-[42px] border-r border-border max-[960px]:border-r-0 max-[960px]:border-b max-[960px]:min-h-[610px] max-[650px]:min-h-[560px] max-[650px]:p-[52px_22px_28px]">
            {/* Overline */}
            <span className="flex items-center gap-[10px] text-text-muted font-mono font-medium text-[10px] leading-[1.4] uppercase tracking-[.09em]">
              <span className="w-[27px] h-[2px] bg-accent-4" aria-hidden="true" />
              Travel intelligence · made human
            </span>

            {/* H1 — Display face (Bodoni Moda) */}
            <h1 className="font-display text-hero leading-[1.0] tracking-[-0.02em] mt-[31px] max-w-[720px]">
              One journey.
              <br />
              <em className="text-primary not-italic font-normal">Every advantage.</em>
            </h1>

            {/* Lede */}
            <p className="text-text-muted mt-[30px] max-w-[560px] text-[17px] leading-[1.65]">
              Flights, stays, points and card offers—resolved into one composed, understandable way
              to travel.
            </p>

            {/* Trust line */}
            <div className="grid grid-cols-3 gap-[14px] mt-auto pt-[34px] border-t border-border">
              <div className="text-text-muted font-mono font-medium text-[10px] leading-[1.45] uppercase">
                <strong className="block mb-[4px] text-primary font-ui font-semibold text-[13px] leading-[1.2] uppercase tracking-none">
                  Trip-first
                </strong>
                Not another flight-search wall
              </div>
              <div className="text-text-muted font-mono font-medium text-[10px] leading-[1.45] uppercase">
                <strong className="block mb-[4px] text-primary font-ui font-semibold text-[13px] leading-[1.2] uppercase tracking-none">
                  Explainable
                </strong>
                Every number has a source
              </div>
              <div className="text-text-muted font-mono font-medium text-[10px] leading-[1.45] uppercase">
                <strong className="block mb-[4px] text-primary font-ui font-semibold text-[13px] leading-[1.2] uppercase tracking-none">
                  Human-controlled
                </strong>
                You approve every next step
              </div>
</div>
            </div>

            {/* Right: Planner Panel */}
          <div className="relative grid grid-rows-[auto_1fr_auto] bg-accent-2 grid-paper p-0 max-[650px]:grid-rows-[auto_1fr_auto]">
            {/* Planner Head */}
            <div className="flex justify-between items-center px-[34px] pt-[25px] pb-[25px] border-b border-border bg-surface-overlay">
              <span className="font-mono font-medium text-[10px] uppercase tracking-[.08em]">
                Journey draft · 01/04
              </span>
              <b className="flex items-center gap-[7px] text-primary text-[11px]">
                <span className="w-[7px] h-[7px] rounded-full bg-success" aria-hidden="true" />
                Ready
              </b>
            </div>

            {/* Route Form */}
            <div className="relative px-[39px] pb-[30px] pt-[44px] pl-[82px] max-[650px]:pr-[22px]">
              {/* Vertical spine line */}
              <span className="absolute left-[49px] top-[76px] bottom-[78px] w-[2px] bg-primary" aria-hidden="true" />

              {/* Route Row 1: Origin */}
              <div className="relative grid grid-cols-[1fr_82px] gap-[24px] min-h-[116px] py-[15px_0_23px] border-b border-border">
                <span
                  /* token-lint-disable-next-line no-direct-var -- route node marker needs 2px ring in accent color; no Tailwind utility for 2px box-shadow ring */
                  className="absolute left-[-41px] top-[25px] w-[11px] h-[11px] rounded-full border-[3px] border-accent-2 bg-accent-4 shadow-[0_0_0_2px_theme(colors.accent.4)]"
                  aria-hidden="true"
                />
                <div>
                  <label className="block text-text-muted font-mono font-medium text-[9px] tracking-[.08em] uppercase">
                    Origin
                  </label>
                  <strong className="block mt-[7px] text-primary font-ui font-semibold text-[26px] leading-none tracking-[-0.01em]">
                    Mumbai
                  </strong>
                  <small className="block mt-[7px] text-text-muted text-[11px]">
                    Chhatrapati Shivaji Maharaj International
                  </small>
                </div>
                <span className="self-start pt-[16px] text-primary font-mono font-medium text-[12px] text-right">
                  BOM
                </span>
              </div>

              {/* Route Row 2: Destination */}
              <div className="relative grid grid-cols-[1fr_82px] gap-[24px] min-h-[116px] py-[15px_0_23px] border-b border-border">
                <span
                  /* token-lint-disable-next-line no-direct-var -- route node marker needs 2px ring in primary color; no Tailwind utility for 2px box-shadow ring */
                  className="absolute left-[-41px] top-[25px] w-[11px] h-[11px] rounded-full border-[3px] border-accent-2 bg-primary shadow-[0_0_0_2px_theme(colors.primary.DEFAULT)]"
                  aria-hidden="true"
                />
                <div>
                  <label className="block text-text-muted font-mono font-medium text-[9px] tracking-[.08em] uppercase">
                    Destination
                  </label>
                  <strong className="block mt-[7px] text-primary font-ui font-semibold text-[26px] leading-none tracking-[-0.01em]">
                    Singapore
                  </strong>
                  <small className="block mt-[7px] text-text-muted text-[11px]">
                    Changi International Airport
                  </small>
                </div>
                <span className="self-start pt-[16px] text-primary font-mono font-medium text-[12px] text-right">
                  SIN
                </span>
              </div>

              {/* Route Row 3: Travel Window */}
              <div className="relative grid grid-cols-[1fr_82px] gap-[24px] min-h-[116px] py-[15px_0_23px]">
                <span
                  /* token-lint-disable-next-line no-direct-var -- route node marker needs 2px ring in brass color; no Tailwind utility for 2px box-shadow ring */
                  className="absolute left-[-41px] top-[25px] w-[11px] h-[11px] rounded-full border-[3px] border-accent-2 bg-accent-3 shadow-[0_0_0_2px_var(--color-accent-3)]"
                  aria-hidden="true"
                />
                <div>
                  <label className="block text-text-muted font-mono font-medium text-[9px] tracking-[.08em] uppercase">
                    Travel window
                  </label>
                  <strong className="block mt-[7px] text-primary font-ui font-semibold text-[26px] leading-none tracking-[-0.01em]">
                    12–18 October
                  </strong>
                  <small className="block mt-[7px] text-text-muted text-[11px]">
                    Flexible by two days
                  </small>
                </div>
                <span className="self-start pt-[16px] text-primary font-mono font-medium text-[12px] text-right">
                  6 NTS
                </span>
              </div>
            </div>

            {/* Planner Action */}
            <div className="grid grid-cols-[1fr_auto] border-t border-border bg-surface-overlay max-[650px]:grid-cols-1">
              <p className="m-0 px-[24px] py-[19px] text-text-muted text-[12px]">
                Next: add the cards and point balances you already have.
              </p>
              <Link
                href="/plan"
                className="min-w-[210px] border-0 border-l border-border rounded-none bg-primary text-text-on-primary font-semibold text-[12px] max-[650px]:border-l-0 max-[650px]:border-t max-[650px]:min-h-[54px] flex items-center justify-center px-6"
              >
                Continue to your wallet →
              </Link>
            </div>
          </div>
        </section>

        {/* ── Recommendations Section ── */}
        <section className="bg-surface px-[62px] py-[70px_0_76px] max-[650px]:px-[22px] max-[650px]:py-[52px_0]">
          {/* Section Heading */}
          <div className="grid grid-cols-[1fr_1fr] items-end gap-[38px] pb-[25px] border-b border-border max-[960px]:grid-cols-1 max-[960px]:gap-[0]">
            <h2 className="font-display text-h2 leading-[1.05] tracking-[-0.015em] text-primary">
              A clear route<br />
              through the trade-offs.
            </h2>
            <p className="max-w-[500px] justify-self-end text-text-muted text-[14px] leading-[1.65] max-[960px]:justify-self-start max-[960px]:mt-[8px]">
              The recommendation is obvious at a glance. Cash cost, point usage, assumptions
              and provenance stay available without competing for attention.
            </p>
          </div>

          {/* Decision List */}
          <div className="mt-[28px] border-t border-border">
            {/* Row 1: Featured / Recommended */}
            {/* token-lint-disable-next-line no-direct-var -- featured decision row needs 34% opacity primary border; no Tailwind utility for arbitrary opacity on border-color */}
            <article className="relative grid grid-cols-[66px_1.6fr_1fr_180px_130px] gap-[22px] items-center min-h-[126px] border-b border-border bg-accent-2 border border-[theme(colors.primary.DEFAULT)/0.34] m-[0_-20px] p-[0_20px] max-[960px]:grid-cols-[50px_1.4fr_1fr_130px] max-[650px]:grid-cols-[36px_1fr] max-[650px]:gap-[14px] max-[650px]:m-0 max-[650px]:p-[28px_12px_22px]">
              {/* Recommended notch */}
              <span className="absolute -top-[11px] left-[88px] inline-block px-[8px] py-[4px] text-text-on-primary bg-accent-4 font-mono font-medium text-[9px] uppercase tracking-[.06em] leading-none max-[650px]:top-[-11px] max-[650px]:left-[12px]">
                Recommended
              </span>

              <span className="text-text-muted font-mono font-medium text-[11px] max-[650px]:text-[10px]">01</span>
              <h3 className="text-primary font-ui font-semibold text-[24px] leading-[1.15] tracking-[-0.005em] max-[650px]:text-[20px]">
                Transfer, then book
              </h3>
              <span className="text-text-muted text-[12px] leading-[1.55] max-[960px]:hidden">
                Flights with bank points; hotel on the card that earns the most.
              </span>
              <span className="text-text font-ui font-semibold text-[22px] leading-none tabular-nums tracking-[-0.01em] max-[650px]:text-[18px]">
                ₹96,400
                <small className="block mt-[7px] text-text-muted font-ui font-normal text-[10px] leading-none tracking-normal">
                  effective trip cost
                </small>
              </span>
              <span className="text-savings-text font-mono font-semibold text-[11px] tabular-nums max-[650px]:text-[10px]">
                Save ₹38,600
              </span>
              <button className="justify-self-end py-[9px] border-0 border-b border-primary text-primary bg-transparent font-semibold text-[11px] max-[650px]:justify-self-start max-[650px]:col-span-2">
                Why this? +
              </button>
            </article>

            {/* Row 2 */}
            <article className="grid grid-cols-[66px_1.6fr_1fr_180px_130px] gap-[22px] items-center min-h-[126px] border-b border-border max-[960px]:grid-cols-[50px_1.4fr_1fr_130px] max-[650px]:grid-cols-[36px_1fr] max-[650px]:gap-[14px] max-[650px]:p-[22px_0]">
              <span className="text-text-muted font-mono font-medium text-[11px] max-[650px]:text-[10px]">02</span>
              <h3 className="text-primary font-ui font-semibold text-[24px] leading-[1.15] tracking-[-0.005em] max-[650px]:text-[20px]">
                Keep your points
              </h3>
              <span className="text-text-muted text-[12px] leading-[1.55] max-[960px]:hidden">
                Pay cash today and preserve every transferable point.
              </span>
              <span className="text-text font-ui font-semibold text-[22px] leading-none tabular-nums tracking-[-0.01em] max-[650px]:text-[18px]">
                ₹135,000
                <small className="block mt-[7px] text-text-muted font-ui font-normal text-[10px] leading-none tracking-normal">
                  cash total
                </small>
              </span>
              <span className="text-savings-text font-mono font-semibold text-[11px] tabular-nums max-[650px]:text-[10px]">
                0 points used
              </span>
              <button className="justify-self-end py-[9px] border-0 border-b border-primary text-primary bg-transparent font-semibold text-[11px] max-[650px]:justify-self-start max-[650px]:col-span-2">
                Compare +
              </button>
            </article>

            {/* Row 3 */}
            <article className="grid grid-cols-[66px_1.6fr_1fr_180px_130px] gap-[22px] items-center min-h-[126px] max-[960px]:grid-cols-[50px_1.4fr_1fr_130px] max-[650px]:grid-cols-[36px_1fr] max-[650px]:gap-[14px] max-[650px]:p-[22px_0]">
              <span className="text-text-muted font-mono font-medium text-[11px] max-[650px]:text-[10px]">03</span>
              <h3 className="text-primary font-ui font-semibold text-[24px] leading-[1.15] tracking-[-0.005em] max-[650px]:text-[20px]">
                Lowest cash today
              </h3>
              <span className="text-text-muted text-[12px] leading-[1.55] max-[960px]:hidden">
                Use more points to minimize immediate out-of-pocket spend.
              </span>
              <span className="text-text font-ui font-semibold text-[22px] leading-none tabular-nums tracking-[-0.01em] max-[650px]:text-[18px]">
                ₹21,800
                <small className="block mt-[7px] text-text-muted font-ui font-normal text-[10px] leading-none tracking-normal">
                  + 112,000 points
                </small>
              </span>
              <span className="text-savings-text font-mono font-semibold text-[11px] tabular-nums max-[650px]:text-[10px]">
                Cash-first option
              </span>
              <button className="justify-self-end py-[9px] border-0 border-b border-primary text-primary bg-transparent font-semibold text-[11px] max-[650px]:justify-self-start max-[650px]:col-span-2">
                Compare +
              </button>
            </article>
          </div>

          {/* Provenance Footer */}
          <div className="grid grid-cols-[1fr_auto] gap-[20px] mt-[30px] py-[17px] border-t border-border border-b border-border text-text-muted font-mono text-[10px] leading-[1.5]">
            <span>
              <b className="text-primary font-medium">Verified inputs:</b> flight fixture · hotel fixture · card rules · transfer rules
            </span>
            <span className="justify-self-end">
              Last verified 25 Jul 2026 · sample data
            </span>
          </div>
        </section>

        {/* Swatch strip is Phase 0 proof scaffolding — do not build */}
      </main>
    </div>
  );
}