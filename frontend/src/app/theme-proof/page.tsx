import { resolveTheme } from "@/lib/theme/resolver";
import { DestinationStamp } from "@/components/product/destination-stamp";
import { JAPAN_ATLAS_STAMP } from "@/lib/design/philatelic-assets";

export default async function ThemeProofPage({
  searchParams,
}: {
  searchParams: Promise<{ theme?: string }>;
}) {
  const params = await searchParams;
  const resolved = resolveTheme(params.theme === "japan" ? "JP" : null);
  const themeClass = `theme-${resolved.globalTheme}`;

  return (
    <div className={`${themeClass} min-h-screen bg-bg text-text p-8 md:p-12 space-y-12 font-ui`}>
      <header>
        <h1 className="font-display display-hero mb-2">Theme Proof: {resolved.globalTheme}</h1>
        <p className="text-text-muted">
          Testing theme resolution. Toggle:{" "}
          <a href="?theme=japan" className="underline text-primary">Japan</a> |{" "}
          <a href="?theme=natural" className="underline text-primary">Natural</a>
        </p>
      </header>

      <section className="space-y-6">
        <h2 className="text-h2">Typography & Ink</h2>
        <div className="p-6 bg-surface shadow-1 rounded-none border-2 border-border space-y-4 max-w-2xl">
          <p className="text-text text-body">Primary ink on surface (body copy).</p>
          <p className="text-text-muted text-body">Muted ink on surface (secondary copy).</p>
          <p className="text-text-faint text-caption">Faint ink (decorative metadata only).</p>
          <p className="font-mono text-sm">Roboto Mono (metadata)</p>
          <div className="font-display display-mark text-2xl">Poiret One Mark</div>
        </div>
      </section>

      <section className="space-y-6">
        <h2 className="text-h2">Surfaces & Depth</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          <div className="p-8 bg-bg border-2 border-border shadow-1 rounded-none">
            <h3 className="font-ui font-semibold mb-2">Background</h3>
            <p className="text-text-muted text-sm">bg + shadow-1</p>
          </div>
          <div className="p-8 bg-surface border-2 border-border shadow-2 rounded-none">
            <h3 className="font-ui font-semibold mb-2">Surface</h3>
            <p className="text-text-muted text-sm">surface + shadow-2</p>
          </div>
          <div className="p-8 bg-surface-raised border-2 border-border shadow-3 rounded-none">
            <h3 className="font-ui font-semibold mb-2">Raised</h3>
            <p className="text-text-muted text-sm">raised + shadow-3</p>
          </div>
        </div>
      </section>

      <section className="space-y-6">
        <h2 className="text-h2">Action & Meaning</h2>
        <div className="flex flex-wrap gap-6">
          <button className="px-6 py-3 bg-primary text-primary-foreground hover:bg-primary-hover border-2 border-border shadow-1 font-semibold transition-colors active:translate-y-0 active:shadow-none">
            Primary Action
          </button>
          
          <div className="px-4 py-2 border border-success text-success-text bg-success/10 rounded-full flex items-center">
            Success Status
          </div>
          
          <div className="px-4 py-2 border border-warning text-warning-text bg-warning/10 rounded-full flex items-center">
            Warning Status
          </div>
          
          <div className="px-4 py-2 border-2 border-savings text-savings-text bg-savings/10 rounded-none font-mono text-sm flex items-center shadow-1">
            Savings Value
          </div>
        </div>
      </section>

      <section className="space-y-6">
        <h2 className="text-h2">Nested theme scope</h2>
        <p className="max-w-2xl text-text-muted">
          Diagnostic token harness for Tailwind inline theme resolution. The inner swatch deliberately overrides the
          surrounding proof theme.
        </p>
        <div className="grid max-w-2xl grid-cols-1 gap-4 md:grid-cols-2">
          <div className="border-2 border-border bg-surface p-4 shadow-1">
            <p className="mb-3 font-mono text-caption text-text-muted">Outer scope primary</p>
            <div
              aria-label="Outer theme primary swatch"
              className="h-16 border-2 border-border bg-primary"
              data-testid="outside-primary"
            />
          </div>
          <div className={`${resolved.globalTheme === "japan" ? "theme-natural" : "theme-japan"} border-2 border-border bg-surface p-4 shadow-1`}>
            <p className="mb-3 font-mono text-caption text-text-muted">Inner override primary</p>
            <div
              aria-label="Inner theme primary swatch"
              className="h-16 border-2 border-border bg-primary"
              data-testid="inside-primary"
            />
          </div>
        </div>
      </section>

      {resolved.globalTheme === "japan" ? (
        <section className="space-y-6">
          <div className="max-w-3xl">
            <h2 className="text-h2">Philatelic artifact proof</h2>
            <p className="mt-2 text-text-muted">
              Diagnostic harness only. Product placement happens only when a caller supplies an explicit approved
              destination artifact.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-8 md:grid-cols-2">
            <div className="border-2 border-border bg-surface p-6 shadow-1" data-testid="stamp-proof-decorative">
              <h3 className="mb-4 font-ui text-h3 font-semibold">Decorative specimen</h3>
              <DestinationStamp asset={JAPAN_ATLAS_STAMP} size="thumbnail" decorative />
            </div>

            <div className="border-2 border-border bg-surface p-6 shadow-1" data-testid="stamp-proof-informative">
              <h3 className="mb-4 font-ui text-h3 font-semibold">Informative specimen</h3>
              <DestinationStamp
                asset={JAPAN_ATLAS_STAMP}
                size="feature"
                routeLabel="DEL → TYO"
                dateLabel="2026-11-03"
                issued
              />
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}
