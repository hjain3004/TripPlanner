import { resolveTheme } from "@/lib/theme/resolver";

export default function ThemeProofPage({
  searchParams,
}: {
  searchParams: { theme?: string };
}) {
  const isNatural = searchParams.theme === "natural";
  // The resolver uses "JP" for Japan, and anything else for natural fallback
  const resolved = resolveTheme(isNatural ? "US" : "JP");
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
        <div className="p-6 bg-surface shadow-1 rounded-sm border border-border space-y-4 max-w-2xl">
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
          <div className="p-8 bg-bg border-2 border-border shadow-1 rounded-sm">
            <h3 className="font-ui font-semibold mb-2">Background</h3>
            <p className="text-text-muted text-sm">bg + shadow-1</p>
          </div>
          <div className="p-8 bg-surface border-2 border-border shadow-2 rounded-sm">
            <h3 className="font-ui font-semibold mb-2">Surface</h3>
            <p className="text-text-muted text-sm">surface + shadow-2</p>
          </div>
          <div className="p-8 bg-surface-raised border-2 border-border shadow-3 rounded-sm">
            <h3 className="font-ui font-semibold mb-2">Raised</h3>
            <p className="text-text-muted text-sm">raised + shadow-3</p>
          </div>
        </div>
      </section>

      <section className="space-y-6">
        <h2 className="text-h2">Action & Meaning</h2>
        <div className="flex flex-wrap gap-6">
          <button className="px-6 py-3 bg-primary text-primary-foreground hover:bg-primary-hover border-2 border-border shadow-1 font-semibold transition-all hover:-translate-y-0.5 active:translate-y-0 active:shadow-none">
            Primary Action
          </button>
          
          <div className="px-4 py-2 border border-success text-success-text bg-success/10 rounded-full flex items-center">
            Success Status
          </div>
          
          <div className="px-4 py-2 border border-warning text-warning-text bg-warning/10 rounded-full flex items-center">
            Warning Status
          </div>
          
          <div className="px-4 py-2 border-2 border-savings text-savings-text bg-savings/10 rounded-sm font-mono text-sm flex items-center shadow-1">
            Savings Value
          </div>
        </div>
      </section>
    </div>
  );
}
