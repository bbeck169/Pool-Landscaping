/**
 * Feb-2026 · Phase 1 offline foundation — api-cache write-through
 * + offline-badge render tests.
 *
 * NOTE ON JEST HOISTING · variables closed-over inside a
 * ``jest.mock`` factory MUST be prefixed with ``mock`` (case-
 * insensitive), OR the factory must be fully self-contained.  We
 * use the fully-self-contained approach here and pull the mock
 * fns back out via ``jest.requireMock`` in the test file.
 */
import React from "react";
import { render } from "@testing-library/react-native";


jest.mock("@/src/lib/offline/cache", () => ({
  __esModule: true,
  cacheWeekJobs: jest.fn(async () => {}),
  getCachedWeekJobs: jest.fn(async () => []),
  getCachedJob: jest.fn(async () => null),
  cacheCustomer: jest.fn(async () => {}),
  getCachedCustomer: jest.fn(async () => null),
  cacheProperty: jest.fn(async () => {}),
  getCachedProperty: jest.fn(async () => null),
  cacheMe: jest.fn(async () => {}),
  getCachedMe: jest.fn(async () => null),
  initCache: jest.fn(async () => {}),
  wipeCache: jest.fn(async () => {}),
  __resetForTests: jest.fn(() => {}),
}));

// Feb-2026 · Phase 1 offline foundation — stub the shared api client
// too so we don't pull AsyncStorage/SecureStore into a unit test.
// ``ApiNetworkError`` MUST be exported so ``instanceof`` checks in
// apiCache's cachedGet still work.  The class is declared INSIDE
// the factory to avoid the jest-hoisting order trap (factories run
// before top-level ``class`` statements execute).
jest.mock("@/src/api", () => {
  class ApiNetworkError extends Error {
    kind = "network" as const;
    constructor(msg: string) { super(msg); this.name = "ApiNetworkError"; }
  }
  return {
    __esModule: true,
    ApiNetworkError,
    TOKEN_KEY: "pool_crm_token",
    api: {
      get: jest.fn(async (_p: string) => ({})),
      post: jest.fn(async () => ({})),
      put: jest.fn(async () => ({})),
      patch: jest.fn(async () => ({})),
      del: jest.fn(async () => ({})),
    },
    registerLogoutOn401: jest.fn(),
    getAuthToken: jest.fn(async () => ""),
    api_base: () => "http://test/api",
  };
});

// NetInfo — module-level toggle so each test can flip online/offline.
const mockNet = { connected: true };
jest.mock("@react-native-community/netinfo", () => ({
  __esModule: true,
  default: {
    fetch: jest.fn(async () => ({ isConnected: mockNet.connected })),
    addEventListener: (_cb: any) => { return () => {}; },
  },
}));

jest.mock("@expo/vector-icons", () => {
  const RN = require("react-native");
  const R = require("react");
  return { Ionicons: ({ name }: any) => R.createElement(RN.View, { accessibilityLabel: `ionicons-${name}` }) };
});


import {
  writeThroughJobs, writeThroughCustomer, writeThroughProperty, writeThroughMe,
  cachedGet,
} from "@/src/lib/offline/apiCache";
import OfflineBadge from "@/src/components/OfflineBadge";
import { api, ApiNetworkError } from "@/src/api";

const cacheMod = jest.requireMock("@/src/lib/offline/cache") as {
  cacheWeekJobs: jest.Mock;
  cacheCustomer: jest.Mock;
  cacheProperty: jest.Mock;
  cacheMe: jest.Mock;
};
const apiMod = api as unknown as { get: jest.Mock };


beforeEach(() => {
  cacheMod.cacheWeekJobs.mockClear();
  cacheMod.cacheCustomer.mockClear();
  cacheMod.cacheProperty.mockClear();
  cacheMod.cacheMe.mockClear();
  apiMod.get.mockReset();
  mockNet.connected = true;
});


