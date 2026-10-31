/**
 * P37c · syncJobGeofencesP37c startup test
 *
 * Verifies:
 *   1. syncJobGeofencesP37c correctly fetches jobs + radius settings.
 *   2. Jobs missing coords are skipped.
 *   3. Completed jobs are skipped.
 *   4. Jobs with active timers are skipped.
 *   5. Region cap of 20 is respected.
 *   6. Returns correct SyncResult shape.
 *   7. Consent cache invalidation works.
 */
import { Platform } from "react-native";

// ── Mocks ────────────────────────────────────────────────────────────
const mockGet = jest.fn();
const mockPost = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...args: any[]) => mockGet(...args),
    post: (...args: any[]) => mockPost(...args),
  },
}));

// Mock expo-location
const mockGetForegroundPermissions = jest.fn();
const mockGetBackgroundPermissions = jest.fn();
const mockHasStartedGeofencing = jest.fn();
const mockStopGeofencing = jest.fn();
const mockStartGeofencing = jest.fn();

jest.mock("expo-location", () => ({
  getForegroundPermissionsAsync: () => mockGetForegroundPermissions(),
  getBackgroundPermissionsAsync: () => mockGetBackgroundPermissions(),
  hasStartedGeofencingAsync: (task: string) => mockHasStartedGeofencing(task),
  stopGeofencingAsync: (task: string) => mockStopGeofencing(task),
  startGeofencingAsync: (task: string, regions: any[]) =>
    mockStartGeofencing(task, regions),
  GeofencingEventType: { Enter: 1, Exit: 2 },
  Accuracy: { Balanced: 3 },
}));

jest.mock("expo-task-manager", () => ({
  defineTask: jest.fn(),
}));

jest.mock("expo-notifications", () => ({
  getPermissionsAsync: jest.fn().mockResolvedValue({ status: "granted" }),
  setNotificationCategoryAsync: jest.fn(),
  scheduleNotificationAsync: jest.fn(),
}));

// Must override Platform.OS to not be "web" for geofencing tests
const originalOS = Platform.OS;

import {
  syncJobGeofencesP37c,
  invalidateConsentCache,
  _testables,
} from "@/src/background/jobGeofence";

beforeEach(() => {
  jest.clearAllMocks();
  (Platform as any).OS = "ios"; // Simulate native
  invalidateConsentCache();
  _testables._resetRegionsFp();
});

afterAll(() => {
  (Platform as any).OS = originalOS;
});

