import {
  oklch,
  rgb,
  wcagLuminance as culoriLum,
  wcagContrast as culoriContrast,
  toGamut,
} from "culori";

export interface Rgb {
  r: number;
  g: number;
  b: number;
  alpha?: number;
}

export function parseToRgb(spec: string): Rgb {
  const c = oklch(spec);
  const r = rgb(c);
  const clamped = toGamut("rgb", "oklch")(r);
  const a = r.alpha ?? clamped.alpha ?? 1;
  return {
    r: clamped.r,
    g: clamped.g,
    b: clamped.b,
    alpha: a < 1 ? a : undefined,
  };
}

export function wcagLuminance(c: Rgb): number {
  return culoriLum({ mode: "rgb", r: c.r, g: c.g, b: c.b });
}

export function wcagContrast(a: Rgb, b: Rgb): number {
  return culoriContrast(
    { mode: "rgb", r: a.r, g: a.g, b: a.b },
    { mode: "rgb", r: b.r, g: b.g, b: b.b },
  );
}

export function alphaCompose(foreground: Rgb, background: Rgb): Rgb {
  const fa = foreground.alpha ?? 1;
  const aa = background.alpha ?? 1;
  const ao = fa + aa * (1 - fa);
  if (ao === 0) return { r: 0, g: 0, b: 0 };
  return {
    r: (foreground.r * fa + background.r * aa * (1 - fa)) / ao,
    g: (foreground.g * fa + background.g * aa * (1 - fa)) / ao,
    b: (foreground.b * fa + background.b * aa * (1 - fa)) / ao,
  };
}
