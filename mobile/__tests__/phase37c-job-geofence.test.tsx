/**
 * Feb-2026 · P37c — jobGeofence.ts region-sync + entry-gate tests.
 *
 * Focus: the pure logic — region cap, coord-picking, radius fetch,
 * consent gate. Native-only surfaces are mocked so the module runs
 * on the Jest node runtime.
 */
const mockGet = jest.fn();
const mockPost = jest.fn();

jest.mock("@/src/api", () => ({
  api: { get: (...a: any[]) => mockGet(...a),
           post: (...a: any[]) => mockPost(...a) },
}));

// Native mocks — expo-* modules would otherwise blow up on node.
const mockStartGeofencing = jest.fn(async () => {});
const mockStopGeofencing = jest.fn(async () => {});
const mockHasStarted = jest.fn(async () => false);
jest.mock("expo-location", () => ({
  GeofencingEventType: { Enter: 1, Exit: 2 },
  getForegroundPermissionsAsync: async () => ({ status: "granted" }),
  getBackgroundPermissionsAsync: async () => ({ status: "granted" }),
  hasStartedGeofencingAsync: (t: string) => mockHasStarted(t),
  startGeofencingAsync: (t: string, r: any[]) => mockStartGeofencing(t, r),
  stopGeofencingAsync: (t: string) => mockStopGeofencing(t),
}));
jest.mock("expo-task-manager", () => ({ defineTask: jest.fn() }));
jest.mock("expo-notifications", () => ({
  getPermissionsAsync: async () => ({ status: "granted" }),
  setNotificationCategoryAsync: async () => true,
  scheduleNotificationAsync: async () => "id",
}));
jest.mock("react-native", () => ({ Platform: { OS: "ios" } }));


import { syncJobGeofencesP37c, _testables } from
    "../src/background/jobGeofence";


beforeEach(() => {
  jest.clearAllMocks();
  mockStartGeofencing.mockResolvedValue(undefined);
  mockStopGeofencing.mockResolvedValue(undefined);
  mockHasStarted.mockResolvedValue(false);
});


function _job(id: string, over: any = {}) {
  return {
    id, status: "scheduled",
    scheduled_start: `2026-06-15T${String((parseInt(id, 36) % 20) + 8)
                          .padStart(2, "0")}:00:00Z`,
    latitude: 33.5806, longitude: -112.2374, ...over,
  };
}


describe("jobGeofence · P37c region sync", () => {
  it("uses tenant radius from settings fetch", async () => {
    mockGet.mockImplementation((path: string) => {
      if (path === "/settings/gps-auto-start") {
        return Promise.resolve({ arrival_radius_meters: 120 });
      }
      if (path === "/jobs") return Promise.resolve([_job("a")]);
      return Promise.resolve({});
    });
    const res = await syncJobGeofencesP37c();
    expect(res.radius).toBe(120);
    expect(mockStartGeofencing).toHaveBeenCalled();
    const regions = mockStartGeofencing.mock.calls[0][1] as any[];
    expect(regions[0].radius).toBe(120);
  });

  it("falls back to 75m if settings fetch fails", async () => {
    mockGet.mockImplementation((path: string) => {
      if (path === "/settings/gps-auto-start") return Promise.reject(new Error("boom"));
      if (path === "/jobs") return Promise.resolve([_job("a")]);
      return Promise.resolve({});
    });
    const res = await syncJobGeofencesP37c();
    expect(res.radius).toBe(75);
  });

  it("skips jobs without coords + jobs with status=completed", async () => {
    mockGet.mockImplementation((path: string) => {
      if (path === "/settings/gps-auto-start")
        return Promise.resolve({ arrival_radius_meters: 75 });
      if (path === "/jobs") return Promise.resolve([
        _job("a"),
        _job("b", { latitude: null, longitude: null }),
        _job("c", { status: "completed" }),
      ]);
      return Promise.resolve({});
    });
    const res = await syncJobGeofencesP37c();
    expect(res.registered).toBe(1);
    expect(res.skipped_no_coords).toBe(1);
    expect(res.skipped_completed).toBe(1);
  });

  it("caps region set at 20 and reports truncated count", async () => {
    const many = Array.from({ length: 25 }, (_, i) =>
      _job(`j${i}`, { scheduled_start: `2026-06-15T${String(i + 6).padStart(2, "0")}:00:00Z` }),
    );
    mockGet.mockImplementation((path: string) => {
      if (path === "/settings/gps-auto-start")
        return Promise.resolve({ arrival_radius_meters: 75 });
      if (path === "/jobs") return Promise.resolve(many);
      return Promise.resolve({});
    });
    const res = await syncJobGeofencesP37c();
    expect(res.registered).toBe(20);
    expect(res.truncated).toBe(5);
  });

  it("prefers canonical latitude/longitude over legacy site_lat/lng", async () => {
    const j = { id: "z", status: "scheduled",
      latitude: 40.0, longitude: -80.0,
      site_lat: 10.0, site_lng: 20.0 };
    const { lat, lng } = _testables._jobCoords(j);
    expect(lat).toBe(40.0);
    expect(lng).toBe(-80.0);
  });

  it("falls back to legacy site_lat/lng when canonical fields missing", () => {
    const j = { id: "z", status: "scheduled",
      site_lat: 10.0, site_lng: 20.0 };
    const { lat, lng } = _testables._jobCoords(j);
    expect(lat).toBe(10.0);
    expect(lng).toBe(20.0);
  });
});