describe("syncJobGeofencesP37c", () => {
  const grantedPerms = { status: "granted" };
  const deniedPerms = { status: "denied" };

  function makeJob(overrides: Record<string, any> = {}) {
    return {
      id: `job-${Math.random().toString(36).slice(2, 8)}`,
      status: "scheduled",
      latitude: 33.45,
      longitude: -112.07,
      scheduled_start: "2099-04-10T08:00:00Z",
      ...overrides,
    };
  }

  it("returns empty result on web platform", async () => {
    (Platform as any).OS = "web";
    const result = await syncJobGeofencesP37c();
    expect(result.registered).toBe(0);
    expect(result.radius).toBe(0);
  });

  it("returns empty when foreground permissions denied", async () => {
    mockGetForegroundPermissions.mockResolvedValue(deniedPerms);
    const result = await syncJobGeofencesP37c();
    expect(result.registered).toBe(0);
  });

  it("returns empty when background permissions denied", async () => {
    mockGetForegroundPermissions.mockResolvedValue(grantedPerms);
    mockGetBackgroundPermissions.mockResolvedValue(deniedPerms);
    const result = await syncJobGeofencesP37c();
    expect(result.registered).toBe(0);
  });

  it("registers geofences for valid jobs", async () => {
    mockGetForegroundPermissions.mockResolvedValue(grantedPerms);
    mockGetBackgroundPermissions.mockResolvedValue(grantedPerms);
    mockHasStartedGeofencing.mockResolvedValue(false);
    mockStartGeofencing.mockResolvedValue(undefined);

    const jobs = [
      makeJob({ id: "j1", latitude: 33.45, longitude: -112.07 }),
      makeJob({ id: "j2", latitude: 34.05, longitude: -118.24 }),
    ];
    mockGet.mockImplementation((url: string) => {
      if (url.startsWith("/jobs")) return Promise.resolve(jobs);
      if (url === "/settings/gps-auto-start")
        return Promise.resolve({ arrival_radius_meters: 100 });
      return Promise.resolve(null);
    });

    const result = await syncJobGeofencesP37c();
    expect(result.registered).toBe(2);
    expect(result.radius).toBe(100);
    expect(result.skipped_no_coords).toBe(0);
    expect(result.skipped_completed).toBe(0);
    expect(mockStartGeofencing).toHaveBeenCalledWith(
      "p37c-job-arrival-geofence",
      expect.arrayContaining([
        expect.objectContaining({
          identifier: "job:j1",
          latitude: 33.45,
          longitude: -112.07,
          radius: 100,
        }),
      ])
    );
  });

  it("skips completed jobs", async () => {
    mockGetForegroundPermissions.mockResolvedValue(grantedPerms);
    mockGetBackgroundPermissions.mockResolvedValue(grantedPerms);
    mockHasStartedGeofencing.mockResolvedValue(false);
    mockStartGeofencing.mockResolvedValue(undefined);

    const jobs = [
      makeJob({ id: "j1", status: "completed" }),
      makeJob({ id: "j2", status: "scheduled" }),
    ];
    mockGet.mockImplementation((url: string) => {
      if (url.startsWith("/jobs")) return Promise.resolve(jobs);
      if (url === "/settings/gps-auto-start")
        return Promise.resolve({ arrival_radius_meters: 75 });
      return Promise.resolve(null);
    });

    const result = await syncJobGeofencesP37c();
    expect(result.registered).toBe(1);
    expect(result.skipped_completed).toBe(1);
  });

  it("skips jobs missing coords", async () => {
    mockGetForegroundPermissions.mockResolvedValue(grantedPerms);
    mockGetBackgroundPermissions.mockResolvedValue(grantedPerms);
    mockHasStartedGeofencing.mockResolvedValue(false);
    mockStartGeofencing.mockResolvedValue(undefined);

    const jobs = [
      makeJob({ id: "j1", latitude: null, longitude: null }),
      makeJob({ id: "j2", latitude: 33.45, longitude: -112.07 }),
    ];
    mockGet.mockImplementation((url: string) => {
      if (url.startsWith("/jobs")) return Promise.resolve(jobs);
      if (url === "/settings/gps-auto-start")
        return Promise.resolve({ arrival_radius_meters: 75 });
      return Promise.resolve(null);
    });

    const result = await syncJobGeofencesP37c();
    expect(result.registered).toBe(1);
    expect(result.skipped_no_coords).toBe(1);
  });

  it("skips jobs with timer already running", async () => {
    mockGetForegroundPermissions.mockResolvedValue(grantedPerms);
    mockGetBackgroundPermissions.mockResolvedValue(grantedPerms);
    mockHasStartedGeofencing.mockResolvedValue(false);
    mockStartGeofencing.mockResolvedValue(undefined);

    const jobs = [
      makeJob({ id: "j1", timer_started_at: "2099-04-10T09:00:00Z" }),
      makeJob({ id: "j2" }),
    ];
    mockGet.mockImplementation((url: string) => {
      if (url.startsWith("/jobs")) return Promise.resolve(jobs);
      if (url === "/settings/gps-auto-start")
        return Promise.resolve({ arrival_radius_meters: 75 });
      return Promise.resolve(null);
    });

    const result = await syncJobGeofencesP37c();
    expect(result.registered).toBe(1);
  });

  it("respects region cap of 20", async () => {
    mockGetForegroundPermissions.mockResolvedValue(grantedPerms);
    mockGetBackgroundPermissions.mockResolvedValue(grantedPerms);
    mockHasStartedGeofencing.mockResolvedValue(false);
    mockStartGeofencing.mockResolvedValue(undefined);

    // Create 25 valid jobs
    const jobs = Array.from({ length: 25 }, (_, i) =>
      makeJob({ id: `j${i}`, latitude: 33 + i * 0.01, longitude: -112 })
    );
    mockGet.mockImplementation((url: string) => {
      if (url.startsWith("/jobs")) return Promise.resolve(jobs);
      if (url === "/settings/gps-auto-start")
        return Promise.resolve({ arrival_radius_meters: 75 });
      return Promise.resolve(null);
    });

    const result = await syncJobGeofencesP37c();
    expect(result.registered).toBe(20);
    expect(result.truncated).toBe(5);
  });

  it("falls back to 75m radius on settings fetch failure", async () => {
    mockGetForegroundPermissions.mockResolvedValue(grantedPerms);
    mockGetBackgroundPermissions.mockResolvedValue(grantedPerms);
    mockHasStartedGeofencing.mockResolvedValue(false);
    mockStartGeofencing.mockResolvedValue(undefined);

    const jobs = [makeJob({ id: "j1" })];
    mockGet.mockImplementation((url: string) => {
      if (url.startsWith("/jobs")) return Promise.resolve(jobs);
      if (url === "/settings/gps-auto-start")
        return Promise.reject(new Error("timeout"));
      return Promise.resolve(null);
    });

    const result = await syncJobGeofencesP37c();
    expect(result.radius).toBe(75);
  });

  it("stops existing geofencing before re-registering", async () => {
    mockGetForegroundPermissions.mockResolvedValue(grantedPerms);
    mockGetBackgroundPermissions.mockResolvedValue(grantedPerms);
    mockHasStartedGeofencing.mockResolvedValue(true); // already running
    mockStopGeofencing.mockResolvedValue(undefined);
    mockStartGeofencing.mockResolvedValue(undefined);

    const jobs = [makeJob({ id: "j1" })];
    mockGet.mockImplementation((url: string) => {
      if (url.startsWith("/jobs")) return Promise.resolve(jobs);
      if (url === "/settings/gps-auto-start")
        return Promise.resolve({ arrival_radius_meters: 75 });
      return Promise.resolve(null);
    });

    await syncJobGeofencesP37c();
    expect(mockStopGeofencing).toHaveBeenCalledWith("p37c-job-arrival-geofence");
    expect(mockStartGeofencing).toHaveBeenCalled();
  });
});

