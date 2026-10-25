import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import {
  SAVED_TRIP_ERROR_FIXTURES,
  type SavedTripErrorFixture,
  handlers,
  resetMswTrips,
  savedTripErrorHandler,
} from "../src/mocks/handlers";
import type {
  ApiErrorBody,
  SavedTripCreatedOut,
  TripDetailOut,
  TripSummaryOut,
} from "../src/lib/api";

// The saved-trip mocks mirror api/saved_trips.py, so a UI built against them sees
// the same status codes, error codes, idempotency and verbatim-report behaviour as the
// real API.

const server = setupServer(...handlers);
const BASE = "http://localhost";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => resetMswTrips());

const json = { "Content-Type": "application/json" };

function post(path: string, body: unknown): Promise<Response> {
  return fetch(`${BASE}${path}`, { method: "POST", headers: json, body: JSON.stringify(body) });
}

async function save(event = "e1", session = "s1", title?: string): Promise<SavedTripCreatedOut> {
  const response = await post("/account/trips", { session_id: session, client_event_id: event, title });
  expect(response.status).toBe(201);
  return (await response.json()) as SavedTripCreatedOut;
}

async function errorOf(response: Response): Promise<ApiErrorBody> {
  return ((await response.json()) as { detail: ApiErrorBody }).detail;
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
    const a = await save("e1", "s1");
    const b = await save("e2", "s2", "Second");
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
});

describe("saved-trip mocks: save conflicts", () => {
  it("refuses a second save of the same session and names the existing trip", async () => {
    const first = await save("e1", "s1");
    const again = await post("/account/trips", { session_id: "s1", client_event_id: "e2" });
    expect(again.status).toBe(409);
    const error = await errorOf(again);
    expect(error.code).toBe("SESSION_ALREADY_SAVED");
    expect(error.trip_id).toBe(first.trip.id);
  });

  it("rejects an event id reused for a different save", async () => {
    await save("e1", "s1");
    const reused = await post("/account/trips", { session_id: "s2", client_event_id: "e1" });
    expect(reused.status).toBe(409);
    expect((await errorOf(reused)).code).toBe("IDEMPOTENCY_KEY_REUSED");
  });

  it("selects plan-state failures by sentinel session id", async () => {
    const cases: Array<[string, number, ApiErrorBody["code"]]> = [
      ["msw-session-missing", 404, "SESSION_NOT_FOUND"],
      ["msw-session-expired", 410, "SESSION_EXPIRED"],
      ["msw-session-unconfirmed", 409, "SESSION_NOT_CONFIRMED"],
      ["msw-session-lost", 409, "PLAN_RESULT_UNAVAILABLE"],
    ];
    for (const [session, status, code] of cases) {
      const response = await post("/account/trips", { session_id: session, client_event_id: `ev-${session}` });
      expect(response.status).toBe(status);
      expect((await errorOf(response)).code).toBe(code);
    }
  });

  it("stops at the 50-trip cap, but still replays the save that reached it", async () => {
    for (let i = 1; i <= 50; i += 1) await save(`e${i}`, `s${i}`);
    const full = await post("/account/trips", { session_id: "s51", client_event_id: "e51" });
    expect(full.status).toBe(409);
    expect((await errorOf(full)).code).toBe("TRIP_LIMIT_REACHED");
    expect((await post("/account/trips", { session_id: "s50", client_event_id: "e50" })).status).toBe(201);
  });
});

