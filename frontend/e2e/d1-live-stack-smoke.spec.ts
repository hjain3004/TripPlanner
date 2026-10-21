import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { existsSync, readFileSync, writeFileSync } from "node:fs";

/**
 * D1 genuine full-stack smoke journey.
 *
 * Phase 1 (@phase1) runs against the freshly started stack; the orchestrator
 * (scripts/d1-smoke.sh) then restarts the BACKEND container and runs phase 2 (@phase2)
 * against the same data volume to prove what survives a restart and what does not.
 *
 * Everything below is real: a real Chromium, the real built Next.js bundle in live API
 * mode, the real reverse proxy and the real FastAPI backend with real SQLite files.
 * There is no MSW and no page.route. Account creation goes through the real API because
 * the product has no sign-in UI yet (a documented limitation in docs/DEPLOYMENT.md).
 */

const STATE_FILE = process.env.TRIPWISE_SMOKE_STATE;

// The smoke asserts on arbitrary real API payloads; `any` here is deliberate test-only typing.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ApiResult = { status: number; json: any };
type SmokeState = {
  email: string;
  password: string;
  walletEntryId: string;
  walletVersion: number;
  nickname: string;
  sessionId: string;
  sessionVersion: number;
  jobId: string;
  storageStatePath: string;
};

