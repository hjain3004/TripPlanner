import { test, expect, type Page } from "@playwright/test";

/**
 * A3 Task 11 — the authenticated wallet journey.
 *
 * Routes are stubbed with `page.route` and the state is held in the test, which
 * is this repo's existing pattern (see `cp2-profile.spec.ts`): it keeps the
 * journey deterministic and lets the final step assert the one thing a live
 * backend makes awkward to force — that an *intentionally empty* authenticated
 * wallet stays empty and is never swapped for a demo wallet.
 */

const BASE = "http://localhost:3000";

test.use({ serviceWorkers: "block" });

type Entry = {
  id: string;
  card_id: string;
  nickname: string;
  last4: string | null;
  statement_day: number | null;
  opened_on: string | null;
  points_balances: Record<string, number>;
  added_at: string;
  version: number;
};

const CARD_PRODUCTS = [
  { card_id: "axis-atlas", display_name: "Atlas", issuer: "Axis Bank", is_eligible: true },
  { card_id: "hdfc-infinia", display_name: "Infinia Metal", issuer: "HDFC Bank", is_eligible: true },
];

function projectionOf(entries: Entry[]) {
  const cardIds = [...new Set(entries.map((e) => e.card_id))].sort();
  const balances: Record<string, number> = {};
  for (const entry of entries) {
    for (const [currency, amount] of Object.entries(entry.points_balances)) {
      const current = balances[currency];
      if (current === undefined || amount > current) balances[currency] = amount;
    }
  }
  return { card_ids: cardIds, points_balances: balances };
}

/** Stub the account surface, keeping wallet state in the test. */
async function mockWallet(page: Page, initial: Entry[] = []) {
  const state = { entries: [...initial], seq: initial.length };

  await page.route("**/auth/me", (route) =>
    route.fulfill({
      json: { id: "msw-user-001", email: "student@example.com", status: "active" },
    }),
  );

  await page.route("**/account/card-products", (route) =>
    route.fulfill({ json: CARD_PRODUCTS }),
  );

  await page.route("**/account/wallet/projection", (route) =>
    route.fulfill({ json: projectionOf(state.entries) }),
  );

  await page.route("**/account/wallet", async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      await route.fulfill({ json: state.entries });
      return;
    }
    const body = request.postDataJSON() as Partial<Entry>;
    state.seq += 1;
    const entry: Entry = {
      id: `e2e-wallet-${state.seq}`,
      card_id: body.card_id as string,
      nickname: body.nickname ?? "Card",
      last4: body.last4 ?? null,
      statement_day: null,
      opened_on: null,
      points_balances: body.points_balances ?? {},
      added_at: "2026-10-19T12:00:00Z",
      version: 1,
    };
    state.entries.push(entry);
    await route.fulfill({ status: 201, json: entry });
  });

  await page.route("**/account/wallet/*", async (route) => {
    const request = route.request();
    const id = new URL(request.url()).pathname.split("/").pop();
    // Playwright gives later-registered routes precedence, so this wildcard
    // also matches /account/wallet/projection. Hand that back to its own
    // handler instead of treating "projection" as an entry id -- the same
    // path-shadowing hazard the FastAPI router avoids by declaring the literal
    // route before /wallet/{entry_id}.
    if (id === "projection") {
      await route.fulfill({ json: projectionOf(state.entries) });
      return;
    }
    const index = state.entries.findIndex((e) => e.id === id);
    if (index === -1) {
      await route.fulfill({
        status: 404,
        json: { detail: { code: "wallet_entry_not_found", message: "No such wallet entry." } },
      });
      return;
    }
    if (request.method() === "DELETE") {
      state.entries.splice(index, 1);
      await route.fulfill({ status: 204, body: "" });
      return;
    }
    const body = request.postDataJSON() as Record<string, unknown>;
    const current = state.entries[index];
    if (body.expected_version !== current.version) {
      await route.fulfill({
        status: 409,
        json: {
          detail: {
            code: "wallet_version_conflict",
            message: "This wallet entry changed since you loaded it.",
          },
        },
      });
      return;
    }
    const patched: Entry = {
      ...current,
      version: current.version + 1,
      nickname: typeof body.nickname === "string" ? body.nickname : current.nickname,
      points_balances:
        (body.points_balances as Record<string, number> | undefined) ??
        current.points_balances,
    };
    state.entries[index] = patched;
    await route.fulfill({ json: patched });
  });

  return state;
}

