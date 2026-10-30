import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import {
  WELCOME_STATUS_ERROR_FIXTURES,
  type WelcomeStatusErrorFixture,
  handlers,
  resetMswTrips,
  resetMswWallet,
  welcomeStatusErrorHandler,
} from "../src/mocks/handlers";
import type {
  RevisionOut,
  SavedTripCreatedOut,
  WelcomeStatusApiErrorBody,
  WelcomeWindowReport,
} from "../src/lib/api";

// The welcome-status mock mirrors api/welcome.py. With no approved offer data shipped,
// the real route reports `unknown` and never invents a window, shortfall or bonus, so a
// UI built on this mock sees the same honest default and the same typed failures.

const server = setupServer(...handlers);
const BASE = "http://localhost";
const json = { "Content-Type": "application/json" };

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const ENTRY = {
  id: "msw-wallet-1",
  card_id: "hdfc-infinia",
  nickname: "Infinia",
  last4: null,
  statement_day: null,
  opened_on: "2026-10-01",
  points_balances: {},
  added_at: "2026-10-19T12:00:00.000Z",
  version: 1,
};

beforeEach(() => {
  resetMswTrips();
  resetMswWallet([ENTRY]);
});

function post(path: string, body: unknown): Promise<Response> {
  return fetch(`${BASE}${path}`, { method: "POST", headers: json, body: JSON.stringify(body) });
}

async function saveTrip(): Promise<SavedTripCreatedOut> {
  const response = await post("/account/trips", { session_id: "s1", client_event_id: "e1" });
  expect(response.status).toBe(201);
  return (await response.json()) as SavedTripCreatedOut;
}

function status(entryId: string, body: Record<string, unknown>): Promise<Response> {
  return post(`/account/wallet/${entryId}/welcome-status`, body);
}

describe("welcome-status mock", () => {
  it("reports that no approved offer exists and invents no window, shortfall or bonus", async () => {
    const trip = await saveTrip();
    const response = await status(ENTRY.id, {
      trip_id: trip.trip.id,
      revision: 1,
      prior_qualifying_spend_minor: 1_200_000,
    });
    expect(response.status).toBe(200);
    const body = (await response.json()) as WelcomeWindowReport;
    expect(body.status).toBe("unknown");
    expect(body.limitations.map((l) => l.code)).toEqual(["NO_APPROVED_OFFER"]);
    expect(body.opened_on).toBe("2026-10-01");
    expect(body.window_closes_on).toBeNull();
    expect(body.days_remaining).toBeNull();
    expect(body.offer).toBeNull();
    expect(body.bonus).toBeNull();
    expect(body.min_spend_minor).toBeNull();
    expect(body.shortfall_minor).toBeNull();
    expect(body.conditional_trip_spend_minor).toBe(0);
    expect(body.qualifying_spend_to_date_minor).toBe(1_200_000);
  });

  it("does not treat an omitted prior spend as zero", async () => {
    const trip = await saveTrip();
    const omitted = (await (
      await status(ENTRY.id, { trip_id: trip.trip.id, revision: 1 })
    ).json()) as WelcomeWindowReport;
    expect(omitted.qualifying_spend_to_date_minor).toBeNull();
    expect(omitted.limitations.map((l) => l.code)).toContain("PRIOR_SPEND_UNKNOWN");

    const zero = (await (
      await status(ENTRY.id, { trip_id: trip.trip.id, revision: 1, prior_qualifying_spend_minor: 0 })
    ).json()) as WelcomeWindowReport;
    expect(zero.qualifying_spend_to_date_minor).toBe(0);
    expect(zero.limitations.map((l) => l.code)).not.toContain("PRIOR_SPEND_UNKNOWN");
  });

  it("reads the trip amount from the stored revision, not from the request", async () => {
    const trip = await saveTrip();
    const stored = (await (
      await fetch(`${BASE}/account/trips/${trip.trip.id}/revisions/1`)
    ).json()) as RevisionOut;
    const result = stored.report.optimizer_result as {
      assignments: { card_id: string; line: { amount_minor: number } }[];
    };
    const expected = result.assignments
      .filter((a) => a.card_id === ENTRY.card_id)
      .reduce((sum, a) => sum + a.line.amount_minor, 0);
    const body = (await (
      await status(ENTRY.id, { trip_id: trip.trip.id, revision: 1 })
    ).json()) as WelcomeWindowReport;
    expect(body.trip_assigned_spend_minor).toBe(expected);
    expect(body.trip.trip_id).toBe(trip.trip.id);
  });

  it("answers an unknown wallet entry, trip and revision with the API's typed 404s", async () => {
    const trip = await saveTrip();
    const cases: [string, Record<string, unknown>, WelcomeStatusApiErrorBody["code"]][] = [
      ["missing-entry", { trip_id: trip.trip.id, revision: 1 }, "WALLET_ENTRY_NOT_FOUND"],
      [ENTRY.id, { trip_id: "missing-trip", revision: 1 }, "TRIP_NOT_FOUND"],
      [ENTRY.id, { trip_id: trip.trip.id, revision: 99 }, "REVISION_NOT_FOUND"],
    ];
    for (const [entryId, body, code] of cases) {
      const response = await status(entryId, body);
      expect(response.status).toBe(404);
      expect(((await response.json()) as { detail: WelcomeStatusApiErrorBody }).detail.code).toBe(code);
    }
  });

  it.each(Object.keys(WELCOME_STATUS_ERROR_FIXTURES) as WelcomeStatusErrorFixture[])(
    "can be told to fail with the documented %s response",
    async (fixture) => {
      server.use(welcomeStatusErrorHandler(fixture));
      const spec = WELCOME_STATUS_ERROR_FIXTURES[fixture] as {
        status: number;
        code?: string;
        detail?: string;
      };
      const response = await status(ENTRY.id, { trip_id: "t", revision: 1 });
      expect(response.status).toBe(spec.status);
      const body = (await response.json()) as { detail: unknown };
      if (spec.code === undefined) expect(body.detail).toBe(spec.detail);
      else expect((body.detail as WelcomeStatusApiErrorBody).code).toBe(spec.code);
    },
  );
});
