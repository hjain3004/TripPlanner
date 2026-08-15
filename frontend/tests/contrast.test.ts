import { describe, it, expect } from "vitest";
import path from "path";
import {
  wcagContrast,
  parseToRgb,
  alphaCompose,
  type Rgb,
} from "./culori-adaptor";
import {
  parseThemeFile,
  parseBridge,
} from "../scripts/parse-theme";

const THEMES_DIR = path.resolve(__dirname, "../src/themes");
const BASE_CSS = path.join(THEMES_DIR, "base.css");
const JAPAN_CSS = path.join(THEMES_DIR, "japan.css");

// ---------------------------------------------------------------------------
// 1. Token-completeness
// ---------------------------------------------------------------------------
describe("theme token completeness", () => {
  const japan = parseThemeFile(JAPAN_CSS);
  const bridge = parseBridge(BASE_CSS);

  for (const mapping of bridge) {
    it(`${mapping.var} → ${mapping.thVar} exists in theme`, () => {
      expect(japan.tokens).toHaveProperty(mapping.thVar);
    });
  }

  it("every --th-* in theme has a bridge mapping", () => {
    for (const thKey of Object.keys(japan.tokens)) {
      if (thKey.startsWith("--th-font-")) continue;
      const found = bridge.some((m) => m.thVar === thKey);
      expect(found, `${thKey} should have a bridge mapping`).toBe(true);
    }
  });
});

// ---------------------------------------------------------------------------
// 2. WCAG contrast pairs
// ---------------------------------------------------------------------------
type TokenSet = Record<string, string>;

function c(spec: string): Rgb {
  return parseToRgb(spec);
}

function ratio(a: string, b: string): number {
  return Math.round(wcagContrast(c(a), c(b)) * 100) / 100;
}

function ratioT(a: string, b: string): number {
  return wcagContrast(c(a), c(b));
}

describe("WCAG contrast pairs (Singapore theme)", () => {
  const T: TokenSet = {
    bg: "oklch(0.947 0.013 87)",
    surface: "oklch(0.979 0.008 91)",
    border: "oklch(0.28 0.01 145 / 0.10)",
    text: "oklch(0.281 0.007 145)",
    textMuted: "oklch(0.525 0.014 157)",
    textFaint: "oklch(0.660 0.014 157)",
    onPrimary: "oklch(0.979 0.008 91)",
    primary: "oklch(0.320 0.042 181)",
    primaryHover: "oklch(0.270 0.042 181)",
    accent4: "oklch(0.536 0.135 30)",
    success: "oklch(0.580 0.120 155)",
    successText: "oklch(0.450 0.120 155)",
    warning: "oklch(0.700 0.130 75)",
    warningText: "oklch(0.450 0.130 75)",
    danger: "oklch(0.550 0.180 25)",
    savings: "oklch(0.660 0.097 82)",
    savingsText: "oklch(0.450 0.097 82)",
  };

  // body text ≥ 4.5:1
  it("text on bg ≥ 4.5:1", () => {
    expect(ratio(T.text, T.bg)).toBeGreaterThanOrEqual(4.5);
  });
  it("text on surface ≥ 4.5:1", () => {
    expect(ratio(T.text, T.surface)).toBeGreaterThanOrEqual(4.5);
  });

  // muted text ≥ 3:1 (AA Large / non-text minimum)
  it("text-muted on bg ≥ 3:1", () => {
    expect(ratio(T.textMuted, T.bg)).toBeGreaterThanOrEqual(3);
  });
  it("text-muted on surface ≥ 3:1", () => {
    expect(ratio(T.textMuted, T.surface)).toBeGreaterThanOrEqual(3);
  });

  // on-primary on primary — inverse text on button ≥ 4.5:1
  it("on-primary on primary ≥ 4.5:1", () => {
    expect(ratio(T.onPrimary, T.primary)).toBeGreaterThanOrEqual(4.5);
  });

  // status text on bg (these -text tokens render on page bg, not on status bg)
  it("success-text on bg ≥ 3:1", () => {
    expect(ratio(T.successText, T.bg)).toBeGreaterThanOrEqual(3);
  });
  it("warning-text on bg ≥ 3:1", () => {
    expect(ratio(T.warningText, T.bg)).toBeGreaterThanOrEqual(3);
  });
  it("danger on bg ≥ 3:1", () => {
    expect(ratioT(T.danger, T.bg)).toBeGreaterThanOrEqual(3);
  });
  it("savings-text on bg ≥ 3:1", () => {
    expect(ratio(T.savingsText, T.bg)).toBeGreaterThanOrEqual(3);
  });

  // accent-4 (lacquer) on bg ≥ 3:1
  it("accent-4 (lacquer) on bg ≥ 3:1", () => {
    expect(ratio(T.accent4, T.bg)).toBeGreaterThanOrEqual(3);
  });

  // faint text — must be < 3:1 (decorative only)
  it("text-faint on bg < 3:1", () => {
    expect(ratio(T.textFaint, T.bg)).toBeLessThan(3);
  });

  // border composited over bg ≥ 1.2:1 (visual separation minimum)
  it("border (composited over bg) ≥ 1.2:1", () => {
    const bc = alphaCompose(c(T.border), c(T.bg));
    const br = wcagContrast(bc, c(T.bg));
    expect(br).toBeGreaterThanOrEqual(1.2);
  });

  // focus ring on bg ≥ 3:1
  it("focus ring (primary) on bg ≥ 3:1", () => {
    expect(ratio(T.primary, T.bg)).toBeGreaterThanOrEqual(3);
  });

  // golden values — freeze actual ratios
  it("golden: text-on-bg", () => {
    expect(ratioT(T.text, T.bg)).toBeCloseTo(12.43, 1);
  });
  it("golden: on-primary-on-primary", () => {
    expect(ratioT(T.onPrimary, T.primary)).toBeCloseTo(11.71, 1);
  });
  it("golden: savings-text-on-bg", () => {
    expect(ratioT(T.savingsText, T.bg)).toBeCloseTo(6.44, 1);
  });
});

