import { describe, expect, it } from "vitest";
import { resolveTheme } from "../src/lib/theme/resolver";

describe("theme resolver", () => {
  it.each([
    { input: null, expectedTheme: "natural", expectedPrimary: null },
    { input: "JP", expectedTheme: "japan", expectedPrimary: "JP" },
    { input: "jp", expectedTheme: "japan", expectedPrimary: "JP" },
    { input: "US", expectedTheme: "natural", expectedPrimary: "US" },
    { input: "ZZ", expectedTheme: "natural", expectedPrimary: "ZZ" },
  ] as const)("resolves $input to $expectedTheme", ({ input, expectedTheme, expectedPrimary }) => {
    const resolved = resolveTheme(input);

    expect(resolved.globalTheme).toBe(expectedTheme);
    expect(resolved.primaryCountryCode).toBe(expectedPrimary);
    expect(resolved.secondaryCountryCodes).toEqual([]);
  });

  it("trims and normalizes explicit country codes without guessing from cities", () => {
    expect(resolveTheme(" jp ").globalTheme).toBe("japan");
    expect(resolveTheme("Tokyo").globalTheme).toBe("natural");
    expect(resolveTheme("").globalTheme).toBe("natural");
  });
});
