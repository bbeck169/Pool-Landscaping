/**
 * TD-mobile-sync-tech-not-linked (contract follow-up) · `_safeFetch` returns
 * `{ ok:false, status, detail, error }` instead of null, and the POST /mobile/sync
 * path (sync/queue) reports errors through `noteSyncError` — match by error code.
 */
import fs from "fs";
import path from "path";

const mockGet = jest.fn();
jest.mock("@/src/api", () => ({ api: { get: (...a: any[]) => mockGet(...a) } }));
jest.mock("@/src/services/readCache", () => ({ writeCache: jest.fn().mockResolvedValue(undefined), readCache: jest.fn().mockResolvedValue(null) }));
jest.mock("@/src/services/sync/netBus", () => ({ isOnlineNow: () => true }));
jest.mock("@/src/services/photoUrlCache", () => ({ stripBase64FromReport: (r: any) => r }));

import { _safeFetch, noteSyncError, hydrateToday, getHydrationMeta } from "@/src/services/routeHydrator";
import { TECH_NOT_LINKED_COPY } from "@/src/lib/syncErrors";

class FakeApiError extends Error {
  status: number; detail: unknown;
  constructor(m: string, s: number, d: unknown) { super(m); this.status = s; this.detail = d; }
}
const INNER = { error: "technician_not_linked", detail: "not linked", tenant_id: "t1", user_id: "u1" };
const NOT_LINKED = () => new FakeApiError("not linked", 409, INNER);

beforeEach(async () => {
  mockGet.mockReset();
  mockGet.mockResolvedValueOnce({ jobs: [], reports: {}, total_jobs: 0 });
  await hydrateToday("u1"); // reset meta to a non-error state
  mockGet.mockReset();
});

it("C1 · _safeFetch success → { ok:true, data }", async () => {
  mockGet.mockResolvedValueOnce({ jobs: [1] });
  expect(await _safeFetch("/mobile/offline-bundle")).toEqual({ ok: true, data: { jobs: [1] } });
});

it("C2 · _safeFetch 409 → { ok:false, status:409, detail:<inner object>, error } (no null)", async () => {
  const err = NOT_LINKED();
  mockGet.mockRejectedValueOnce(err);
  expect(await _safeFetch("/mobile/offline-bundle")).toEqual({ ok: false, status: 409, detail: INNER, error: err });
});

it("C3 · _safeFetch network / 5xx → ok:false with status null / 503", async () => {
  mockGet.mockRejectedValueOnce(new Error("Network request failed"));
  expect(await _safeFetch("/x")).toMatchObject({ ok: false, status: null, detail: null });
  mockGet.mockRejectedValueOnce(new FakeApiError("Server error", 503, "upstream down"));
  expect(await _safeFetch("/x")).toMatchObject({ ok: false, status: 503, detail: "upstream down" });
});

it("C4 · POST /mobile/sync path: 409 technician_not_linked → tech_not_linked + admin copy", () => {
  noteSyncError(NOT_LINKED());
  expect(getHydrationMeta().syncStatus).toBe("tech_not_linked");
  expect(getHydrationMeta().lastError).toBe(TECH_NOT_LINKED_COPY);
});

it("C5 · POST /mobile/sync path: network / 5xx / other 409 leave the sync status unchanged", () => {
  const before = getHydrationMeta().syncStatus;
  noteSyncError(new Error("Network request failed"));
  noteSyncError(new FakeApiError("Server error", 500, "boom"));
  noteSyncError(new FakeApiError("Conflict", 409, { error: "version_conflict" }));
  expect(getHydrationMeta().syncStatus).toBe(before);
  expect(before).not.toBe("tech_not_linked");
});

it("C6 · wiring lock: sync/queue dispatch catch reports every error via noteSyncError", () => {
  const src = fs.readFileSync(path.resolve(__dirname, "../src/services/sync/queue.ts"), "utf8");
  expect(src).toContain('import { noteSyncError } from "../routeHydrator";');
  const c = src.slice(src.indexOf("async function _dispatchOne"));
  expect(c.slice(c.indexOf("} catch (e: any) {"), c.indexOf("instanceof ApiNetworkError"))).toContain("noteSyncError(e);");
});
