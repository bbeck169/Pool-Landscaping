/**
 * G1 · GPS Tracker unit tests.
 *
 * Mocks expo-location, expo-task-manager, AsyncStorage, fetch.
 */

/* ── Mocks (must be before all imports) ────────────────────────────── */

// In-memory AsyncStorage mock
const _store: Record<string, string> = {};
jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn((key: string) => Promise.resolve(_store[key] ?? null)),
  setItem: jest.fn((key: string, val: string) => { _store[key] = val; return Promise.resolve(); }),
  removeItem: jest.fn((key: string) => { delete _store[key]; return Promise.resolve(); }),
  clear: jest.fn(() => { Object.keys(_store).forEach(k => delete _store[k]); return Promise.resolve(); }),
}));

const mockWatchPositionAsync = jest.fn();
const mockRequestForeground = jest.fn();
const mockRequestBackground = jest.fn();
const mockStartLocationUpdatesAsync = jest.fn();
const mockStopLocationUpdatesAsync = jest.fn();

jest.mock("expo-location", () => ({
  requestForegroundPermissionsAsync: (...a: any[]) => mockRequestForeground(...a),
  requestBackgroundPermissionsAsync: (...a: any[]) => mockRequestBackground(...a),
  watchPositionAsync: (...a: any[]) => mockWatchPositionAsync(...a),
  startLocationUpdatesAsync: (...a: any[]) => mockStartLocationUpdatesAsync(...a),
  stopLocationUpdatesAsync: (...a: any[]) => mockStopLocationUpdatesAsync(...a),
  Accuracy: { Balanced: 3 },
}));

jest.mock("expo-task-manager", () => ({
  defineTask: jest.fn(),
  isTaskRegisteredAsync: jest.fn().mockResolvedValue(false),
}));

jest.mock("@/src/api", () => ({
  getAuthToken: jest.fn().mockResolvedValue("test-token-123"),
}));

// Mock global fetch
const mockFetch = jest.fn();
(global as any).fetch = mockFetch;

// Env
process.env.EXPO_PUBLIC_BACKEND_URL = "http://test-backend";

/* ── Imports (after mocks) ─────────────────────────────────────────── */

import * as GpsTracker from "@/src/services/gpsTracker";
import AsyncStorage from "@react-native-async-storage/async-storage";

/* ── Helpers ───────────────────────────────────────────────────────── */

function configResponse(enabled: boolean, fg = 60, bg = 300) {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve({
      enabled,
      ping_interval_foreground_s: fg,
      ping_interval_background_s: bg,
    }),
  };
}

function pingResponse(inserted: number, dedup = 0) {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve({ inserted, dedup_count: dedup, clock_in_id: "shift1" }),
  };
}

const QUEUE_KEY = "gps_ping_queue_g1";

/* ── Tests ─────────────────────────────────────────────────────────── */

beforeEach(async () => {
  jest.clearAllMocks();
  Object.keys(_store).forEach(k => delete _store[k]);
  // Reset tracker state
  await GpsTracker.stopTracking();
  mockRequestForeground.mockResolvedValue({ status: "granted" });
  mockRequestBackground.mockResolvedValue({ status: "granted" });
  mockWatchPositionAsync.mockResolvedValue({ remove: jest.fn() });
  mockStartLocationUpdatesAsync.mockResolvedValue(undefined);
  mockStopLocationUpdatesAsync.mockResolvedValue(undefined);
});

describe("GpsTracker", () => {

  test("startTracking no-ops when config enabled=false", async () => {
    mockFetch.mockResolvedValueOnce(configResponse(false));

    const ok = await GpsTracker.startTracking("tok");
    expect(ok).toBe(false);
    expect(GpsTracker.isTracking()).toBe(false);
    expect(mockWatchPositionAsync).not.toHaveBeenCalled();
  });

  test("startTracking requests permission and starts watch when enabled", async () => {
    mockFetch.mockResolvedValueOnce(configResponse(true, 30));

    const ok = await GpsTracker.startTracking("tok");
    expect(ok).toBe(true);
    expect(GpsTracker.isTracking()).toBe(true);
    expect(mockRequestForeground).toHaveBeenCalled();
    expect(mockWatchPositionAsync).toHaveBeenCalled();
  });

  test("startTracking returns false on permission denial", async () => {
    mockFetch.mockResolvedValueOnce(configResponse(true));
    mockRequestForeground.mockResolvedValueOnce({ status: "denied" });

    const ok = await GpsTracker.startTracking("tok");
    expect(ok).toBe(false);
    expect(GpsTracker.isTracking()).toBe(false);
  });

  test("flushBufferedPings posts batch and returns counts", async () => {
    const pings = Array.from({ length: 5 }, (_, i) => ({
      lat: 33.0 + i * 0.01,
      lon: -112.0,
      accuracy_m: 10,
      source: "foreground",
      captured_at: new Date(Date.now() - i * 1000).toISOString(),
    }));
    _store[QUEUE_KEY] = JSON.stringify(pings);

    mockFetch.mockResolvedValueOnce(pingResponse(5, 0));

    const result = await GpsTracker.flushBufferedPings();
    expect(result).not.toBeNull();
    expect(result!.inserted).toBe(5);
    expect(result!.dedup_count).toBe(0);

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/gps/pings"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  test("409 response triggers stopTracking and buffer clear", async () => {
    const pings = [{ lat: 33, lon: -112, accuracy_m: 10, source: "foreground",
                     captured_at: new Date().toISOString() }];
    _store[QUEUE_KEY] = JSON.stringify(pings);

    const stoppedCb = jest.fn();
    GpsTracker.onTrackingStopped(stoppedCb);

    mockFetch.mockResolvedValueOnce({ ok: false, status: 409 });

    const result = await GpsTracker.flushBufferedPings();
    expect(result!.inserted).toBe(0);
    expect(stoppedCb).toHaveBeenCalled();

    // Buffer should be cleared
    expect(_store[QUEUE_KEY]).toBeUndefined();
    expect(GpsTracker.isTracking()).toBe(false);
  });

  test("413 response triggers split-and-retry", async () => {
    const pings = Array.from({ length: 4 }, (_, i) => ({
      lat: 33.0 + i * 0.01, lon: -112, accuracy_m: 10,
      source: "foreground", captured_at: new Date(Date.now() - i * 1000).toISOString(),
    }));
    _store[QUEUE_KEY] = JSON.stringify(pings);

    // First call returns 413, then two halves succeed
    mockFetch
      .mockResolvedValueOnce({ ok: false, status: 413 })
      .mockResolvedValueOnce(pingResponse(2, 0))
      .mockResolvedValueOnce(pingResponse(2, 0));

    const result = await GpsTracker.flushBufferedPings();
    expect(result!.inserted).toBe(4);
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  test("stopTracking unregisters watch", async () => {
    const removeFn = jest.fn();
    mockWatchPositionAsync.mockResolvedValueOnce({ remove: removeFn });
    mockFetch.mockResolvedValueOnce(configResponse(true));

    await GpsTracker.startTracking("tok");
    expect(GpsTracker.isTracking()).toBe(true);

    await GpsTracker.stopTracking();
    expect(GpsTracker.isTracking()).toBe(false);
    expect(removeFn).toHaveBeenCalled();
  });
});