describe("saved-trip mocks: append", () => {
  it("appends the attached session's plan and replays a retry once", async () => {
    const created = await save("e1", "s1");
    const path = `/account/trips/${created.trip.id}/revisions`;
    const first = await post(path, { session_id: "s1", client_event_id: "a1" });
    const retry = await post(path, { session_id: "s1", client_event_id: "a1" });
    expect(first.status).toBe(201);
    expect(await retry.json()).toEqual(await first.json());
    const detail = (await (await fetch(`${BASE}/account/trips/${created.trip.id}`)).json()) as TripDetailOut;
    expect(detail.revision_count).toBe(2);
  });

  it("refuses a session the trip was not saved from, and an event id reused for another session", async () => {
    const created = await save("e1", "s1");
    const path = `/account/trips/${created.trip.id}/revisions`;
    const foreign = await post(path, { session_id: "s-other", client_event_id: "a1" });
    expect(foreign.status).toBe(409);
    expect((await errorOf(foreign)).code).toBe("SESSION_NOT_ATTACHED");
    await post(path, { session_id: "s1", client_event_id: "a2" });
    const reused = await post(path, { session_id: "s-other", client_event_id: "a2" });
    expect((await errorOf(reused)).code).toBe("IDEMPOTENCY_KEY_REUSED");
  });

  it("stops at the 25-revision cap", async () => {
    const created = await save("e1", "s1");
    const path = `/account/trips/${created.trip.id}/revisions`;
    for (let i = 2; i <= 25; i += 1) {
      expect((await post(path, { session_id: "s1", client_event_id: `a${i}` })).status).toBe(201);
    }
    const full = await post(path, { session_id: "s1", client_event_id: "a26" });
    expect(full.status).toBe(409);
    expect((await errorOf(full)).code).toBe("REVISION_LIMIT_REACHED");
  });
});

describe("saved-trip mocks: delete", () => {
  it("deletes a trip and then reports it missing", async () => {
    const created = await save();
    const url = `${BASE}/account/trips/${created.trip.id}`;
    expect((await fetch(url, { method: "DELETE" })).status).toBe(204);
    expect((await fetch(url, { method: "DELETE" })).status).toBe(404);
    expect((await fetch(url)).status).toBe(404);
  });

  it("replays a retried delete as 204 and rejects the event id for another trip", async () => {
    const a = await save("e1", "s1");
    const b = await save("e2", "s2");
    const del = (id: string, event: string) =>
      fetch(`${BASE}/account/trips/${id}?client_event_id=${event}`, { method: "DELETE" });
    expect((await del(a.trip.id, "d1")).status).toBe(204);
    expect((await del(a.trip.id, "d1")).status).toBe(204); // replay, trip already gone
    expect((await del(a.trip.id, "d2")).status).toBe(404); // a genuine second delete
    const reused = await del(b.trip.id, "d1");
    expect(reused.status).toBe(409);
    expect((await errorOf(reused)).code).toBe("IDEMPOTENCY_KEY_REUSED");
  });
});

describe("saved-trip mocks: re-runs", () => {
  async function start(tripId: string, event: string): Promise<Response> {
    return post(`/account/trips/${tripId}/reruns`, { client_event_id: event });
  }
  const poll = (tripId: string, jobId: string) =>
    fetch(`${BASE}/account/trips/${tripId}/reruns/${jobId}`).then((r) => r.json());

  it("runs, then completes with the revision it actually appended", async () => {
    const created = await save();
    const id = created.trip.id;
    const started = await start(id, "r1");
    expect(started.status).toBe(202);
    const { job_id } = (await started.json()) as { job_id: string };
    expect(await poll(id, job_id)).toMatchObject({ status: "running", revision: null });
    expect(await poll(id, job_id)).toMatchObject({ status: "complete", revision: 2, error: null });
    expect(await poll(id, job_id)).toMatchObject({ status: "complete", revision: 2 }); // not re-appended
    const detail = (await (await fetch(`${BASE}/account/trips/${id}`)).json()) as TripDetailOut;
    expect(detail.revision_count).toBe(2);
  });

  it("returns the same job for a retried start and refuses a second while one runs", async () => {
    const id = (await save()).trip.id;
    const first = (await (await start(id, "r1")).json()) as { job_id: string };
    const retry = await start(id, "r1");
    expect(await retry.json()).toEqual(first);
    const busy = await start(id, "r2");
    expect(busy.status).toBe(409);
    expect((await errorOf(busy)).code).toBe("RERUN_IN_PROGRESS");
    await poll(id, first.job_id);
    await poll(id, first.job_id); // completes
    expect((await start(id, "r3")).status).toBe(202); // the trip is free again
  });

  it("rejects an event id reused for another trip and stops at the revision cap", async () => {
    const a = (await save("e1", "s1")).trip.id;
    const b = (await save("e2", "s2")).trip.id;
    await start(a, "shared");
    const reused = await start(b, "shared");
    expect((await errorOf(reused)).code).toBe("IDEMPOTENCY_KEY_REUSED");

    const path = `/account/trips/${b}/revisions`;
    for (let i = 2; i <= 25; i += 1) await post(path, { session_id: "s2", client_event_id: `a${i}` });
    const full = await start(b, "r-full");
    expect(full.status).toBe(409);
    expect((await errorOf(full)).code).toBe("REVISION_LIMIT_REACHED");
  });

  it("answers an unknown job, or another trip's job, with RERUN_NOT_FOUND", async () => {
    const a = (await save("e1", "s1")).trip.id;
    const b = (await save("e2", "s2")).trip.id;
    const { job_id } = (await (await start(a, "r1")).json()) as { job_id: string };
    expect((await errorOf(await fetch(`${BASE}/account/trips/${a}/reruns/nope`))).code).toBe("RERUN_NOT_FOUND");
    expect((await errorOf(await fetch(`${BASE}/account/trips/${b}/reruns/${job_id}`))).code).toBe("RERUN_NOT_FOUND");
  });
});