/** A real same-origin browser fetch, exactly like the app's own client (cookies + CSRF header). */
async function api(
  page: Page,
  method: string,
  path: string,
  body?: unknown,
  csrf: "auto" | "none" | string = "auto",
): Promise<ApiResult> {
  return page.evaluate(
    async ({ method, path, body, csrf }) => {
      const headers: Record<string, string> = {};
      if (body !== undefined) headers["Content-Type"] = "application/json";
      if (csrf === "auto") {
        const m = document.cookie.match(/(?:^|; )tp_csrf=([^;]*)/);
        if (m) headers["X-CSRF-Token"] = decodeURIComponent(m[1]);
      } else if (csrf !== "none") {
        headers["X-CSRF-Token"] = csrf;
      }
      const res = await fetch(`/api${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        credentials: "same-origin",
      });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let json: any = null;
      try {
        json = await res.json();
      } catch {
        /* no body */
      }
      return { status: res.status, json };
    },
    { method, path, body, csrf },
  );
}

function futureDate(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function readState(): SmokeState {
  if (!STATE_FILE || !existsSync(STATE_FILE)) {
    throw new Error("phase 2 needs the state file written by phase 1");
  }
  return JSON.parse(readFileSync(STATE_FILE, "utf8")) as SmokeState;
}

async function expectSampleModeNoLiveProviders(page: Page) {
  const ready = await api(page, "GET", "/health/ready", undefined, "none");
  expect(ready.status).toBe(200);
  expect(ready.json.status).toBe("ready");
  expect(ready.json.provider_mode).toBe("sample");
  expect(ready.json.live_providers_enabled).toEqual([]);
  expect(ready.json.checks).toEqual({ data_dir: "ok", accounts_db: "ok", knowledge_base: "ok" });
}

test.describe("@phase1 fresh stack", () => {
  test.skip(!STATE_FILE, "TRIPWISE_SMOKE_STATE is required (run via scripts/d1-smoke.sh)");

  test("frontend (live API mode) -> real backend: account, cookies, CSRF, wallet, planning session", async ({
    page,
    context,
  }) => {
    const stamp = Date.now();
    const email = `d1-smoke-${stamp}@example.com`;
    const password = `smoke-pass-${stamp}-long`;
    const nickname = `D1 smoke card ${stamp}`;

    await test.step("frontend loads in live API mode, with no mock service worker", async () => {
      const response = await page.goto("/");
      expect(response?.ok()).toBeTruthy();
      await expect(page.locator("body")).toBeVisible();
      const mock = await page.evaluate(async () => ({
        worker: (globalThis as unknown as Record<string, unknown>).__msw_worker ?? null,
        registrations: (await navigator.serviceWorker?.getRegistrations?.())?.length ?? 0,
      }));
      expect(mock).toEqual({ worker: null, registrations: 0 });
    });

    await test.step("sample mode is labelled and no live provider is enabled", async () => {
      await expectSampleModeNoLiveProviders(page);
    });

    await test.step("unauthenticated requests are refused", async () => {
      expect((await api(page, "GET", "/account/wallet", undefined, "none")).status).toBe(401);
      expect((await api(page, "GET", "/planning/preferences", undefined, "none")).status).toBe(401);
    });

    await test.step("register and sign in through the real API", async () => {
      const registered = await api(page, "POST", "/auth/register", { email, password }, "none");
      expect(registered.status).toBe(201);
      const login = await api(page, "POST", "/auth/login", { email, password }, "none");
      expect(login.status).toBe(200);
      const me = await api(page, "GET", "/auth/me", undefined, "none");
      expect(me.status).toBe(200);
      expect(me.json.email).toBe(email);
    });

    await test.step("cookie attributes are exactly as designed (no weakening for convenience)", async () => {
      const cookies = await context.cookies();
      const session = cookies.find((c) => c.name === "tp_session");
      const csrf = cookies.find((c) => c.name === "tp_csrf");
      expect(session, "session cookie").toBeDefined();
      expect(csrf, "csrf cookie").toBeDefined();
      expect(session).toMatchObject({ httpOnly: true, secure: true, sameSite: "Lax" });
      expect(csrf).toMatchObject({ httpOnly: false, secure: true, sameSite: "Lax" });
      const visible = await page.evaluate(() => document.cookie);
      expect(visible).toContain("tp_csrf=");
      expect(visible).not.toContain("tp_session");
    });

    let entry: { id: string; version: number };
    await test.step("CSRF protects mutations: missing and wrong tokens are refused, the right one succeeds", async () => {
      const products = await api(page, "GET", "/account/card-products");
      expect(products.status).toBe(200);
      const card = products.json.find((p: { is_eligible: boolean }) => p.is_eligible);
      expect(card, "an eligible seeded card product").toBeDefined();

      const body = { card_id: card.card_id, nickname, client_event_id: `smoke-wallet-${stamp}` };
      expect((await api(page, "POST", "/account/wallet", body, "none")).status).toBe(403);
      expect((await api(page, "POST", "/account/wallet", body, "not-the-token")).status).toBe(403);

      const created = await api(page, "POST", "/account/wallet", body);
      expect(created.status).toBe(201);
      expect(created.json.nickname).toBe(nickname);
      entry = { id: created.json.id, version: created.json.version };

      // Durable idempotency: replaying the same client_event_id returns the same entry.
      const replay = await api(page, "POST", "/account/wallet", body);
      expect(replay.status).toBe(201);
      expect(replay.json.id).toBe(entry.id);
    });

    await test.step("profile can be read", async () => {
      const profile = await api(page, "GET", "/planning/preferences");
      expect(profile.status).toBe(200);
    });

    await test.step("the wallet page renders the persisted entry from the live backend", async () => {
      await page.goto("/wallet");
      await expect(page.getByText(nickname).first()).toBeVisible();
    });

    let session: { id: string; version: number };
    await test.step("a conversational planning session starts and reflects the saved wallet", async () => {
      const started = await api(page, "POST", "/planning/sessions", undefined);
      expect(started.status).toBe(201);
      expect(started.json.current_question.id).toBe("trip_essentials");
      expect(started.json.wallet.card_ids.length).toBe(1);
      // No LLM role ran: sample/deterministic behaviour only.
      expect(started.json.interview_llm_calls).toBe(0);
      expect(started.json.assistance_status).toBe("not_run");
      session = { id: started.json.id, version: started.json.version };
    });

    await test.step("one typed answer is accepted and the session can be re-read", async () => {
      const answer = {
        question_id: "trip_essentials",
        expected_version: session.version,
        client_event_id: `smoke-answer-${stamp}`,
        payload: {
          origin: "DEL",
          destination: "SIN",
          start_date: futureDate(40),
          end_date: futureDate(45),
          travelers: 1,
        },
      };
      const answered = await api(page, "POST", `/planning/sessions/${session.id}/answers`, answer);
      expect(answered.status).toBe(200);
      expect(answered.json.version).toBeGreaterThan(session.version);
      session.version = answered.json.version;

      const reread = await api(page, "GET", `/planning/sessions/${session.id}`);
      expect(reread.status).toBe(200);
      expect(reread.json.version).toBe(session.version);
      expect(reread.json.answers.trip_essentials).toBeDefined();
      expect(reread.json.interview_llm_calls).toBe(0);
    });

    await test.step("the conversation page loads against the live backend while signed in", async () => {
      const response = await page.goto("/plan/conversation");
      expect(response?.ok()).toBeTruthy();
      await expect(page.getByText(/Sign in to start your trip consultation/i)).toHaveCount(0);
    });

    let jobId: string;
    await test.step("a legacy planning job without an LLM fails honestly (no silent hang, no fabrication)", async () => {
      const created = await api(page, "POST", "/plan", {
        raw_request: "Delhi to Singapore, one traveler, five nights",
      }, "none");
      expect(created.status).toBe(202);
      jobId = created.json.job_id;
      await expect
        .poll(async () => (await api(page, "GET", `/plan/${jobId}`, undefined, "none")).json?.status, {
          timeout: 20_000,
        })
        .toBe("failed");
      const failed = await api(page, "GET", `/plan/${jobId}`, undefined, "none");
      expect(failed.json.error.message).toMatch(/not configured/i);
      expect(failed.json.report ?? null).toBeNull();
    });

    await test.step("persist state for the post-restart phase", async () => {
      const storageStatePath = `${STATE_FILE}.storage.json`;
      await context.storageState({ path: storageStatePath });
      const state: SmokeState = {
        email,
        password,
        walletEntryId: entry.id,
        walletVersion: entry.version,
        nickname,
        sessionId: session.id,
        sessionVersion: session.version,
        jobId,
        storageStatePath,
      };
      writeFileSync(STATE_FILE!, JSON.stringify(state));
    });
  });
});

test.describe("@phase2 after the backend container was restarted", () => {
  test.skip(!STATE_FILE, "TRIPWISE_SMOKE_STATE is required (run via scripts/d1-smoke.sh)");

  test("durable state survives; process-local jobs do not, and say so honestly", async ({
    browser,
  }) => {
    const state = readState();
    const restoredContext: BrowserContext = await browser.newContext({
      storageState: state.storageStatePath,
      serviceWorkers: "block",
    });
    const page = await restoredContext.newPage();
    await page.goto("/");

    await test.step("backend is ready again and still labelled sample mode", async () => {
      await expectSampleModeNoLiveProviders(page);
    });

    await test.step("the pre-restart session cookie is still valid (sessions are persisted)", async () => {
      const me = await api(page, "GET", "/auth/me", undefined, "none");
      expect(me.status).toBe(200);
      expect(me.json.email).toBe(state.email);
    });

    await test.step("the wallet entry persisted with the same id and version", async () => {
      const wallet = await api(page, "GET", "/account/wallet");
      expect(wallet.status).toBe(200);
      const found = wallet.json.find((e: { id: string }) => e.id === state.walletEntryId);
      expect(found).toBeDefined();
      expect(found.nickname).toBe(state.nickname);
      expect(found.version).toBe(state.walletVersion);
      await page.goto("/wallet");
      await expect(page.getByText(state.nickname).first()).toBeVisible();
    });

    await test.step("the planning session and its typed answer persisted", async () => {
      const session = await api(page, "GET", `/planning/sessions/${state.sessionId}`);
      expect(session.status).toBe(200);
      expect(session.json.version).toBe(state.sessionVersion);
      expect(session.json.answers.trip_essentials).toBeDefined();
    });

    await test.step("a fresh sign-in with the same credentials still works", async () => {
      const fresh = await browser.newContext({ serviceWorkers: "block" });
      const freshPage = await fresh.newPage();
      await freshPage.goto("/");
      const login = await api(
        freshPage,
        "POST",
        "/auth/login",
        { email: state.email, password: state.password },
        "none",
      );
      expect(login.status).toBe(200);
      await fresh.close();
    });

    await test.step("the process-local planning job is gone, and the API says so (HTTP 404)", async () => {
      const job = await api(page, "GET", `/plan/${state.jobId}`, undefined, "none");
      expect(job.status).toBe(404);
    });

    await restoredContext.close();
  });
});
