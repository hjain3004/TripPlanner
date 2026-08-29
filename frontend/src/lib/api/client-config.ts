import { createClient } from "./generated/client/client.gen";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// Authenticated planning sessions use the server-owned cookie session. The
// CSRF token is echoed by the mutation helper below; credentials must always
// travel with same-site and local development requests.
export const apiClient = createClient({ baseUrl: API_BASE, credentials: "include" });

export function csrfHeaders(): Record<string, string> {
  if (typeof document === "undefined") return {};
  const token = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("tp_csrf="))
    ?.slice("tp_csrf=".length);
  return token ? { "X-CSRF-Token": decodeURIComponent(token) } : {};
}
