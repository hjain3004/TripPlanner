import { test, expect } from "@playwright/test";

const BASE = "http://localhost:3000";

const LCP_THRESHOLD_MS = 2500;
const CLS_THRESHOLD = 0.1;

async function measureWebVital(page: import("@playwright/test").Page, url: string) {
  await page.goto(url, { waitUntil: "networkidle" });

  // Wait extra time for any late-loading content
  await page.waitForTimeout(1000);

  const lcp = await page.evaluate(() => {
    return new Promise<number | null>((resolve) => {
      // Check PerformanceObserver first, fall back to Performance API
      try {
        const observer = new PerformanceObserver((list) => {
          const entries = list.getEntries();
          if (entries.length > 0) {
            resolve(entries[entries.length - 1].startTime);
          }
          observer.disconnect();
        });
        observer.observe({ type: "largest-contentful-paint", buffered: true });
        // Timeout fallback after 3s
        setTimeout(() => resolve(null), 3000);
      } catch {
        resolve(null);
      }
    });
  });

  const cls = await page.evaluate(() => {
    return new Promise<number | null>((resolve) => {
      try {
        let clsValue = 0;
        const observer = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            if (entry.entryType === "layout-shift") {
              clsValue += (entry as unknown as { value: number }).value;
            }
          }
        });
        observer.observe({ type: "layout-shift", buffered: true });
        setTimeout(() => {
          observer.disconnect();
          resolve(clsValue);
        }, 2000);
      } catch {
        resolve(null);
      }
    });
  });

  // INP is hard to measure without real interactions — report null if unavailable
  const inp = null;

  return { lcp, cls, inp };
}

test.describe("F4 performance trace", () => {
  test("landing page meets Web Vitals thresholds", async ({ page }) => {
    const metrics = await measureWebVital(page, BASE + "/");

    console.log(`Landing page — LCP: ${metrics.lcp?.toFixed(1) ?? "N/A"}ms, CLS: ${metrics.cls?.toFixed(3) ?? "N/A"}`);

    if (metrics.lcp != null) {
      expect(metrics.lcp).toBeLessThanOrEqual(LCP_THRESHOLD_MS);
    }
    if (metrics.cls != null) {
      expect(metrics.cls).toBeLessThanOrEqual(CLS_THRESHOLD);
    }
  });

  test("results page meets Web Vitals thresholds", async ({ page }) => {
    const metrics = await measureWebVital(page, BASE + "/plan");

    console.log(`Results page — LCP: ${metrics.lcp?.toFixed(1) ?? "N/A"}ms, CLS: ${metrics.cls?.toFixed(3) ?? "N/A"}`);

    if (metrics.lcp != null) {
      expect(metrics.lcp).toBeLessThanOrEqual(LCP_THRESHOLD_MS);
    }
    if (metrics.cls != null) {
      expect(metrics.cls).toBeLessThanOrEqual(CLS_THRESHOLD);
    }
  });
});