describe("saved-trip mocks: not-found behaviour", () => {
  it("answers an unknown trip and revision with typed 404s", async () => {
    const missingTrip = await fetch(`${BASE}/account/trips/nope`);
    expect(missingTrip.status).toBe(404);
    expect((await errorOf(missingTrip)).code).toBe("TRIP_NOT_FOUND");

    const created = await save();
    const revision = await fetch(`${BASE}/account/trips/${created.trip.id}/revisions/9`);
    expect((await errorOf(revision)).code).toBe("REVISION_NOT_FOUND");
  });
});

describe("saved-trip mocks: error fixtures", () => {
  const names = Object.keys(SAVED_TRIP_ERROR_FIXTURES) as SavedTripErrorFixture[];
  // Compile-time exhaustiveness: if the backend adds or removes an error code, the
  // regenerated ApiErrorBody type stops matching this table and tsc fails.
  const EVERY_CODE: Record<ApiErrorBody["code"], true> = {
    IDEMPOTENCY_KEY_REUSED: true,
    PLAN_RESULT_UNAVAILABLE: true,
    REPORT_TOO_LARGE: true,
    RERUN_IN_PROGRESS: true,
    RERUN_NOT_FOUND: true,
    REVISION_LIMIT_REACHED: true,
    REVISION_NOT_FOUND: true,
    SAVED_TRIP_INVALID: true,
    SAVED_TRIPS_UNAVAILABLE: true,
    SESSION_ALREADY_SAVED: true,
    SESSION_EXPIRED: true,
    SESSION_NOT_ATTACHED: true,
    SESSION_NOT_CONFIRMED: true,
    SESSION_NOT_FOUND: true,
    STALE_SESSION: true,
    TRIP_LIMIT_REACHED: true,
    TRIP_NOT_FOUND: true,
    TRIP_NOT_RERUNNABLE: true,
    TRIP_REVISION_CONFLICT: true,
  };

  it("has a fixture for every error code the API can return, plus 401 and 403", () => {
    const covered = new Set<string>(
      names.flatMap((n) => {
        const spec = SAVED_TRIP_ERROR_FIXTURES[n] as { code?: string };
        return spec.code === undefined ? [] : [spec.code];
      }),
    );
    expect([...covered].sort()).toEqual(Object.keys(EVERY_CODE).sort());
    const statuses = new Set(names.map((n) => SAVED_TRIP_ERROR_FIXTURES[n].status));
    for (const status of [401, 403, 404, 409, 410, 413, 422, 503]) expect(statuses.has(status)).toBe(true);
  });

  for (const name of names) {
    it(`serves the ${name} fixture`, async () => {
      server.use(savedTripErrorHandler("post", "*/account/trips", name));
      const response = await post("/account/trips", { session_id: "s1", client_event_id: "x" });
      const spec = SAVED_TRIP_ERROR_FIXTURES[name] as { status: number; code?: string };
      expect(response.status).toBe(spec.status);
      const body = await response.json();
      if (spec.code === undefined) expect(typeof body.detail).toBe("string");
      else expect(body.detail.code).toBe(spec.code);
    });
  }

  it("carries the existing trip id on SESSION_ALREADY_SAVED", async () => {
    server.use(savedTripErrorHandler("post", "*/account/trips", "SESSION_ALREADY_SAVED"));
    const response = await post("/account/trips", { session_id: "s1", client_event_id: "x" });
    expect((await errorOf(response)).trip_id).toBe("msw-trip-1");
  });
});