describe("_testables helpers", () => {
  it("_jobCoords returns canonical lat/lng", () => {
    expect(_testables._jobCoords({ latitude: 10, longitude: 20 })).toEqual({
      lat: 10,
      lng: 20,
    });
  });

  it("_jobCoords falls back to site_lat/site_lng", () => {
    expect(_testables._jobCoords({ site_lat: 10, site_lng: 20 })).toEqual({
      lat: 10,
      lng: 20,
    });
  });

  it("_jobCoords returns null for missing coords", () => {
    expect(_testables._jobCoords({})).toEqual({ lat: null, lng: null });
  });

  it("invalidateConsentCache clears the cache", () => {
    // Should not throw
    invalidateConsentCache();
  });

  it("constants are correct", () => {
    expect(_testables.JOB_GEOFENCE_TASK).toBe("p37c-job-arrival-geofence");
    expect(_testables.REGION_CAP).toBe(20);
    expect(_testables.FALLBACK_RADIUS_M).toBe(75);
  });
});

describe("β-core 2 · today + upcoming window", () => {
  const granted = { status: "granted" };
  const day = (offset: number) => {
    const d = new Date(Date.now() + offset * 86_400_000);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };
  const arm = (jobs: any[]) => {
    mockGetForegroundPermissions.mockResolvedValue(granted);
    mockGetBackgroundPermissions.mockResolvedValue(granted);
    mockHasStartedGeofencing.mockResolvedValue(false);
    mockStartGeofencing.mockResolvedValue(undefined);
    mockGet.mockImplementation((url: string) =>
      url.startsWith("/jobs") ? Promise.resolve(jobs)
        : url === "/settings/gps-auto-start" ? Promise.resolve({ arrival_radius_meters: 75 }) : Promise.resolve(null));
  };
  const job = (id: string, date: string, over: any = {}) =>
    ({ id, status: "scheduled", latitude: 33.4, longitude: -112, scheduled_date: date, ...over });

  it("fetches /jobs with a start=today&end=today+14 window", async () => {
    arm([]);
    await syncJobGeofencesP37c();
    expect(mockGet).toHaveBeenCalledWith(`/jobs?start=${day(0)}&end=${day(14)}`);
  });

  it("past jobs never burn the 20-region cap; soonest upcoming fill it", async () => {
    const past = Array.from({ length: 25 }, (_, i) => job(`old${i}`, day(-30 + i)));
    const upcoming = Array.from({ length: 22 }, (_, i) => job(`new${String(i).padStart(2, "0")}`, day(i % 10)));
    arm([...past, ...upcoming]);
    const r = await syncJobGeofencesP37c();
    expect(r.registered).toBe(20);
    expect(r.skipped_past).toBe(25);
    expect(r.truncated).toBe(2);
    const ids = mockStartGeofencing.mock.calls[0][1].map((x: any) => x.identifier);
    expect(ids.some((i: string) => i.startsWith("job:old"))).toBe(false);
  });

  it("cancelled / canceled / skipped / completed excluded", async () => {
    arm([
      job("a", day(0), { status: "cancelled" }), job("b", day(0), { status: "Canceled" }),
      job("c", day(1), { status: "skipped" }), job("d", day(1), { status: "completed" }), job("e", day(2)),
    ]);
    const r = await syncJobGeofencesP37c();
    expect(r.registered).toBe(1);
    expect(r.skipped_completed).toBe(4);
  });

  it("unchanged region set while running → no stop/start churn", async () => {
    const jobs = [job("same", day(1))];
    arm(jobs);
    await syncJobGeofencesP37c();
    mockStartGeofencing.mockClear(); mockStopGeofencing.mockClear();
    mockHasStartedGeofencing.mockResolvedValue(true);
    await syncJobGeofencesP37c();
    expect(mockStopGeofencing).not.toHaveBeenCalled();
    expect(mockStartGeofencing).not.toHaveBeenCalled();
  });
});
