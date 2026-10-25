import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import {
  SAVED_TRIP_ERROR_FIXTURES,
  type SavedTripErrorFixture,
  handlers,
  resetMswTrips,
  savedTripErrorHandler,
} from "../src/mocks/handlers";
import type { SavedTripCreatedOut, TripDetailOut, TripSummaryOut } from "../src/lib/api";

// The saved-trip mocks mirror api/saved_trips.py, so a UI built against them sees
// the same status codes, error codes and verbatim-report behaviour as the real API.

const server = setupServer(...handlers);
const BASE = "http://localhost";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => resetMswTrips());

const json = { "Content-Type": "application/json" };

async function save(event = "e1", title?: string): Promise<SavedTripCreatedOut> {
  const response = await fetch(`${BASE}/account/trips`, {
    method: "POST",
    headers: json,
    body: JSON.stringify({ session_id: "s1", client_event_id: event, title }),
  });
  expect(response.status).toBe(201);
  return (await response.json()) as SavedTripCreatedOut;
}

describe("saved-trip mocks: success paths", () => {
  it("lists nothing for an account with no trips", async () => {
    const response = await fetch(`${BASE}/account/trips`);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual([]);
  });

  it("saves a trip, lists it, and replays a retry without duplicating", async () => {
    const first = await save("e1");
    const retry = await save("e1");
    expect(retry).toEqual(first);
    const listing = (await (await fetch(`${BASE}/account/trips`)).json()) as TripSummaryOut[];
    expect(listing.map((t) => t.id)).toEqual([first.trip.id]);
    expect(first.revision.revision).toBe(1);
    expect(first.trip.revision_count).toBe(1);
  });

  it("lists newest first and keeps a caller title", async () => {
    const a = await save("e1");
    const b = await save("e2", "Second");
    const listing = (await (await fetch(`${BASE}/account/trips`)).json()) as TripSummaryOut[];
    expect(listing.map((t) => t.id)).toEqual([b.trip.id, a.trip.id]);
    expect(listing[0]?.title).toBe("Second");
  });

  it("returns detail without report bodies and the stored report verbatim", async () => {
    const created = await save();
    const detail = (await (await fetch(`${BASE}/account/trips/${created.trip.id}`)).json()) as TripDetailOut;
    expect(detail.revisions).toHaveLength(1);
    expect(JSON.stringify(detail)).not.toContain('"report"');
    const revision = await (await fetch(`${BASE}/account/trips/${created.trip.id}/revisions/1`)).json();
    expect(revision.report).toEqual(created.revision.report);
    expect(revision.is_current_schema).toBe(true);
  });

  it("appends a revision and completes a re-run into the next one", async () => {
    const created = await save();
    const id = created.trip.id;
    const appended = await fetch(`${BASE}/account/trips/${id}/revisions`, {
      method: "POST",
      headers: json,
      body: JSON.stringify({ session_id: "s1", client_event_id: "a1" }),
    });
    expect(appended.status).toBe(201);
    const started = await fetch(`${BASE}/account/trips/${id}/reruns`, {
      method: "POST",
      headers: json,
      body: JSON.stringify({ client_event_id: "r1" }),
    });
    expect(started.status).toBe(202);
    const { job_id } = (await started.json()) as { job_id: string };
    const status = await (await fetch(`${BASE}/account/trips/${id}/reruns/${job_id}`)).json();
    expect(status).toMatchObject({ status: "complete", revision: 3, error: null });
  });

  it("deletes a trip and then reports it missing", async () => {
    const created = await save();
    const url = `${BASE}/account/trips/${created.trip.id}`;
    expect((await fetch(url, { method: "DELETE" })).status).toBe(204);
    expect((await fetch(url, { method: "DELETE" })).status).toBe(404);
    expect((await fetch(url)).status).toBe(404);
  });
});

describe("saved-trip mocks: not-found behaviour", () => {
  it("answers an unknown trip, revision and re-run with typed 404s", async () => {
    const missingTrip = await fetch(`${BASE}/account/trips/nope`);
    expect(missingTrip.status).toBe(404);
    expect((await missingTrip.json()).detail.code).toBe("TRIP_NOT_FOUND");

    const created = await save();
    const revision = await fetch(`${BASE}/account/trips/${created.trip.id}/revisions/9`);
    expect((await revision.json()).detail.code).toBe("REVISION_NOT_FOUND");
    const rerun = await fetch(`${BASE}/account/trips/${created.trip.id}/reruns/nope`);
    expect((await rerun.json()).detail.code).toBe("RERUN_NOT_FOUND");

    const session = await fetch(`${BASE}/account/trips`, {
      method: "POST",
      headers: json,
      body: JSON.stringify({ session_id: "msw-session-missing", client_event_id: "x" }),
    });
    expect((await session.json()).detail.code).toBe("SESSION_NOT_FOUND");
  });
});

describe("saved-trip mocks: error fixtures", () => {
  const names = Object.keys(SAVED_TRIP_ERROR_FIXTURES) as SavedTripErrorFixture[];

  it("covers 401, 403, 404, every 409 code, 413 and 422", () => {
    const statuses = new Set(names.map((n) => SAVED_TRIP_ERROR_FIXTURES[n].status));
    for (const status of [401, 403, 404, 409, 413, 422]) expect(statuses.has(status)).toBe(true);
    const conflicts = names.filter((n) => SAVED_TRIP_ERROR_FIXTURES[n].status === 409);
    expect(conflicts.sort()).toEqual(
      [
        "IDEMPOTENCY_KEY_REUSED",
        "PLAN_RESULT_UNAVAILABLE",
        "RERUN_IN_PROGRESS",
        "REVISION_LIMIT_REACHED",
        "SESSION_ALREADY_SAVED",
        "SESSION_NOT_ATTACHED",
        "SESSION_NOT_CONFIRMED",
        "TRIP_LIMIT_REACHED",
        "TRIP_REVISION_CONFLICT",
      ].sort(),
    );
  });

  for (const name of names) {
    it(`serves the ${name} fixture`, async () => {
      server.use(savedTripErrorHandler("post", "*/account/trips", name));
      const response = await fetch(`${BASE}/account/trips`, {
        method: "POST",
        headers: json,
        body: JSON.stringify({ session_id: "s1", client_event_id: "x" }),
      });
      const spec = SAVED_TRIP_ERROR_FIXTURES[name] as { status: number; code?: string };
      expect(response.status).toBe(spec.status);
      const body = await response.json();
      if (spec.code === undefined) expect(typeof body.detail).toBe("string");
      else expect(body.detail.code).toBe(spec.code);
    });
  }

  it("carries the existing trip id on SESSION_ALREADY_SAVED", async () => {
    server.use(savedTripErrorHandler("post", "*/account/trips", "SESSION_ALREADY_SAVED"));
    const response = await fetch(`${BASE}/account/trips`, {
      method: "POST",
      headers: json,
      body: JSON.stringify({ session_id: "s1", client_event_id: "x" }),
    });
    expect((await response.json()).detail.trip_id).toBe("msw-trip-1");
  });
});
