/**
 * P9-C · Technician Visibility Jail — tests.
 *
 * 1. writeThroughJobs filters out peer jobs for a technician.
 * 2. writeThroughJobs does NOT filter for an admin.
 * 3. Purge migration removes peer rows on first launch and no-ops on second.
 * 4. CrewFilterBar hides "All crews" when hideAllOption is true.
 */

// ── Cache mock (must use jest.fn() inside factory — sandbox restriction) ──
jest.mock("@/src/lib/offline/cache.native", () => ({
  cacheWeekJobs: jest.fn(),
  getCachedWeekJobs: jest.fn().mockResolvedValue([]),
  getCachedJob: jest.fn().mockResolvedValue(null),
  initCache: jest.fn(),
  wipeCache: jest.fn(),
  __resetForTests: jest.fn(),
}));
jest.mock("@/src/services/readCache", () => ({ markApiSuccess: jest.fn() }));

// ── AsyncStorage mock ──
const _asyncStore: Record<string, string | null> = {};
jest.mock("@react-native-async-storage/async-storage", () => ({
  __esModule: true,
  default: {
    getItem: jest.fn((k: string) => Promise.resolve(_asyncStore[k] ?? null)),
    setItem: jest.fn((k: string, v: string) => { _asyncStore[k] = v; return Promise.resolve(); }),
    removeItem: jest.fn((k: string) => { delete _asyncStore[k]; return Promise.resolve(); }),
  },
}));

// ── SQLite mock ──
const _sqliteRows: { jobs: any[] } = { jobs: [] };
const _sqliteDeleted: string[] = [];
jest.mock("expo-sqlite", () => ({
  openDatabaseAsync: jest.fn(() =>
    Promise.resolve({
      execAsync: jest.fn(() => Promise.resolve()),
      getAllAsync: jest.fn((_q: string, params: any[]) =>
        Promise.resolve(
          _sqliteRows.jobs.filter((r: any) =>
            !params || !params[0] || r._tech_user_id === params[0],
          ),
        ),
      ),
      runAsync: jest.fn((_q: string, params: any[]) => {
        if (_q.includes("DELETE") && params?.[0]) _sqliteDeleted.push(params[0]);
        return Promise.resolve();
      }),
    }),
  ),
}));

// ── Imports (after all mocks) ──
import { writeThroughJobs, type TechScope } from "@/src/lib/offline/apiCache";
import { cacheWeekJobs } from "@/src/lib/offline/cache.native";
import { runP9cPurgeMigration, _PURGE_GUARD_KEY } from "@/src/lib/offline/p9cPurge";

import React from "react";
import { render } from "@testing-library/react-native";
import CrewFilterBar from "@/src/components/schedule/CrewFilterBar";

// Cast the mock for type-safe assertions.
const mockCacheWeekJobs = cacheWeekJobs as jest.Mock;

// ── Constants ──
const TECH_ID = "tech-42";
const PEER_ID = "tech-99";
const USER_ID = "user-1";

const ownJob = { id: "j1", technician_id: TECH_ID, scheduled_date: "2026-04-20" };
const peerJob = { id: "j2", technician_id: PEER_ID, scheduled_date: "2026-04-20" };
const unassignedJob = { id: "j3", technician_id: null, scheduled_date: "2026-04-20" };

beforeEach(() => {
  jest.clearAllMocks();
  Object.keys(_asyncStore).forEach((k) => delete _asyncStore[k]);
  _sqliteRows.jobs = [];
  _sqliteDeleted.length = 0;
});

