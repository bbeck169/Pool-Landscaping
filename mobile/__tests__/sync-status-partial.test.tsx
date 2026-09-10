/**
 * Fix 3 — Sync status partial/failed test.
 *
 * Asserts:
 *   1. cached=0, total=37 → syncStatus === "failed", lastSyncedAt unchanged.
 *   2. cached=5, total=37 → syncStatus === "partial", lastSyncedAt unchanged.
 *   3. cached=37, total=37 → syncStatus === "synced", lastSyncedAt stamped.
 *   4. OfflineBadge renders "N of M" text for partial state.
 *   5. OfflineBadge renders "Sync failed" for failed state.
 */
import React from "react";
import { render } from "@testing-library/react-native";

/* ── Mocks ────────────────────────────────────────────────────────── */
const mockGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...args: any[]) => mockGet(...args),
    post: jest.fn(), patch: jest.fn(), put: jest.fn(), del: jest.fn(),
  },
}));

const mockWriteCache = jest.fn().mockResolvedValue(undefined);
jest.mock("@/src/services/readCache", () => ({
  writeCache: (...args: any[]) => mockWriteCache(...args),
  readCache: jest.fn().mockResolvedValue(null),
}));

jest.mock("@/src/services/sync/netBus", () => ({
  isOnlineNow: () => true,
}));

jest.mock("@/src/services/photoUrlCache", () => ({
  stripBase64FromReport: (r: any) => r,
}));

jest.mock("@expo/vector-icons", () => {
  const { Text } = require("react-native");
  return { Ionicons: ({ name, ...p }: any) => <Text {...p}>{name}</Text> };
});

jest.mock("@/src/theme", () => ({
  colors: { brand: "#0EA5E9", onSurface: "#0F172A", error: "#DC2626", muted: "#94A3B8", surface: "#FFF", surfaceSecondary: "#F8FAFC", border: "#E2E8F0" },
  font: { regular: "Sys", medium: "Sys", semibold: "Sys", bold: "Sys" },
  fontSize: { xs: 10, sm: 13, base: 15, lg: 17, xl: 20 },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16 },
  radius: { sm: 6, md: 10, lg: 14 },
}));

jest.mock("@/src/lib/offline/netStatus", () => ({
  useOnline: jest.fn(() => false), // offline by default
  getSecondsSinceLastSuccess: () => 120,
}));

import { hydrateToday, CK, type HydrationMeta } from "../src/services/routeHydrator";
import OfflineBadge from "../src/components/OfflineBadge";
import { useOnline } from "@/src/lib/offline/netStatus";

/* ── Helpers ──────────────────────────────────────────────────────── */
function makeBundleResponse(jobCount: number, failFrom: number = -1): any {
  const jobs = [];
  for (let i = 0; i < jobCount; i++) {
    jobs.push({ id: `job-${i}`, customer_name: `Cust ${i}` });
  }
  return {
    jobs: failFrom >= 0 ? jobs.slice(0, failFrom) : jobs,
    service_reports_in_progress: [],
    job_count: jobCount,
    cap_reached: false,
    generated_at: new Date().toISOString(),
  };
}

/* ── Tests ──────────────────────────────────────────────────────── */
describe("Fix 3 — Sync status honest reporting", () => {
  const PRIOR_CLEAN_SYNC = "2026-04-15T08:00:00.000Z";

  beforeEach(() => {
    jest.clearAllMocks();
    mockGet.mockReset();
    mockWriteCache.mockClear();
  });

  it("1. cached=0 of 37 → syncStatus='failed', lastSyncedAt unchanged", async () => {
    // Bundle returns 0 jobs out of a total of 37 (server truncated or empty window)
    mockGet.mockResolvedValue({
      jobs: [],
      service_reports_in_progress: [],
      job_count: 37,
      cap_reached: false,
      generated_at: new Date().toISOString(),
    });

    const result = await hydrateToday("user-fail");

    expect(result.syncStatus).toBe("failed");
    expect(result.cachedJobs).toBe(0);
    expect(result.totalJobs).toBe(37);
    // lastSyncedAt should NOT be stamped (remains empty from fresh state)
    expect(result.lastSyncedAt).toBe("");
  });

  it("2. cached=5 of 37 → syncStatus='partial', lastSyncedAt unchanged", async () => {
    // Bundle returns 5 jobs but server says 37 total
    mockGet.mockResolvedValue(makeBundleResponse(37, 5));

    const result = await hydrateToday("user-partial");

    expect(result.syncStatus).toBe("partial");
    expect(result.cachedJobs).toBe(5);
    expect(result.totalJobs).toBe(37);
    // lastSyncedAt not updated (no prior clean sync)
    expect(result.lastSyncedAt).toBe("");
    // lastPartialSyncAt IS stamped
    expect(result.lastPartialSyncAt).toBeTruthy();
  });

  it("3. cached=37 of 37 → syncStatus='synced', lastSyncedAt stamped", async () => {
    mockGet.mockResolvedValue(makeBundleResponse(37));

    const result = await hydrateToday("user-full");

    expect(result.syncStatus).toBe("synced");
    expect(result.cachedJobs).toBe(37);
    expect(result.totalJobs).toBe(37);
    expect(result.lastSyncedAt).toBeTruthy();
    const ts = new Date(result.lastSyncedAt).getTime();
    expect(ts).toBeGreaterThan(Date.now() - 5000);
  });

  it("4. OfflineBadge renders 'N of M' text for partial state (offline)", () => {
    (useOnline as jest.Mock).mockReturnValue(false);

    const { getByTestId } = render(
      <OfflineBadge
        testID="test-badge"
        cacheStats={{ cached: 5, total: 37, lastSyncedAt: "", syncStatus: "partial" }}
      />,
    );

    const label = getByTestId("offline-badge-label");
    const text = Array.isArray(label.children) ? label.children.join("") : String(label.children);
    expect(text).toContain("5 of 37");
  });

  it("5. OfflineBadge renders 'Sync failed' for failed state (offline)", () => {
    (useOnline as jest.Mock).mockReturnValue(false);

    const { getByTestId } = render(
      <OfflineBadge
        testID="test-badge"
        cacheStats={{ cached: 0, total: 37, lastSyncedAt: "", syncStatus: "failed" }}
      />,
    );

    const label = getByTestId("offline-badge-label");
    const text = Array.isArray(label.children) ? label.children.join("") : String(label.children);
    expect(text).toContain("sync failed");
  });

  it("6. OfflineBadge shows 'Partial sync: N of M' when ONLINE + partial", () => {
    (useOnline as jest.Mock).mockReturnValue(true);

    const { getByTestId } = render(
      <OfflineBadge
        testID="test-badge"
        cacheStats={{ cached: 10, total: 25, lastSyncedAt: "", syncStatus: "partial" }}
      />,
    );

    const label = getByTestId("offline-badge-label");
    const text = Array.isArray(label.children) ? label.children.join("") : String(label.children);
    expect(text).toContain("10 of 25");
  });
});