describe("WCAG contrast pairs (Japan theme)", () => {
  const T: TokenSet = {
    bg: "oklch(0.958 0.012 75.4)",
    surface: "oklch(0.977 0.010 81.8)",
    border: "oklch(0.398 0.021 46.3)",
    text: "oklch(0.398 0.021 46.3)",
    textMuted: "oklch(0.507 0.019 46.4)",
    textFaint: "oklch(0.606 0.019 50.3)",
    onPrimary: "oklch(0.977 0.010 81.8)",
    primary: "oklch(0.398 0.021 46.3)",
    primaryHover: "oklch(0.338 0.016 43.0)",
    accent2: "oklch(0.902 0.019 43.2)",
    accent4: "oklch(0.642 0.033 65.6)",
    success: "oklch(0.577 0.042 139.2)",
    successText: "oklch(0.462 0.044 141.4)",
    warning: "oklch(0.709 0.094 80.4)",
    warningText: "oklch(0.468 0.072 78.7)",
    danger: "oklch(0.527 0.065 24.6)",
    savings: "oklch(0.633 0.074 75.8)",
    savingsText: "oklch(0.469 0.055 74.1)",
  };

  it("text on bg >= 4.5:1", () => {
    expect(ratio(T.text, T.bg)).toBeGreaterThanOrEqual(4.5);
  });
  it("text on surface >= 4.5:1", () => {
    expect(ratio(T.text, T.surface)).toBeGreaterThanOrEqual(4.5);
  });
  it("text-muted on bg >= 3:1", () => {
    expect(ratio(T.textMuted, T.bg)).toBeGreaterThanOrEqual(3);
  });
  it("on-primary on primary >= 4.5:1", () => {
    expect(ratio(T.onPrimary, T.primary)).toBeGreaterThanOrEqual(4.5);
  });
  it("success-text on bg >= 3:1", () => {
    expect(ratio(T.successText, T.bg)).toBeGreaterThanOrEqual(3);
  });
  it("warning-text on bg >= 3:1", () => {
    expect(ratio(T.warningText, T.bg)).toBeGreaterThanOrEqual(3);
  });
  it("danger on bg >= 3:1", () => {
    expect(ratioT(T.danger, T.bg)).toBeGreaterThanOrEqual(3);
  });
  it("savings-text on bg >= 3:1", () => {
    expect(ratio(T.savingsText, T.bg)).toBeGreaterThanOrEqual(3);
  });
  it("text-faint on bg is ~3.42:1", () => {
    expect(ratio(T.textFaint, T.bg)).toBeCloseTo(3.42, 1);
  });

  // TrustChip renders 11px text, which is AA *small* text and so needs 4.5:1 -
  // not the 3:1 the text-muted assertions guarantee. The chip paired
  // text-muted with accent-2 at 4.35:1 and failed the aXe check on the
  // results page. text on accent-2 is 6.95:1.
  it("trust-chip text on accent-2 >= 4.5:1 (11px is AA small text)", () => {
    expect(ratio(T.text, T.accent2)).toBeGreaterThanOrEqual(4.5);
  });
  it("text-muted on accent-2 is the 4.35:1 that failed - do not use it there", () => {
    expect(ratio(T.textMuted, T.accent2)).toBeLessThan(4.5);
  });
});