test.describe("A3: the authenticated wallet journey", () => {
  test("add, edit and remove a card, and see what planning will use", async ({ page }) => {
    const state = await mockWallet(page);

    // 1-2. Signed in, on /wallet.
    await page.goto(`${BASE}/wallet`);
    await expect(page.getByTestId("wallet-signed-out")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Your wallet", level: 1 })).toBeVisible();
    await expect(page.getByTestId("wallet-empty")).toBeVisible();
    await expect(page.getByTestId("wallet-projection-empty")).toBeVisible();

    // The privacy promise is on the page, not buried in a tooltip.
    await expect(page.getByTestId("wallet-privacy-note")).toContainText("never stores");

    // 3. Add a known card product with a points balance.
    await page.getByTestId("wallet-card-product").selectOption("hdfc-infinia");
    await page.getByTestId("wallet-nickname").fill("Everyday card");
    await page.getByTestId("wallet-last4").fill("1234");
    await page.getByTestId("wallet-points-currency").fill("hdfc-reward-points");
    await page.getByTestId("wallet-points-amount").fill("1200");
    await page.getByTestId("wallet-add-submit").click();

    await expect(page.getByTestId("wallet-entry")).toHaveCount(1);
    await expect(page.getByTestId("wallet-entry")).toContainText("Everyday card");
    await expect(page.getByTestId("wallet-entry")).toContainText("ends 1234");
    await expect(page.getByTestId("wallet-projection-cards")).toContainText("hdfc-infinia");
    await expect(page.getByTestId("wallet-projection-points")).toContainText(
      "hdfc-reward-points",
    );

    // 4. Edit it.
    const entryId = state.entries[0].id;
    await page.getByTestId(`wallet-edit-${entryId}`).click();
    await page.getByTestId("wallet-edit-nickname").fill("Travel card");
    await page.getByTestId("wallet-edit-save").click();
    await expect(page.getByTestId("wallet-entry")).toContainText("Travel card");

    // 8. Remove it — only after an explicit confirmation.
    await page.getByTestId(`wallet-remove-${entryId}`).click();
    await expect(page.getByTestId("wallet-remove-confirm")).toBeVisible();
    await page.getByTestId("wallet-remove-confirm-yes").click();

    // 9. The authenticated empty wallet stays empty: no demo wallet appears.
    await expect(page.getByTestId("wallet-entry")).toHaveCount(0);
    await expect(page.getByTestId("wallet-empty")).toBeVisible();
    await expect(page.getByTestId("wallet-projection-empty")).toBeVisible();
    await expect(page.getByTestId("wallet-projection")).not.toContainText("hdfc-infinia");
  });

  test("a destructive removal can be declined", async ({ page }) => {
    const state = await mockWallet(page, [
      {
        id: "e2e-wallet-1",
        card_id: "hdfc-infinia",
        nickname: "Keep me",
        last4: null,
        statement_day: null,
        opened_on: null,
        points_balances: {},
        added_at: "2026-10-19T12:00:00Z",
        version: 1,
      },
    ]);

    await page.goto(`${BASE}/wallet`);
    await page.getByTestId("wallet-remove-e2e-wallet-1").click();
    await page.getByTestId("wallet-remove-confirm-no").click();

    await expect(page.getByTestId("wallet-remove-confirm")).toHaveCount(0);
    await expect(page.getByTestId("wallet-entry")).toHaveCount(1);
    expect(state.entries).toHaveLength(1);
  });

  test("a stale edit surfaces a typed conflict instead of overwriting", async ({ page }) => {
    await mockWallet(page, [
      {
        id: "e2e-wallet-1",
        card_id: "hdfc-infinia",
        nickname: "Original",
        last4: null,
        statement_day: null,
        opened_on: null,
        points_balances: {},
        added_at: "2026-10-19T12:00:00Z",
        version: 7, // the UI holds version 7; we force the server to disagree
      },
    ]);
    await page.route("**/account/wallet/e2e-wallet-1", (route) =>
      route.fulfill({
        status: 409,
        json: {
          detail: {
            code: "wallet_version_conflict",
            message: "This wallet entry changed since you loaded it.",
          },
        },
      }),
    );

    await page.goto(`${BASE}/wallet`);
    await page.getByTestId("wallet-edit-e2e-wallet-1").click();
    await page.getByTestId("wallet-edit-nickname").fill("Mine wins");
    await page.getByTestId("wallet-edit-save").click();

    await expect(page.getByTestId("wallet-conflict")).toBeVisible();
    await expect(page.getByTestId("wallet-reload")).toBeVisible();
    // The optimistic value was not silently kept.
    await expect(page.getByTestId("wallet-entry")).toContainText("Original");
  });

  test("the signed-out state offers a sign-in action", async ({ page }) => {
    await page.route("**/auth/me", (route) => route.fulfill({ status: 401, json: {} }));
    await page.goto(`${BASE}/wallet`);
    await expect(page.getByTestId("wallet-signed-out")).toBeVisible();
    await expect(page.getByTestId("wallet-list")).toHaveCount(0);
  });

  test("the header links to the wallet", async ({ page }, testInfo) => {
    // The header nav block is `max-[960px]:hidden` in the approved composition,
    // so "Your wallet" is only reachable from the header at desktop widths.
    // That is a pre-existing navigation limitation, not something A3 changed:
    // every other test in this file passes at 390px and 768px, so the wallet
    // *page* is responsive -- it simply has no mobile header entry point yet.
    // Logged in DEVIATIONS.md rather than papered over here.
    const width = testInfo.project.use.viewport?.width ?? 0;
    test.skip(width < 960, "header nav is hidden below 960px by design");

    await mockWallet(page);
    await page.goto(`${BASE}/`);
    const link = page.getByRole("link", { name: "Your wallet" });
    await expect(link).toBeVisible();
    await link.click();
    await expect(page).toHaveURL(/\/wallet$/);
  });
});

test.describe("A3: the planning review shows the session wallet", () => {
  // 5-7. The review step must render the wallet the *session* will use, which
  // the server snapshotted at session start -- not a live account re-read.
  function reviewingSession(wallet: { card_ids: string[]; points_balances: Record<string, number> }) {
    return {
      id: "e2e-session-1",
      user_id: "msw-user-001",
      status: "reviewing",
      version: 3,
      created_at: "2026-10-19T12:00:00Z",
      updated_at: "2026-10-19T12:00:00Z",
      expires_at: "2026-11-18T12:00:00Z",
      current_question: null,
      suggested_question_ids: [],
      progress: { completed: 8, minimum_total: 8, maximum_total: 12, status: "reviewing" },
      answers: {},
      events: [],
      assistance_status: "idle",
      interview_llm_calls: 0,
      assistance_pending: false,
      assistance_diagnostics: [],
      pending_answer: null,
      contradictions: [],
      pending_profile_updates: [],
      wallet,
      brief: null,
      planning_job_id: null,
    };
  }

  async function openReview(
    page: Page,
    wallet: { card_ids: string[]; points_balances: Record<string, number> },
  ) {
    await page.route("**/auth/me", (route) =>
      route.fulfill({
        json: { id: "msw-user-001", email: "student@example.com", status: "active" },
      }),
    );
    const session = reviewingSession(wallet);
    await page.route("**/planning/sessions", (route) =>
      route.fulfill({ status: 201, json: session }),
    );
    await page.route("**/planning/sessions/**", (route) => route.fulfill({ json: session }));
    await page.goto(`${BASE}/plan/conversation`);
  }

  test("names the cards the session will plan with", async ({ page }) => {
    await openReview(page, {
      card_ids: ["hdfc-infinia"],
      points_balances: { "hdfc-reward-points": 1200 },
    });

    const summary = page.getByTestId("session-wallet-summary");
    await expect(summary).toBeVisible();
    await expect(page.getByTestId("session-wallet-cards")).toContainText("hdfc-infinia");
    await expect(page.getByTestId("session-wallet-points")).toContainText(
      "hdfc-reward-points",
    );
    await expect(page.getByTestId("session-wallet-empty")).toHaveCount(0);
  });

  test("says cash only when the session wallet is empty", async ({ page }) => {
    await openReview(page, { card_ids: [], points_balances: {} });

    await expect(page.getByTestId("session-wallet-empty")).toBeVisible();
    await expect(page.getByTestId("session-wallet-empty")).toContainText("cash only");
    await expect(page.getByTestId("session-wallet-cards")).toHaveCount(0);
  });
});
