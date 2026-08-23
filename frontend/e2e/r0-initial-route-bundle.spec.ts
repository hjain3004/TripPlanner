import { expect, test } from "@playwright/test";

const BASE = "http://localhost:3000";
const FORBIDDEN_PACKAGE_MARKERS = [
  {
    packageName: "gsap",
    markers: ["_gsap", "TimelineLite", "TweenLite", "CSSPlugin", "GreenSock"],
  },
  {
    packageName: "maplibre-gl",
    markers: ["maplibre-gl", "maplibregl", "MapLibre"],
  },
  {
    packageName: "lenis",
    markers: ["lenis", "Lenis"],
  },
] as const;

function isLocalJavascriptResponse(responseUrl: string, contentType: string): boolean {
  const url = new URL(responseUrl);
  if (url.origin !== BASE) return false;
  if (!url.pathname.endsWith(".js") && !contentType.toLowerCase().includes("javascript")) {
    return false;
  }
  return url.pathname.startsWith("/_next/");
}

test.describe("R0 initial route bundle", () => {
  test("landing route does not fetch heavy optional libraries", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "Initial-route bundle gate is desktop-only.");

    const inspectedScripts: { url: string; body: string }[] = [];

    page.on("response", async (response) => {
      const headers = response.headers();
      const contentType = headers["content-type"] ?? "";
      const responseUrl = response.url();
      if (!isLocalJavascriptResponse(responseUrl, contentType)) return;

      try {
        await response.finished();
        inspectedScripts.push({
          url: responseUrl,
          body: await response.text(),
        });
      } catch {
        // The assertion below requires a successfully inspected Next chunk, so collection errors
        // cannot make this test pass vacuously.
      }
    });

    await page.goto(BASE + "/", { waitUntil: "networkidle" });
    await page.waitForLoadState("networkidle");

    expect(
      inspectedScripts.some((script) => new URL(script.url).pathname.startsWith("/_next/static/")),
      "at least one first-party Next.js script must be inspected"
    ).toBe(true);

    const offending = inspectedScripts.flatMap((script) => {
      return FORBIDDEN_PACKAGE_MARKERS.flatMap(({ packageName, markers }) => {
        const matches = markers.filter((marker) => script.body.includes(marker));
        return matches.map((marker) => `${new URL(script.url).pathname} contains ${packageName}:${marker}`);
      });
    });

    expect(offending).toEqual([]);
  });
});
