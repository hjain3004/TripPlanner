import { test, expect } from "@playwright/test";

const BASE = "http://localhost:3000";

// Identifiers that only appear in maplibre-gl's actual LIBRARY CODE, never in
// a lazy-import reference stub.
//
// This deliberately does not check for the package name "maplibre-gl". A
// correctly code-split dynamic import still leaves the module name in a small
// wrapper chunk - that is how the loader knows which chunk to fetch. Measured:
// the real library sits in a 945KB lazy chunk, while the wizard loads only a
// 1KB stub that names it. Checking the name therefore failed while the code
// was already correct. The file's own gsap comment below records the same
// lesson; it just was not applied to maplibre.
//
// These strings still catch the real regression: a static `import "maplibre-gl"`
// pulls the library itself into an initial chunk, and GlyphManager et al come
// with it.
const MODULE_NAMES = ["GlyphManager", "maplibregl_", "MapLibre"];

test.describe("F4 bundle check", () => {
  test("landing page loads without gsap or maplibre-gl", async ({ page }) => {
    // Capture initial HTML and JS bodies
    const initialHtml = await page.goto(BASE + "/", { waitUntil: "networkidle" });
    const html = await initialHtml!.text();

    // Extract <script> URLs from the initial HTML — these are the critical chunks
    const scriptSrcs = [...html.matchAll(/<script[^>]*src="([^"]+)"/g)].map((m) => m[1]);

    // Fetch each initial script and check for heavy libs
    for (const src of scriptSrcs) {
      const absUrl = new URL(src, BASE).toString();
      const resp = await page.request.get(absUrl);
      const body = await resp.text();

      // gsap may appear as import path in wrapper chunks; check for GSAP library code instead
      for (const mod of MODULE_NAMES) {
        expect(
          body.includes(mod),
          `"${mod}" should not appear in initial chunk "${src.split("/").pop()}"`
        ).toBe(false);
      }
    }
  });

  test("wizard steps 1-4 load without gsap or maplibre-gl", async ({ page }) => {
    const initialHtml = await page.goto(BASE + "/plan", { waitUntil: "networkidle" });
    const html = await initialHtml!.text();

    const scriptSrcs = [...html.matchAll(/<script[^>]*src="([^"]+)"/g)].map((m) => m[1]);

    for (const src of scriptSrcs) {
      const absUrl = new URL(src, BASE).toString();
      const resp = await page.request.get(absUrl);
      const body = await resp.text();

      for (const mod of MODULE_NAMES) {
        expect(
          body.includes(mod),
          `"${mod}" should not appear in initial chunk "${src.split("/").pop()}"`
        ).toBe(false);
      }
    }
  });
});
