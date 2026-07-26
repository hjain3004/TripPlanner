import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
  },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium", viewport: { width: 1440, height: 900 }, baseURL: "http://localhost:3000" },
    },
    {
      name: "mobile",
      use: { browserName: "chromium", viewport: { width: 390, height: 844 }, baseURL: "http://localhost:3000" },
    },
    {
      name: "tablet",
      use: { browserName: "chromium", viewport: { width: 768, height: 1024 }, baseURL: "http://localhost:3000" },
    },
    {
      name: "reduced-motion",
      use: {
        browserName: "chromium",
        viewport: { width: 1440, height: 900 },
        baseURL: "http://localhost:3000",
        contextOptions: { reducedMotion: "reduce" },
      },
    },
  ],
  webServer: {
    command: "npm run build && npm run start",
    port: 3000,
    cwd: "..",
    reuseExistingServer: !process.env.CI,
  },
});
