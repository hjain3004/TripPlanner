"use client";

import { useEffect } from "react";

export function MSWProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    const init = async () => {
      try {
        if (process.env.NEXT_PUBLIC_API_MODE === "mock" || !process.env.NEXT_PUBLIC_API_MODE) {
          const { worker } = await import("./browser");
          await worker.start({ onUnhandledRequest: "bypass", quiet: true });
          (globalThis as unknown as Record<string, unknown>).__msw_worker = worker;
        }
      } catch {
        // MSW registration can fail in production (no public/mockServiceWorker.js).
        // This is non-fatal.
      }
    };
    init();
  }, []);

  return <>{children}</>;
}
