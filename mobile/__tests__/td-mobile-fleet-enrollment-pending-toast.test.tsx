/**
 * TD-mobile-fleet-enrollment-pending-toast · one-time toast on 403 not-in-fleet,
 * plus a regression lock on the already-shipped auto-start behaviour
 * (0e7fd1580 / 9ba22f2b3 / 5d1a6d427 / 72a07ea09).
 */
import React from "react";
import { AppState } from "react-native";
import { render, act, waitFor } from "@testing-library/react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

const mockPost = jest.fn();
const mockToast = jest.fn();
let mockRole = "technician";
jest.mock("@/src/api", () => {
  class ApiError extends Error {
    status: number; detail: any;
    constructor(m: string, s: number, d?: any) { super(m); this.status = s; this.detail = d; }
  }
  class ApiNetworkError extends Error {}
  return { api: { post: (u: string, b: any) => mockPost(u, b) }, ApiError, ApiNetworkError };
});
jest.mock("expo-location", () => ({
  requestForegroundPermissionsAsync: async () => ({ status: "granted" }),
  getForegroundPermissionsAsync: async () => ({ status: "granted" }),
  Accuracy: { Balanced: 3 },
  getCurrentPositionAsync: async () => ({ coords: { latitude: 1, longitude: 2, accuracy: 5, heading: 0, speed: 0 }, timestamp: 0 }),
}));
jest.mock("expo-battery", () => ({ getBatteryLevelAsync: async () => 0.9, addBatteryLevelListener: () => ({ remove: jest.fn() }) }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u1", role: mockRole } }) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockToast }) }));

import { ApiError } from "@/src/api";
import * as E from "@/src/services/fleet/locationEmitter";
import FleetEmitterRunner, { ENROLLMENT_TOAST_KEY, ENROLLMENT_TOAST_COPY, __resetEnrollmentToastGuard } from "@/src/components/fleet/FleetEmitterRunner";

const NOT_ENROLLED = () => new (ApiError as any)("Technician is not enrolled in the fleet", 403);
const pings = () => mockPost.mock.calls.filter((c) => c[0] === "/fleet/ping");
let clock = Date.UTC(2026, 9, 25, 8);

beforeEach(async () => {
  clock += 3_600_000; // _lastPingAt is module state → fresh clock per test
  jest.useFakeTimers({ now: clock });
  E.stopEmitter();
  __resetEnrollmentToastGuard();
  await AsyncStorage.clear();
  mockRole = "technician";
  mockToast.mockReset();
  mockPost.mockReset().mockResolvedValue({ ok: true });
  Object.defineProperty(AppState, "currentState", { value: "active", configurable: true });
});
afterEach(() => { E.stopEmitter(); jest.useRealTimers(); });

const mount = async () => { const q = render(<FleetEmitterRunner />); await act(async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); }); return q; };

it("F1 · regression: tech login (pause absent) → auto-start + ping sent", async () => {
  await mount();
  await waitFor(() => expect(pings().length).toBe(1));
  expect(E.isEmitterRunning()).toBe(true);
  expect(mockToast).not.toHaveBeenCalled();
});

it("F2 · regression: explicit pause respected → no start, no ping, no toast", async () => {
  await E.setPaused(true);
  await mount();
  expect(E.getEmitterStatus()).toBe("paused");
  expect(pings()).toHaveLength(0);
  expect(mockToast).not.toHaveBeenCalled();
});

it("F3 · 403 not-in-fleet → emitter stops (no retry across ticks) + ONE 'Enrollment pending — contact admin' toast", async () => {
  mockPost.mockRejectedValue(NOT_ENROLLED());
  await mount();
  await waitFor(() => expect(E.getEmitterStatus()).toBe("not_in_fleet"));
  await waitFor(() => expect(mockToast).toHaveBeenCalledWith(ENROLLMENT_TOAST_COPY, "info"));
  expect(E.isEmitterRunning()).toBe(false);
  await act(async () => { jest.advanceTimersByTime(120_000); });
  expect(pings()).toHaveLength(1); // no retry loop
  expect(mockToast).toHaveBeenCalledTimes(1);
  expect(await AsyncStorage.getItem(ENROLLMENT_TOAST_KEY)).toBe("1");
});

it("F4 · one-time across app restarts: persisted flag → a later 403 does not toast again", async () => {
  await AsyncStorage.setItem(ENROLLMENT_TOAST_KEY, "1");
  mockPost.mockRejectedValue(NOT_ENROLLED());
  await mount();
  await waitFor(() => expect(E.getEmitterStatus()).toBe("not_in_fleet"));
  await act(async () => {});
  expect(mockToast).not.toHaveBeenCalled();
});

it("F5 · other failures (500 / network) never show the enrollment toast", async () => {
  mockPost.mockRejectedValue(new (ApiError as any)("Server error", 500));
  await mount();
  await act(async () => { jest.advanceTimersByTime(20_000); });
  expect(mockToast).not.toHaveBeenCalled();
  expect(E.getEmitterStatus()).not.toBe("not_in_fleet");
});

it("F6 · non-tech (admin) → no emitter, no toast (role gate unchanged)", async () => {
  mockRole = "admin";
  await mount();
  expect(E.isEmitterRunning()).toBe(false);
  expect(pings()).toHaveLength(0);
  expect(mockToast).not.toHaveBeenCalled();
});
