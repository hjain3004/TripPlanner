import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.use({ serviceWorkers: "block" });
const id = "cp3-browser-session";
const flight = { id: "flight_preferences", prompt: "Which cabin suits your overnight flight?", phase: "core", answer_kind: "flight", required: false, allow_delegate: true, control: { type: "flight", allow_skip: true, options: [{ value: "economy", label: "Economy" }, { value: "business", label: "Business" }] } };
const rhythm = { ...flight, id: "daily_rhythm", answer_kind: "rhythm", prompt: "What pace feels right?", control: { type: "rhythm", allow_skip: true, options: [{ value: "relaxed", label: "Relaxed" }, { value: "packed", label: "Packed" }] } };
const candidate = { cabin: "business", max_stops: 0, schedule: "morning", checked_baggage: true, airport_flexible: false, seat: "aisle" };
type State = ReturnType<typeof session>;
function session(overrides: Record<string, unknown> = {}) {
  return { id, user_id: "fixture-user", status: "interviewing", version: 1, created_at: "2026-10-10T00:00:00Z", updated_at: "2026-10-10T00:00:00Z", expires_at: "2026-11-09T00:00:00Z", current_question: flight, question_catalog: [flight, rhythm], suggested_question_ids: [], progress: { completed: 3, minimum_total: 8, maximum_total: 12, status: "interviewing" }, answers: {} as Record<string, unknown>, events: [] as unknown[], assistance_status: "not_run", assistance_diagnostics: [] as string[], interview_llm_calls: 0, pending_answer: null as unknown, contradictions: [] as unknown[], pending_profile_updates: [], brief: null as unknown, planning_job_id: null, wallet: { card_ids: [], points_balances: {} }, ...overrides };
}
async function fixture(page: Page, initial = session()) {
  let state: State = initial;
  const answers: Record<string, unknown>[] = [];
  const interpretations: Record<string, unknown>[] = [];
  let confirmations = 0;
  await page.route(`**/planning/sessions/${id}`, (route) => route.fulfill({ json: state }));
  await page.route(`**/planning/sessions/${id}/interpret`, async (route) => {
    interpretations.push(route.request().postDataJSON());
    state = { ...state, version: state.version + 1, interview_llm_calls: 1, assistance_status: "complete", pending_answer: { question_id: "flight_preferences", payload: candidate }, events: [{ id: "ack", kind: "assistant_acknowledgement", text: "An aisle seat and a daytime flight sound like a good fit.", created_at: "2026-10-10T00:00:00Z" }] };
    await route.fulfill({ json: state });
  });
  await page.route(`**/planning/sessions/${id}/answers`, async (route) => {
    const body = route.request().postDataJSON();
    answers.push(body);
    state = { ...state, version: state.version + 1, pending_answer: null, current_question: rhythm, answers: { ...state.answers, [body.question_id]: { ...body, answered_at: "2026-10-10T00:00:00Z" } } };
    await route.fulfill({ json: state });
  });
  await page.route(`**/planning/sessions/${id}/amend`, async (route) => {
    const body = route.request().postDataJSON();
    answers.push(body);
    state = { ...state, version: state.version + 1, pending_answer: null, contradictions: [], answers: { ...state.answers, [body.question_id]: { ...body, delegated: false, answered_at: "2026-10-10T00:00:00Z" } } };
    await route.fulfill({ json: state });
  });
  await page.route(`**/planning/sessions/${id}/confirm`, async (route) => { confirmations++; await route.fulfill({ status: 409, json: { detail: "Fixture does not start jobs" } }); });
  await page.goto(`/plan/conversation?session=${id}`);
  return { answers, interpretations, confirmations: () => confirmations, setState: (next: State) => { state = next; } };
}

test("interpretation is a preview, resumes, and saves the exact candidate only on explicit Continue", async ({ page }) => {
  const requests = await fixture(page);
  await page.getByLabel("Describe your preference").fill("I want an aisle seat and a daytime flight");
  await page.getByRole("button", { name: "Interpret preference", exact: true }).click();
  const preview = page.getByRole("region", { name: "Suggested answer" });
  await expect(preview).toContainText("aisle");
  await expect(page.getByRole("radio", { name: "Business", exact: true })).not.toBeChecked();
  expect(requests.answers).toHaveLength(0);
  await page.reload();
  await expect(preview).toContainText("morning");
  await page.getByRole("button", { name: "Use suggested answer" }).click();
  await expect(page.getByRole("radio", { name: "Business", exact: true })).toBeChecked();
  expect(requests.answers).toHaveLength(0);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: rhythm.prompt })).toBeVisible();
  expect(requests.answers[0].payload).toEqual(candidate);
  expect(requests.answers[0].expected_version).toBe(2);
  expect(requests.interpretations[0]).toMatchObject({ question_id: "flight_preferences", expected_version: 1, text: "I want an aisle seat and a daytime flight" });
  await page.reload();
  await expect(page.getByRole("region", { name: "Suggested answer" })).not.toBeVisible();
});

