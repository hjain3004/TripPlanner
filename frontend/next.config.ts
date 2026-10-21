import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  turbopack: {
    root: __dirname,
  },
  // The production image sets NEXT_OUTPUT=standalone to get a minimal, self-contained
  // server bundle. Default builds (dev, Playwright's webServer) are unchanged.
  ...(process.env.NEXT_OUTPUT === "standalone" ? { output: "standalone" as const } : {}),
};

export default nextConfig;
