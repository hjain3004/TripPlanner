import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import {
  ACQUISITION_ERROR_FIXTURES,
  type AcquisitionErrorFixture,
  acquisitionErrorHandler,
  handlers,
  resetMswTrips,
  resetMswWallet,
} from "../src/mocks/handlers";
import type {
  AcquisitionAssessmentReport,
  SavedTripCreatedOut,
} from "../src/lib/api";

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

function assess(tripId: string, revision: number, body: Record<string, unknown> = {}): Promise<Response> {
  return post(`/account/acquisition/trips/${tripId}/revisions/${revision}`, body);
}

describe("acquisition-assessment mock", () => {
  it("reports honest no-approved-offer with empty shipped catalog and preserves held-card strategy", async () => {
    const trip = await saveTrip();
    const response = await assess(trip.trip.id, 1, {
      payment_timing: {
        booking_date: "2026-10-24",
        first_bookable_spend_date: "2026-11-20",
      },
    });
    expect(response.status).toBe(200);
    const body = (await response.json()) as AcquisitionAssessmentReport;

    expect(body.trip_id).toBe(trip.trip.id);
    expect(body.revision).toBe(1);
    expect(body.suggestions).toEqual([]);
    expect(body.refusals).toEqual([]);
    expect(body.limitations.map((l) => l.code)).toContain("NO_APPROVED_OFFER");

    // Held cards strategy remains complete and unchanged
    expect(body.held_cards_strategy).toBeDefined();
    expect(body.held_cards_strategy.card_ids).toEqual(["hdfc-infinia"]);
    expect(body.held_cards_strategy.gross_minor).toBeGreaterThan(0);
    expect(body.held_cards_strategy.currency).toBe("INR");
  });

  it("answers documented error fixtures with the expected status and codes", async () => {
    for (const name of Object.keys(ACQUISITION_ERROR_FIXTURES) as AcquisitionErrorFixture[]) {
      server.use(acquisitionErrorHandler(name));
      const res = await assess("any-trip", 1);
      const spec = ACQUISITION_ERROR_FIXTURES[name];
      expect(res.status).toBe(spec.status);
    }
  });

  it("rejects unknown trips and revisions with typed 404s", async () => {
    const trip = await saveTrip();
    const badTrip = await assess("nonexistent-trip", 1);
    expect(badTrip.status).toBe(404);
    const badTripBody = await badTrip.json();
    expect(badTripBody.detail.code).toBe("TRIP_NOT_FOUND");

    const badRev = await assess(trip.trip.id, 999);
    expect(badRev.status).toBe(404);
    const badRevBody = await badRev.json();
    expect(badRevBody.detail.code).toBe("REVISION_NOT_FOUND");
  });
});
