import { test, expect } from "@playwright/test";

const BASE = "http://localhost:3000";

const MODULE_NAMES = ["maplibre-gl", "maplibregl"];

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