test("editing a used proposal preserves its other fields", async ({ page }) => {
  const requests = await fixture(page, session({ pending_answer: { question_id: "flight_preferences", payload: candidate }, interview_llm_calls: 1 }));
  await page.getByRole("button", { name: "Use suggested answer" }).click();
  await page.getByRole("radio", { name: "Economy", exact: true }).press("Space");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: rhythm.prompt })).toBeVisible();
  expect(requests.answers[0].payload).toEqual({ ...candidate, cabin: "economy" });
});

test("a candidate with no cabin preference still saves its explicit seat preference", async ({ page }) => {
  const proposed = { ...candidate, cabin: "no_preference" };
  const requests = await fixture(page, session({ pending_answer: { question_id: "flight_preferences", payload: proposed } }));
  await page.getByRole("button", { name: "Use suggested answer" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: rhythm.prompt })).toBeVisible();
  expect(requests.answers[0]).toMatchObject({ delegated: false, payload: proposed });
});

test("dismissing a proposal permits a typed replacement without saving the suggestion", async ({ page }) => {
  const requests = await fixture(page, session({ pending_answer: { question_id: "flight_preferences", payload: candidate } }));
  await page.getByRole("button", { name: "Dismiss suggestion" }).click();
  await expect(page.getByRole("region", { name: "Suggested answer" })).not.toBeVisible();
  await page.getByRole("radio", { name: "Economy", exact: true }).press("Space");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: rhythm.prompt })).toBeVisible();
  expect(requests.answers[0].payload).toMatchObject({ cabin: "economy", seat: "no_preference" });
});

test("degraded and exhausted assistance retain typed controls and persisted diagnostics", async ({ page }) => {
  const requests = await fixture(page, session({ assistance_status: "degraded", assistance_diagnostics: ["unavailable", "interrupted", "budget_exhausted"], interview_llm_calls: 2 }));
  await expect(page.getByRole("status").filter({ hasText: "Assistance is limited" })).toContainText("interrupted");
  await expect(page.getByRole("button", { name: "Interpret preference", exact: true })).toBeDisabled();
  await page.reload();
  await expect(page.getByText("Assistance is limited", { exact: false })).toBeVisible();
  await page.getByRole("radio", { name: "Economy", exact: true }).press("Space");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: rhythm.prompt })).toBeVisible();
  expect(requests.interpretations).toHaveLength(0);
  expect(requests.answers).toHaveLength(1);
});

test("before the core checkpoint the remaining call is reserved for adaptive review", async ({ page }) => {
  await fixture(page, session({ interview_llm_calls: 1 }));
  await expect(page.getByText("The remaining assistance call is reserved for your trip review.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Interpret preference", exact: true })).toBeDisabled();
  await expect(page.getByRole("radio", { name: "Economy", exact: true })).toBeEnabled();
});

test("contradictions block Build until a referenced answer is explicitly amended", async ({ page }) => {
  const requests = await fixture(page, session({ status: "reviewing", current_question: null, brief: { flight_preferences: candidate, daily_rhythm: { pace: "packed" }, assumptions: [], applied_profile_sections: [] }, answers: { flight_preferences: { question_id: "flight_preferences", payload: candidate, delegated: false }, daily_rhythm: { question_id: "daily_rhythm", payload: { pace: "packed" }, delegated: false } }, contradictions: [{ answer_ids: ["flight_preferences", "daily_rhythm"], clarification: "Please review your daytime flight and packed first day." }] }));
  await expect(page.getByRole("button", { name: "Build my trip" })).toBeDisabled();
  expect(requests.confirmations()).toBe(0);
  await page.getByRole("button", { name: "Review Flight Preferences", exact: true }).click();
  await expect(page.getByRole("heading", { name: flight.prompt })).toBeVisible();
  await page.getByRole("button", { name: "Go back to the previous question" }).click();
  await expect(page.getByRole("button", { name: "Build my trip" })).toBeDisabled();
  expect(requests.answers).toHaveLength(0);
  await page.getByRole("button", { name: "Review Flight Preferences", exact: true }).click();
  await expect(page.getByRole("radio", { name: "Business", exact: true })).toBeChecked();
  await page.getByRole("radio", { name: "Economy", exact: true }).press("Space");
  await page.getByRole("button", { name: "Save answer", exact: true }).click();
  await expect(page.getByRole("button", { name: "Build my trip" })).toBeEnabled();
  expect(requests.answers[0]).toMatchObject({ question_id: "flight_preferences", payload: { ...candidate, cabin: "economy" } });
  expect(requests.confirmations()).toBe(0);
});

