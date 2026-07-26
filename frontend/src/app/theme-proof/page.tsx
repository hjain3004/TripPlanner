export default function ThemeProofPage() {
  return (
    <div className="theme-singapore">
      <div className="bg-primary p-4" data-testid="outside-primary">
        Outside (mangrove)
      </div>
      <div className="theme-proof bg-primary p-4" data-testid="inside-primary">
        Inside (overridden)
      </div>
      <style>{` /* token-lint-disable-next-line no-color-literals -- theme-proof override */ .theme-proof {
          --th-primary: oklch(0.55 0.10 205);
        }
      `}</style>
    </div>
  );
}
