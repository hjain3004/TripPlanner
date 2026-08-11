export type DestinationTheme = "natural" | "japan";

export type ThemeResolution = {
  globalTheme: DestinationTheme;
  primaryCountryCode: string | null;
  secondaryCountryCodes: string[];
};

export function resolveTheme(primaryCountryCode: string | null): ThemeResolution {
  const normalizedPrimary = primaryCountryCode?.trim().toUpperCase() || null;
  // Japan is the only allowlisted destination pack. Unknown falls back to natural.
  const globalTheme: DestinationTheme = normalizedPrimary === "JP" ? "japan" : "natural";

  return {
    globalTheme,
    primaryCountryCode: normalizedPrimary,
    secondaryCountryCodes: [],
  };
}
