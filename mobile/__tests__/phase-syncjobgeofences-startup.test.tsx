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
      scheduled_start: "2026-04-10T08:00:00Z",
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
      if (url === "/jobs") return Promise.resolve(jobs);
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
      if (url === "/jobs") return Promise.resolve(jobs);
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
      if (url === "/jobs") return Promise.resolve(jobs);
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
      makeJob({ id: "j1", timer_started_at: "2026-04-10T09:00:00Z" }),
      makeJob({ id: "j2" }),
    ];
    mockGet.mockImplementation((url: string) => {
      if (url === "/jobs") return Promise.resolve(jobs);
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
      if (url === "/jobs") return Promise.resolve(jobs);
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
      if (url === "/jobs") return Promise.resolve(jobs);
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
      if (url === "/jobs") return Promise.resolve(jobs);
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
