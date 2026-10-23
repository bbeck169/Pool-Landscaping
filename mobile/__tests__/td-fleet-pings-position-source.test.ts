/**
 * TD-fleet-pings-not-reaching-be · Lane A — position source swap in _doPing.
 * getLastKnownPositionAsync() (null on web / cold-start native → every ping
 * silently skipped) → getCurrentPositionAsync({ accuracy: Balanced }) with a
 * try/catch skip + __DEV__-only console.warn on every short-circuit path.
 */
import fs from "fs";
import path from "path";
import { AppState } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

const mockPost = jest.fn();
const mockCur = jest.fn();
const mockLast = jest.fn();
const mockBatt = jest.fn();
jest.mock("expo-location", () => ({
  requestForegroundPermissionsAsync: async () => ({ status: "granted" }),
  Accuracy: { Balanced: 3 },
  getCurrentPositionAsync: (o: any) => mockCur(o),
  getLastKnownPositionAsync: () => mockLast(),
}));
jest.mock("expo-battery", () => ({
  getBatteryLevelAsync: () => mockBatt(),
  addBatteryLevelListener: () => ({ remove: jest.fn() }),
}));
jest.mock("@/src/api", () => {
  class ApiError extends Error { status = 0; }
  class ApiNetworkError extends Error {}
  return { api: { post: (u: string, b: any) => mockPost(u, b) }, ApiError, ApiNetworkError };
});

import * as E from "@/src/services/fleet/locationEmitter";

const FIX = { coords: { latitude: 33.45, longitude: -112.07, accuracy: 65, heading: 90, speed: 10 }, timestamp: 0 };
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const pings = () => mockPost.mock.calls.filter((c) => c[0] === "/fleet/ping");
let warn: jest.SpyInstance;
let appHandler: ((s: string) => void) | null = null;
let clock = Date.UTC(2026, 9, 22, 12);

beforeEach(async () => {
  // _lastPingAt is module state (not reset by stopEmitter) → give every test a fresh clock hour.
  clock += 3_600_000;
  jest.useFakeTimers({ now: clock });
  E.stopEmitter();
  await AsyncStorage.clear();
  mockPost.mockReset().mockResolvedValue({ ok: true });
  mockCur.mockReset().mockResolvedValue(FIX);
  mockLast.mockReset().mockResolvedValue(null);
  mockBatt.mockReset().mockResolvedValue(0.8);
  Object.defineProperty(AppState, "currentState", { value: "active", configurable: true });
  jest.spyOn(AppState, "addEventListener").mockImplementation(((_t: string, cb: any) => {
    appHandler = cb;
    return { remove: jest.fn() };
  }) as any);
  warn = jest.spyOn(console, "warn").mockImplementation(() => {});
});
afterEach(() => { E.stopEmitter(); jest.useRealTimers(); jest.restoreAllMocks(); (global as any).__DEV__ = true; });

const start = async () => { await E.startEmitter(); await flush(); };
const warned = (needle: string) => warn.mock.calls.some((c) => String(c[0]).includes(needle));

it("L1 · start → getCurrentPositionAsync({accuracy: Balanced}) → POST /fleet/ping with the full body; last-known never used", async () => {
  await start();
  expect(mockCur).toHaveBeenCalledWith({ accuracy: 3 });
  expect(mockLast).not.toHaveBeenCalled();
  expect(pings()).toHaveLength(1);
  expect(pings()[0][1]).toEqual({
    lat: 33.45, lng: -112.07, accuracy_m: 65, speed_kmh: 36, heading_deg: 90, battery_pct: 80,
    device_time: new Date(clock).toISOString(),
  });
  expect(E.getEmitterStatus()).toBe("active");
});

it("L2 · fires a ping on each 15 s tick (cadence unchanged)", async () => {
  await start();
  for (let tick = 1; tick <= 3; tick++) {
    jest.advanceTimersByTime(15_000);
    await flush();
    expect(pings()).toHaveLength(1 + tick);
  }
  jest.advanceTimersByTime(14_000);
  await flush();
  expect(pings()).toHaveLength(4); // nothing between ticks
});

it("L3 · getCurrentPositionAsync rejects → ping skipped cleanly (no throw), dev warn, emitter keeps running; next tick recovers", async () => {
  mockCur.mockRejectedValueOnce(new Error("Location request timed out"));
  await expect(E.startEmitter()).resolves.toBe(true);
  await flush();
  expect(pings()).toHaveLength(0);
  expect(warned("getCurrentPositionAsync failed")).toBe(true);
  expect(E.isEmitterRunning()).toBe(true);
  expect(E.getEmitterStatus()).toBe("active"); // status machine untouched
  jest.advanceTimersByTime(15_000);
  await flush();
  expect(pings()).toHaveLength(1);
});

it("L4 · null position → skipped with a dev warn", async () => {
  mockCur.mockResolvedValueOnce(null);
  await start();
  expect(pings()).toHaveLength(0);
  expect(warned("no position available")).toBe(true);
});

it("L5 · battery read fails → ping still sent without battery_pct, dev warn", async () => {
  mockBatt.mockRejectedValue(new Error("battery unavailable"));
  await start();
  expect(pings()).toHaveLength(1);
  expect(pings()[0][1].battery_pct).toBeUndefined();
  expect(warned("battery level unavailable")).toBe(true);
});

it("L6 · rate limit (<5 s since last ping, e.g. quick foreground bounce) → skipped with a dev warn", async () => {
  await start();
  appHandler?.("background");
  appHandler?.("active");
  await flush();
  expect(pings()).toHaveLength(1);
  expect(warned("rate limit")).toBe(true);
});

it("L7 · production (__DEV__ = false) → short-circuits stay silent", async () => {
  (global as any).__DEV__ = false;
  mockCur.mockRejectedValueOnce(new Error("timeout"));
  await start();
  mockCur.mockResolvedValueOnce(null);
  jest.advanceTimersByTime(15_000);
  await flush();
  expect(pings()).toHaveLength(0);
  expect(warn).not.toHaveBeenCalled();
});

it("L8 · source lock: cadence constants + status-before-first-ping timing unchanged; last-known gone from _doPing", () => {
  const src = fs.readFileSync(path.resolve(__dirname, "../src/services/fleet/locationEmitter.ts"), "utf8");
  for (const c of ["ACTIVE_INTERVAL_MS = 15_000", "IDLE_INTERVAL_MS = 60_000", "LOW_BATT_ACTIVE_MS = 60_000",
    "LOW_BATT_IDLE_MS = 300_000", "RETRY_BACKOFF_MS = 5_000", "now - _lastPingAt < 5000"]) expect(src).toContain(c);
  expect(src).not.toMatch(/await Location\.getLastKnownPositionAsync\(/);
  expect(src).toContain("getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced })");
  expect(src).toMatch(/_setStatus\(_appActive \? "active" : "idle"\)/);
});