test("personalized server prompts and acknowledgements remain visible after refresh", async ({ page }) => {
  const prompt = "For your anniversary, would you prefer a quieter flight?";
  await fixture(page, session({ current_question: { ...flight, prompt }, events: [{ id: "ack", kind: "assistant_acknowledgement", text: "I will keep your anniversary plans in mind.", created_at: "2026-10-10T00:00:00Z" }] }));
  await expect(page.getByRole("heading", { name: prompt })).toBeVisible();
  await expect(page.getByText("I will keep your anniversary plans in mind.")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: prompt })).toBeVisible();
  await expect(page.getByText("I will keep your anniversary plans in mind.")).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test("interpretation network failures leave typed answers usable", async ({ page }) => {
  const requests = await fixture(page);
  await page.route(`**/planning/sessions/${id}/interpret`, (route) => route.abort());
  await page.getByLabel("Describe your preference").fill("I prefer daytime flights");
  await page.getByRole("button", { name: "Interpret preference", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Interpretation could not be completed" })).toBeVisible();
  await page.getByRole("radio", { name: "Economy", exact: true }).press("Space");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: rhythm.prompt })).toBeVisible();
  expect(requests.answers).toHaveLength(1);
});

test("required fiscal and trip facts have typed controls and no interpretation action", async ({ page }) => {
  await fixture(page, session({ current_question: { ...flight, id: "budget_and_objective", prompt: "Choose your optimization priority", answer_kind: "budget_objective", control: { type: "budget_objective", allow_skip: false, options: [{ value: "balanced", label: "Balance cash and value" }] } } }));
  await expect(page.getByRole("radio", { name: "Balance cash and value" })).toBeVisible();
  await expect(page.getByLabel("Describe your preference")).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Interpret preference", exact: true })).not.toBeVisible();
});

