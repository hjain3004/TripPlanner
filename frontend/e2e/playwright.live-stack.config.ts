import { defineConfig } from "@playwright/test";

/**
 * D1 - genuine full-stack smoke. Runs ONLY against the production-like Compose stack
 * (scripts/d1-smoke.sh starts it). There is deliberately no webServer: nothing here
 * starts, mocks or stubs the application. Service workers are deliberately ALLOWED: a
 * mock-mode build would register the MSW worker, and the spec asserts that none is. There
 * is no page.route - every request in the journey reaches the real FastAPI backend
 * through the same-origin reverse proxy.
 */
export default defineConfig({
  testDir: ".",
  testMatch: "d1-live-stack-smoke.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  timeout: 90_000,
  use: {
    baseURL: process.env.TRIPWISE_STACK_URL ?? "http://localhost:8080",
    browserName: "chromium",
    viewport: { width: 1440, height: 900 },
    serviceWorkers: "allow",
  },
});
