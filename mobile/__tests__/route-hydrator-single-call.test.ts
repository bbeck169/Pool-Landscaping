/**
 * Fix 1 — Route hydrator single-call test.
 *
 * Asserts that `hydrateToday` calls GET /mobile/offline-bundle exactly
 * ONCE and does NOT call /jobs/{jid} per job.
 */

/* ── Mocks — must be declared before imports ────────────────────────── */
const mockGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...args: any[]) => mockGet(...args),
    post: jest.fn(), patch: jest.fn(), put: jest.fn(), del: jest.fn(),
  },
}));

const mockWriteCache = jest.fn().mockResolvedValue(undefined);
const mockReadCache = jest.fn().mockResolvedValue(null);
jest.mock("@/src/services/readCache", () => ({
  writeCache: (...args: any[]) => mockWriteCache(...args),
  readCache: (...args: any[]) => mockReadCache(...args),
}));

jest.mock("@/src/services/sync/netBus", () => ({
  isOnlineNow: () => true,
}));

jest.mock("@/src/services/photoUrlCache", () => ({
  stripBase64FromReport: (r: any) => r, // pass-through for this test
}));

/* ── Import after mocks ──────────────────────────────────────────── */
import { hydrateToday, subscribeHydration, CK, type HydrationMeta } from "../src/services/routeHydrator";

/* ── Test data ──────────────────────────────────────────────────── */
const JOBS = [
  { id: "job-1", customer_name: "Customer A", service_type: "cleaning" },
  { id: "job-2", customer_name: "Customer B", service_type: "chem" },
  { id: "job-3", customer_name: "Customer C", service_type: "opening" },
];

const REPORTS = [
  { job_id: "job-1", id: "sr-1", notes: "" },
  { job_id: "job-3", id: "sr-3", notes: "checked" },
];

const BUNDLE_RESPONSE = {
  jobs: JOBS,
  customers: [],
  service_reports_in_progress: REPORTS,
  chemistry_types: [],
  chemicals_catalog: [],
  invoices: [],
  job_count: 3,
  cap_reached: false,
  generated_at: "2026-04-16T12:00:00Z",
};

/* ── Tests ──────────────────────────────────────────────────────── */
describe("Fix 1 — Route hydrator single bundle call", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGet.mockReset();
    mockWriteCache.mockClear();
  });

  it("calls /mobile/offline-bundle exactly once, never /jobs/{jid}", async () => {
    mockGet.mockResolvedValue(BUNDLE_RESPONSE);

    await hydrateToday("user-123");

    // Exactly 1 API call — the bundle endpoint
    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(mockGet).toHaveBeenCalledWith(
      "/mobile/offline-bundle",
      expect.anything(),
    );

    // No per-job calls
    const calls = mockGet.mock.calls.map((c: any) => c[0]);
    const perJobCalls = calls.filter(
      (url: string) => url.startsWith("/jobs/") && !url.includes("offline-bundle"),
    );
    expect(perJobCalls).toHaveLength(0);
  });

  it("caches each job detail + bootstrap from bundle data", async () => {
    mockGet.mockResolvedValue(BUNDLE_RESPONSE);

    await hydrateToday("user-456");

    // Should have cached: todayJobs + 3x jobDetail + 3x jobBootstrap + hydrationMeta = 8
    const cacheKeys = mockWriteCache.mock.calls.map((c: any) => c[0]);
    expect(cacheKeys).toContain(CK.todayJobs("user-456"));
    expect(cacheKeys).toContain(CK.jobDetail("job-1"));
    expect(cacheKeys).toContain(CK.jobDetail("job-2"));
    expect(cacheKeys).toContain(CK.jobDetail("job-3"));
    expect(cacheKeys).toContain(CK.jobBootstrap("job-1"));
    expect(cacheKeys).toContain(CK.jobBootstrap("job-2"));
    expect(cacheKeys).toContain(CK.jobBootstrap("job-3"));
  });

  it("matches service reports to jobs by job_id", async () => {
    mockGet.mockResolvedValue(BUNDLE_RESPONSE);

    await hydrateToday("user-789");

    // job-1 has report sr-1, job-3 has report sr-3, job-2 has no report
    const bootstrapCalls = mockWriteCache.mock.calls.filter(
      (c: any) => typeof c[0] === "string" && c[0].startsWith("job:bootstrap:"),
    );

    const job1Boot = bootstrapCalls.find((c: any) => c[0] === CK.jobBootstrap("job-1"));
    expect(job1Boot?.[1]?.report?.id).toBe("sr-1");

    const job2Boot = bootstrapCalls.find((c: any) => c[0] === CK.jobBootstrap("job-2"));
    expect(job2Boot?.[1]?.report).toBeNull();

    const job3Boot = bootstrapCalls.find((c: any) => c[0] === CK.jobBootstrap("job-3"));
    expect(job3Boot?.[1]?.report?.id).toBe("sr-3");
  });

  it("notifies subscribers with progress", async () => {
    mockGet.mockResolvedValue(BUNDLE_RESPONSE);

    const updates: HydrationMeta[] = [];
    const unsub = subscribeHydration((m) => updates.push({ ...m }));

    await hydrateToday("user-notify");
    unsub();

    // Should have initial state + inProgress + progress + final
    expect(updates.length).toBeGreaterThanOrEqual(3);

    // Final state should show all 3 cached
    const final = updates[updates.length - 1];
    expect(final.cachedJobs).toBe(3);
    expect(final.totalJobs).toBe(3);
    expect(final.inProgress).toBe(false);
  });
});