test("a validated server failure discloses degradation and consumes the reserved call", async ({ page }) => {
  await fixture(page);
  await page.route(`**/planning/sessions/${id}/interpret`, (route) => route.fulfill({ json: session({ version: 2, assistance_status: "degraded", assistance_diagnostics: ["invalid_response"], interview_llm_calls: 1 }) }));
  await page.getByLabel("Describe your preference").fill("A quiet flight");
  await page.getByRole("button", { name: "Interpret preference", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Assistance is limited" })).toContainText("could not be validated");
  await expect(page.getByRole("button", { name: "Interpret preference", exact: true })).toBeDisabled();
  await expect(page.getByRole("radio", { name: "Economy", exact: true })).toBeEnabled();
  await expect(page.getByRole("region", { name: "Suggested answer" })).not.toBeVisible();
});

test("refreshing during assistance polls saved state and resumes without another interpretation", async ({ page }) => {
  const pending = session({ status: "awaiting_assistant", current_question: null, interview_llm_calls: 1 });
  const requests = await fixture(page, pending);
  let completed = false;
  let reads = 0;
  await page.route(`**/planning/sessions/${id}`, (route) => {
    reads++;
    return route.fulfill({ json: completed ? session({ version: 3, interview_llm_calls: 1, pending_answer: { question_id: "flight_preferences", payload: candidate }, assistance_status: "complete" }) : pending });
  });
  await expect(page.getByRole("region", { name: "Assistance in progress" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("region", { name: "Assistance in progress" })).toBeVisible();
  await expect.poll(() => reads).toBeGreaterThan(1);
  completed = true;
  await expect(page.getByRole("region", { name: "Suggested answer" })).toContainText("aisle");
  await expect(page.getByRole("region", { name: "Assistance in progress" })).not.toBeVisible();
  expect(requests.interpretations).toHaveLength(0);
  expect(requests.answers).toHaveLength(0);
});

test("an interrupted assistance poll recovers to typed controls with persisted diagnostics", async ({ page }) => {
  const pending = session({ status: "awaiting_assistant", current_question: null, interview_llm_calls: 1 });
  const requests = await fixture(page, pending);
  await expect(page.getByRole("region", { name: "Assistance in progress" })).toBeVisible();
  let recovered = false;
  await page.route(`**/planning/sessions/${id}`, (route) => route.fulfill(recovered ? { json: session({ version: 3, assistance_status: "degraded", assistance_diagnostics: ["interrupted"], interview_llm_calls: 1 }) } : { status: 503, json: { detail: "Temporary read failure" } }));
  await expect(page.getByRole("alert").filter({ hasText: "could not check assistance progress" })).toBeVisible();
  recovered = true;
  await page.getByRole("button", { name: "Check progress again" }).click();
  await expect(page.getByRole("radio", { name: "Economy", exact: true })).toBeEnabled();
  await expect(page.getByRole("status").filter({ hasText: "Assistance is limited" })).toContainText("interrupted");
  expect(requests.interpretations).toHaveLength(0);
});

test("a resumed review candidate uses the amendment route and leaves the saved answer unchanged until Save", async ({ page }) => {
  const saved = { ...candidate, cabin: "economy", seat: "window" };
  const requests = await fixture(page, session({ status: "reviewing", current_question: null, brief: { flight_preferences: saved, assumptions: [], applied_profile_sections: [] }, answers: { flight_preferences: { question_id: "flight_preferences", payload: saved, delegated: false } }, pending_answer: { question_id: "flight_preferences", payload: candidate }, interview_llm_calls: 2 }));
  await expect(page.getByRole("region", { name: "Pending answer suggestion" })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Review suggested answer" }).click();
  await expect(page.getByRole("radio", { name: "Economy", exact: true })).toBeChecked();
  await expect(page.getByRole("region", { name: "Suggested answer" })).toContainText("aisle");
  expect(requests.answers).toHaveLength(0);
  await page.getByRole("button", { name: "Use suggested answer" }).click();
  await expect(page.getByRole("radio", { name: "Business", exact: true })).toBeChecked();
  expect(requests.answers).toHaveLength(0);
  await page.getByRole("button", { name: "Save answer", exact: true }).click();
  await expect(page.getByRole("button", { name: "Build my trip" })).toBeVisible();
  expect(requests.answers[0].payload).toEqual(candidate);
  await expect(page.getByRole("region", { name: "Pending answer suggestion" })).not.toBeVisible();
});

test("a temporary interpretation response polls without inventing or saving a candidate", async ({ page }) => {
  const requests = await fixture(page);
  let complete = false;
  await page.route(`**/planning/sessions/${id}/interpret`, (route) => route.fulfill({ json: session({ status: "awaiting_assistant", current_question: null, version: 2, interview_llm_calls: 1 }) }));
  await page.getByLabel("Describe your preference").fill("A quiet morning flight");
  await page.getByRole("button", { name: "Interpret preference", exact: true }).click();
  await expect(page.getByRole("region", { name: "Assistance in progress" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Suggested answer" })).not.toBeVisible();
  await page.route(`**/planning/sessions/${id}`, (route) => route.fulfill({ json: complete ? session({ version: 3, interview_llm_calls: 1, pending_answer: { question_id: "flight_preferences", payload: candidate } }) : session({ status: "awaiting_assistant", current_question: null, version: 2, interview_llm_calls: 1 }) }));
  complete = true;
  await expect(page.getByRole("region", { name: "Suggested answer" })).toContainText("morning");
  expect(requests.answers).toHaveLength(0);
});

test("interpreting an affected review answer preserves typed state until explicit amendment", async ({ page }) => {
  const payloads = {
    trip_essentials: { origin: "DEL", destination: "SIN", start_date: "2026-11-01", end_date: "2026-11-05", travelers: 1 },
    purpose_and_party: { purpose: "leisure", adults: 1, children_ages: [] },
    budget_and_objective: { budget_minor: null, currency: "INR", travel_style: "balanced", objective: "balanced", points_priority: "best_value" },
    flight_preferences: { ...candidate, cabin: "economy" },
    stay_preferences: { lodging_styles: [], neighborhood_priorities: [], room_count: 1, room_needs: [], location_price_tradeoff: "balanced" },
    daily_rhythm: { pace: "relaxed", day_start: "normal", evening_style: "quiet", downtime_minutes: null, transit_tolerance_minutes: null, day_trip_appetite: "none" },
    experiences_and_food: { interests: [], food_interests: [], iconic_local_balance: "balanced", nightlife: false, shopping: false },
    hard_constraints: { has_constraints: false, dietary: [], accessibility: [], exclusions: [], immovable_events: [] },
  };
  const answers = Object.fromEntries(Object.entries(payloads).map(([question_id, payload]) => [question_id, { question_id, payload, delegated: false }]));
  const requests = await fixture(page, session({ status: "reviewing", current_question: null, answers, brief: { flight_preferences: payloads.flight_preferences, assumptions: [], applied_profile_sections: [] }, interview_llm_calls: 1 }));
  await page.getByRole("button", { name: "Amend Flight Preferences" }).click();
  await page.getByLabel("Describe your preference").fill("An aisle seat on a quiet morning flight");
  await page.getByRole("button", { name: "Interpret preference", exact: true }).click();
  await expect(page.getByRole("region", { name: "Suggested answer" })).toContainText("aisle");
  await expect(page.getByRole("radio", { name: "Economy", exact: true })).toBeChecked();
  expect(requests.answers).toHaveLength(0);
  await page.getByRole("button", { name: "Use suggested answer" }).click();
  await page.getByRole("button", { name: "Save answer", exact: true }).click();
  await expect(page.getByRole("button", { name: "Build my trip" })).toBeVisible();
  expect(requests.answers[0].payload).toEqual(candidate);
});

for (const status of ["interviewing", "reviewing"] as const) {
  test(`${status} interpretation reservations recover automatically after refresh`, async ({ page }) => {
    const saved = { ...candidate, cabin: "economy" };
    const pending = session({ status, assistance_pending: true, assistance_status: "degraded", assistance_diagnostics: ["interrupted", "interrupted"], interview_llm_calls: 1, current_question: status === "interviewing" ? flight : null, answers: { flight_preferences: { question_id: "flight_preferences", payload: saved, delegated: false } }, brief: status === "reviewing" ? { flight_preferences: saved, assumptions: [], applied_profile_sections: [] } : null });
    const requests = await fixture(page, pending);
    let recovered = false;
    let reads = 0;
    await page.route(`**/planning/sessions/${id}`, (route) => {
      reads++;
      const next = recovered ? { ...pending, version: 3, assistance_pending: false, assistance_status: "degraded", assistance_diagnostics: ["interrupted", "interrupted"] } : pending;
      requests.setState(next);
      return route.fulfill({ json: next });
    });
    await expect(page.getByRole("region", { name: "Assistance in progress" })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("region", { name: "Assistance in progress" })).toBeVisible();
    await expect(page.getByText("Assistance is limited.", { exact: false })).not.toBeVisible();
    if (status === "interviewing") {
      await expect(page.getByRole("radio", { name: "Economy", exact: true })).toBeDisabled();
      await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeDisabled();
      await expect(page.getByRole("button", { name: "Interpret preference", exact: true })).toBeDisabled();
    } else {
      await expect(page.getByRole("button", { name: "Build my trip" })).toBeDisabled();
      await expect(page.getByRole("button", { name: "Amend Flight Preferences" })).toBeDisabled();
    }
    await expect.poll(() => reads).toBeGreaterThan(1);
    recovered = true;
    await expect(page.getByRole("region", { name: "Assistance in progress" })).not.toBeVisible();
    await expect(page.getByText("An assistance request was interrupted.", { exact: true })).toHaveCount(1);
    if (status === "reviewing") await page.getByRole("button", { name: "Amend Flight Preferences" }).click();
    await page.getByRole("radio", { name: "Business", exact: true }).press("Space");
    await page.getByRole("button", { name: status === "reviewing" ? "Save answer" : "Continue", exact: true }).click();
    if (status === "reviewing") await expect(page.getByRole("button", { name: "Build my trip" })).toBeEnabled();
    else await expect(page.getByRole("heading", { name: rhythm.prompt })).toBeVisible();
    expect(requests.answers[0]).toMatchObject({ question_id: "flight_preferences", expected_version: 3, payload: { ...saved, cabin: "business" } });
    expect(requests.interpretations).toHaveLength(0);
    expect(requests.confirmations()).toBe(0);
  });
}
