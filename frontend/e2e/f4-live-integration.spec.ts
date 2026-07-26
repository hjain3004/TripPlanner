import { test, expect } from "@playwright/test";

const BASE = "http://localhost:3000";
const PLAN_URL = BASE + "/plan";

test.describe("F4 live integration", () => {
  test("wizard submits to live backend and receives structured error", async ({ page }) => {
    // This test requires the backend running on port 8000
    test.skip(process.env.NEXT_PUBLIC_API_MODE !== "live", "live integration test requires NEXT_PUBLIC_API_MODE=live");

    await page.goto(PLAN_URL);

    // Step 1 — Trip basics
    await expect(page.locator("h1")).toContainText("Where are you going?");
    await page.fill("#origin", "DEL");
    await page.fill("#destination", "SIN");
    await page.fill("#start-date", "2026-08-01");
    await page.fill("#end-date", "2026-08-05");
    await page.fill("#travelers", "2");
    await page.locator("button").filter({ hasText: "Next" }).click();

    // Step 2 — Wallet
    await expect(page.locator("h1")).toContainText("Your cards and points");
    await page.fill("#card-ids", "hdfc-infinia");
    await page.fill("#points", "voyager-prime:140000");
    await page.locator("button").filter({ hasText: "Next" }).click();

    // Step 3 — Preferences
    await expect(page.locator("h1")).toContainText("Trip preferences");
    await page.fill("#interests", "nature, food");
    await page.locator("button").filter({ hasText: "Next" }).click();

    // Step 4 — Review
    await expect(page.locator("h1")).toContainText("Review your trip");
    await page.locator("button").filter({ hasText: "Next" }).click();

    // Step 5 — Submit
    await expect(page.locator("h1")).toContainText("Ready to generate");
    await page.locator("button").filter({ hasText: "Generate plan" }).click();

    // The request goes to the real backend, which returns 202 with a job_id.
    // The pipeline then fails because HostedFreeTier raises LLMCallError.
    // The UI should reach "failed" or "polling" state.
    await expect(page.getByText("Something went wrong").or(page.getByTestId("stage-tracker"))).toBeVisible({ timeout: 15000 });
  });

  test("API health endpoint responds correctly", async ({ request }) => {
    test.skip(process.env.NEXT_PUBLIC_API_MODE !== "live", "requires live backend");

    const resp = await request.get("http://127.0.0.1:8000/health");
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body).toEqual({ status: "ok" });
  });

  test("API plan endpoint returns 202 with job_id", async ({ request }) => {
    test.skip(process.env.NEXT_PUBLIC_API_MODE !== "live", "requires live backend");

    const resp = await request.post("http://127.0.0.1:8000/plan", {
      data: {
        raw_request: "Plan a trip from Delhi to Singapore from August 1 to August 5 2026 for 2 travelers. I have HDFC Infinia and 140000 Voyager Prime points.",
        test_mode: true,
      },
    });
    expect(resp.status()).toBe(202);
    const body = await resp.json();
    expect(body).toHaveProperty("job_id");
    expect(typeof body.job_id).toBe("string");

    // Poll the job — it should fail quickly because HostedFreeTier raises immediately
    const jobId = body.job_id;
    const pollResp = await request.get(`http://127.0.0.1:8000/plan/${jobId}`);
    expect(pollResp.status()).toBe(200);
    const status = await pollResp.json();
    expect(status).toHaveProperty("status");
    // Status may be "failed" or "pending" depending on timing
    expect(["pending", "failed", "in_progress", "needs_clarification"]).toContain(status.status);
  });
});