describe("apiCache · write-through helpers", () => {
  test("writeThroughJobs unwraps `{jobs: [...] }` envelope + caches for the tech", async () => {
    await writeThroughJobs("T1", { jobs: [{ id: "j1" }, { id: "j2" }] });
    expect(cacheMod.cacheWeekJobs).toHaveBeenCalledWith("T1",
      [{ id: "j1" }, { id: "j2" }]);
  });

  test("writeThroughJobs accepts a plain array payload", async () => {
    await writeThroughJobs("T1", [{ id: "j3" }]);
    expect(cacheMod.cacheWeekJobs).toHaveBeenCalledWith("T1", [{ id: "j3" }]);
  });

  test("writeThroughJobs is a no-op when techUserId is missing", async () => {
    await writeThroughJobs("", { jobs: [{ id: "j1" }] });
    expect(cacheMod.cacheWeekJobs).not.toHaveBeenCalled();
  });

  test("writeThroughCustomer / Property / Me forward payloads correctly", async () => {
    await writeThroughCustomer({ id: "c1", first_name: "A" });
    await writeThroughProperty({ id: "p1", customer_id: "c1" });
    await writeThroughMe({ id: "u1", role: "technician" });
    expect(cacheMod.cacheCustomer).toHaveBeenCalledWith({ id: "c1", first_name: "A" });
    expect(cacheMod.cacheProperty).toHaveBeenCalledWith({ id: "p1", customer_id: "c1" });
    expect(cacheMod.cacheMe).toHaveBeenCalledWith({ id: "u1", role: "technician" });
  });

  test("write-through helpers do NOT touch POST/PUT/DELETE cache paths (Phase 2 scope)", () => {
    // Sanity: the module exports only read-cache write-through
    // helpers.  There is no ``writeThroughPost`` / ``writeThroughDelete`` etc.
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const mod = require("@/src/lib/offline/apiCache");
    const exported = Object.keys(mod).sort();
    for (const key of exported) {
      expect(key).not.toMatch(/writeThroughPost|writeThroughPut|writeThroughDelete/i);
    }
  });
});


describe("apiCache · cachedGet compose helper", () => {
  test("on 2xx: returns server payload and fires the write-through", async () => {
    apiMod.get.mockResolvedValueOnce({ jobs: [{ id: "j1" }] });
    const writeThrough = jest.fn(async () => {});
    const readCache = jest.fn(async () => ({ jobs: [] }));
    const out = await cachedGet("/jobs?start=x", { writeThrough, readCache });
    expect(out).toEqual({ jobs: [{ id: "j1" }] });
    // Write-through fires asynchronously — flush one microtask.
    await new Promise((r) => setImmediate(r));
    expect(writeThrough).toHaveBeenCalledWith({ jobs: [{ id: "j1" }] });
    expect(readCache).not.toHaveBeenCalled();
  });

  test("on ApiNetworkError: reads from cache when present", async () => {
    apiMod.get.mockRejectedValueOnce(new ApiNetworkError("offline"));
    const readCache = jest.fn(async () => [{ id: "cached-j1" }]);
    const out = await cachedGet("/jobs?x", { readCache });
    expect(out).toEqual([{ id: "cached-j1" }]);
    expect(readCache).toHaveBeenCalled();
  });

  test("on ApiNetworkError with empty cache: re-throws so the screen shows its normal error UI", async () => {
    apiMod.get.mockRejectedValueOnce(new ApiNetworkError("offline"));
    const readCache = jest.fn(async () => null);
    await expect(cachedGet("/jobs?x", { readCache })).rejects.toBeInstanceOf(ApiNetworkError);
  });

  test("HTTP 500 / non-network errors are NOT swallowed by the cache", async () => {
    apiMod.get.mockRejectedValueOnce(new Error("Request failed (500)"));
    const readCache = jest.fn(async () => [{ id: "cached" }]);
    await expect(cachedGet("/jobs?x", { readCache })).rejects.toThrow("Request failed (500)");
    expect(readCache).not.toHaveBeenCalled();
  });
});



describe("<OfflineBadge />", () => {
  test("does NOT render when netinfo reports online", async () => {
    mockNet.connected = true;
    const { queryByTestId } = render(<OfflineBadge />);
    // Wait a tick for the initial ``NetInfo.fetch`` to resolve.
    await new Promise((r) => setImmediate(r));
    expect(queryByTestId("offline-badge")).toBeNull();
  });

  test("renders the 'Offline' pill when netinfo reports offline", async () => {
    mockNet.connected = false;
    const { findByTestId, getByText } = render(<OfflineBadge />);
    const pill = await findByTestId("offline-badge");
    expect(pill).toBeTruthy();
    expect(getByText("Offline")).toBeTruthy();
  });
});
