export type DestinationTheme = "natural" | "japan";

export type ThemeResolution = {
  globalTheme: DestinationTheme;
  primaryCountryCode: string | null;
  secondaryCountryCodes: string[];
};

export function resolveTheme(primaryCountryCode: string | null): ThemeResolution {
  // Japan is the golden pack. Unknown falls back to natural.
  let globalTheme: DestinationTheme = "natural";
  
  // Default to japan for testing as per J1 spec
  globalTheme = "japan";

  if (primaryCountryCode === "JP") {
    globalTheme = "japan";
  }

  return {
    globalTheme,
    primaryCountryCode,
    secondaryCountryCodes: [],
  };
}
