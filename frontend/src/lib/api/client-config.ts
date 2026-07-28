import { createClient } from "./client/client.gen";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const apiClient = createClient({ baseUrl: API_BASE });