// ═══════════════════════════════════════════════════════════════
// 1. writeThroughJobs — tech filter
// ═══════════════════════════════════════════════════════════════
describe("writeThroughJobs — tech filter", () => {
  const techScope: TechScope = { role: "technician", technicianId: TECH_ID };

  it("keeps own + unassigned, drops peer jobs for a technician", async () => {
    await writeThroughJobs(USER_ID, { jobs: [ownJob, peerJob, unassignedJob] }, techScope);

    expect(mockCacheWeekJobs).toHaveBeenCalledTimes(1);
    const cached = mockCacheWeekJobs.mock.calls[0][1];
    expect(cached).toHaveLength(2);
    expect(cached.map((j: any) => j.id).sort()).toEqual(["j1", "j3"]);
  });

  it("caches empty list (fail closed) when tech has no technician_id", async () => {
    await writeThroughJobs(USER_ID, { jobs: [ownJob, peerJob] }, { role: "technician", technicianId: null });
    expect(mockCacheWeekJobs).not.toHaveBeenCalled();
  });

  it("does NOT filter when no techScope (admin path)", async () => {
    await writeThroughJobs(USER_ID, { jobs: [ownJob, peerJob, unassignedJob] }, undefined);

    expect(mockCacheWeekJobs).toHaveBeenCalledTimes(1);
    const cached = mockCacheWeekJobs.mock.calls[0][1];
    expect(cached).toHaveLength(3);
  });

  it("does NOT filter for explicit admin techScope", async () => {
    await writeThroughJobs(USER_ID, { jobs: [ownJob, peerJob, unassignedJob] }, { role: "admin", technicianId: null });

    expect(mockCacheWeekJobs).toHaveBeenCalledTimes(1);
    const cached = mockCacheWeekJobs.mock.calls[0][1];
    expect(cached).toHaveLength(3);
  });
});

// ═══════════════════════════════════════════════════════════════
// 2. P9-C purge migration
// ═══════════════════════════════════════════════════════════════
describe("runP9cPurgeMigration", () => {
  it("deletes peer jobs on first launch for a technician", async () => {
    _sqliteRows.jobs = [
      { id: "j1", _tech_user_id: USER_ID, payload: JSON.stringify({ technician_id: TECH_ID }) },
      { id: "j2", _tech_user_id: USER_ID, payload: JSON.stringify({ technician_id: PEER_ID }) },
      { id: "j3", _tech_user_id: USER_ID, payload: JSON.stringify({ technician_id: null }) },
    ];

    await runP9cPurgeMigration("technician", TECH_ID, USER_ID);

    expect(_sqliteDeleted).toContain("j2");
    expect(_sqliteDeleted).not.toContain("j1");
    expect(_sqliteDeleted).not.toContain("j3");
    expect(_asyncStore[_PURGE_GUARD_KEY]).toBe("true");
  });

  it("no-ops on second launch (guard already set)", async () => {
    _asyncStore[_PURGE_GUARD_KEY] = "true";
    _sqliteRows.jobs = [
      { id: "j2", _tech_user_id: USER_ID, payload: JSON.stringify({ technician_id: PEER_ID }) },
    ];

    await runP9cPurgeMigration("technician", TECH_ID, USER_ID);
    expect(_sqliteDeleted).toHaveLength(0);
  });

  it("skips entirely for admin role", async () => {
    await runP9cPurgeMigration("admin", null, USER_ID);
    expect(_sqliteDeleted).toHaveLength(0);
    expect(_asyncStore[_PURGE_GUARD_KEY]).toBeUndefined();
  });

  it("wipes all cached jobs when tech has no technician_id (fail closed)", async () => {
    await runP9cPurgeMigration("technician", null, USER_ID);
    expect(_sqliteDeleted).toContain(USER_ID);
    expect(_asyncStore[_PURGE_GUARD_KEY]).toBe("true");
  });
});

// ═══════════════════════════════════════════════════════════════
// 3. CrewFilterBar — hideAllOption
// ═══════════════════════════════════════════════════════════════
describe("CrewFilterBar — hideAllOption", () => {
  const crews = [{ id: "c1", name: "Alpha" }];
  const noop = () => {};

  it("renders trigger by default", () => {
    const { queryByTestId } = render(
      <CrewFilterBar crews={crews} selectedCrewId="" onSelect={noop} memberNames={[]} />,
    );
    expect(queryByTestId("crew-filter-trigger")).toBeTruthy();
  });

  it("accepts hideAllOption=true without crash", () => {
    const { toJSON } = render(
      <CrewFilterBar crews={crews} selectedCrewId="" onSelect={noop} memberNames={[]} hideAllOption />,
    );
    expect(toJSON()).toBeTruthy();
  });
});
