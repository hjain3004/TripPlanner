import { setupWorker } from "msw/browser";
import { http, HttpResponse } from "msw";
import { handlers } from "./handlers";

export const worker = setupWorker(...handlers);

if (typeof globalThis !== "undefined") {
  (globalThis as unknown as Record<string, unknown>).__msw = { worker, http, HttpResponse };
}
