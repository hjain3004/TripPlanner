import { test, expect, type Page } from "@playwright/test";

const SESSION = "cp2-e2e-session";

test.use({ serviceWorkers: "block" });

function session(overrides: Record<string, unknown> = {}) {
  return {
    id: SESSION,
    user_id: "cp2-user",
    status: "interviewing",
    version: 0,
    created_at: "2026-08-29T00:00:00Z",
    updated_at: "2026-08-29T00:00:00Z",
    expires_at: "2026-09-28T00:00:00Z",
    current_question: {
      id: "trip_essentials",
      prompt: "Where are you headed, and what are your travel dates?",
      phase: "core",
      answer_kind: "trip_essentials",
      required: true,
      allow_delegate: false,
      control: { type: "trip_essentials", fields: ["origin", "destination", "start_date", "end_date", "travelers"], allow_skip: false, options: [] },
    },
    question_catalog: [
      {
        id: "trip_essentials",
        prompt: "Where are you headed, and what are your travel dates?",
        phase: "core",
        answer_kind: "trip_essentials",
        required: true,
        allow_delegate: false,
        control: { type: "trip_essentials", fields: ["origin", "destination", "start_date", "end_date", "travelers"], allow_skip: false, options: [] },
      },
    ],
    suggested_question_ids: [],
    progress: { completed: 0, minimum_total: 8, maximum_total: 12, status: "interviewing" },
    answers: {},
    events: [],
    assistance_status: "not_run",
    pending_profile_updates: [],
    brief: null,
    planning_job_id: null,
    ...overrides,
  };
}

async function mockSession(page: Page, value = session()) {
  await page.route("**/planning/sessions", async (route) => {
    if (route.request().method() === "POST") await route.fulfill({ status: 201, json: value });
    else await route.continue();
  });
  await page.route(`**/planning/sessions/${SESSION}`, async (route) => {
    if (route.request().method() === "GET") await route.fulfill({ json: value });
    else await route.continue();
  });
}

test.describe("CP2 conversational planning", () => {
  test("shows an honest sign-in requirement when the session API rejects access", async ({ page }) => {
    await page.route("**/planning/sessions", (route) => route.fulfill({ status: 401, json: { detail: "Not authenticated" } }));
    await page.goto("/plan/conversation");
    await expect(page.getByRole("alert").filter({ hasText: "Sign in" })).toContainText("Sign in");
    await expect(page.getByText("Where are you headed")).not.toBeVisible();
  });

  test("renders the server-issued typed control without local option vocabularies", async ({ page }) => {
    const value = session({
      current_question: {
        id: "flight_preferences", prompt: "Choose your cabin", phase: "core", answer_kind: "flight", required: true, allow_delegate: true,
        control: { type: "flight", allow_skip: true, options: [{ value: "server_choice", label: "Server supplied cabin" }] },
      },
    });
    await mockSession(page, value);
    await page.goto("/plan/conversation");
    await expect(page.getByText("Server supplied cabin")).toBeVisible();
    await expect(page.getByText("Business")).not.toBeVisible();
  });

  test("hydrates a resumed trip and preserves the saved traveler count", async ({ page }) => {
    const value = session({
      version: 1,
      answers: { trip_essentials: { question_id: "trip_essentials", delegated: false, payload: { origin: "DEL", destination: "SIN", start_date: "2026-11-01", end_date: "2026-11-05", travelers: 3 }, client_event_id: "e1", answered_at: "2026-08-29T00:00:00Z" } },
    });
    await mockSession(page, value);
    await page.goto(`/plan/conversation?session=${SESSION}`);
    await expect(page.getByLabel("travelers")).toHaveValue("3");
    await page.reload();
    await expect(page.getByLabel("travelers")).toHaveValue("3");
  });

  test("keeps the consultation within the mobile viewport", async ({ page }) => {
    await mockSession(page);
    await page.goto("/plan/conversation");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });
});
