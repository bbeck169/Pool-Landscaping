/**
 * TD-fleet-tracking-always-on · Option A (soft always-on) Phase 1.
 * Real locationEmitter + AsyncStorage mock; expo-location / expo-battery / api mocked.
 */
import React from "react";
import { AppState, Linking } from "react-native";
import { render, fireEvent, act, renderHook, waitFor } from "@testing-library/react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

const mockReqPerm = jest.fn();
const mockGetPerm = jest.fn();
jest.mock("expo-location", () => ({
  requestForegroundPermissionsAsync: () => mockReqPerm(),
  getForegroundPermissionsAsync: () => mockGetPerm(),
  getLastKnownPositionAsync: async () => null,
}));
jest.mock("expo-battery", () => ({
  getBatteryLevelAsync: async () => 0.9,
  addBatteryLevelListener: () => ({ remove: jest.fn() }),
}));
jest.mock("@/src/api", () => {
  class ApiError extends Error { status = 0; }
  class ApiNetworkError extends Error {}
  return { api: { post: jest.fn() }, ApiError, ApiNetworkError };
});
let mockUser: any = { id: "t1", role: "technician" };
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: mockUser }) }));

import * as E from "@/src/services/fleet/locationEmitter";
import { useFleetEmitter } from "@/src/hooks/useFleetEmitter";
import FleetPauseToggle from "@/src/components/fleet/FleetPauseToggle";
import FleetPermissionBanner from "@/src/components/fleet/FleetPermissionBanner";

const PAUSE_KEY = "fleet_pause_shift";
let appHandlers: ((s: string) => any)[] = [];

beforeEach(async () => {
  E.stopEmitter();
  await AsyncStorage.clear();
  mockUser = { id: "t1", role: "technician" };
  mockReqPerm.mockReset().mockResolvedValue({ status: "granted" });
  mockGetPerm.mockReset().mockResolvedValue({ status: "granted" });
  appHandlers = [];
  jest.spyOn(AppState, "addEventListener").mockImplementation(((_t: string, cb: any) => {
    appHandlers.push(cb);
    return { remove: () => { appHandlers = appHandlers.filter((h) => h !== cb); } };
  }) as any);
});
afterEach(() => { E.stopEmitter(); jest.restoreAllMocks(); });

const foreground = async () => { await act(async () => { for (const h of [...appHandlers]) await h("active"); }); };

it("A1 · first launch (no stored pause record) → not paused; emitter starts (tracking defaults ON)", async () => {
  expect(await AsyncStorage.getItem(PAUSE_KEY)).toBeNull();
  expect(await E.isPaused()).toBe(false);
  expect(await E.startEmitter()).toBe(true);
  expect(E.isEmitterRunning()).toBe(true);
});

it("A2 · explicit pause is sticky across a cold restart → stays paused, startEmitter refuses", async () => {
  await E.setPaused(true);
  expect(await AsyncStorage.getItem(PAUSE_KEY)).toBe("1");
  E.stopEmitter(); // simulate process death; storage survives
  expect(await E.isPaused()).toBe(true);
  expect(await E.startEmitter()).toBe(false);
  expect(E.getEmitterStatus()).toBe("paused");
  expect(E.isEmitterRunning()).toBe(false);
});

it("A3 · paused then explicitly resumed → key cleared → next launch tracks", async () => {
  await E.setPaused(true);
  await E.setPaused(false);
  expect(await AsyncStorage.getItem(PAUSE_KEY)).toBeNull();
  expect(await E.startEmitter()).toBe(true);
});

it("A4 · OS permission denied → OS wins: not running, status no_permission", async () => {
  mockReqPerm.mockResolvedValue({ status: "denied" });
  expect(await E.startEmitter()).toBe(false);
  expect(E.isEmitterRunning()).toBe(false);
  expect(E.getEmitterStatus()).toBe("no_permission");
});

it("H1 · login as tech → hook auto-starts tracking; explicitly paused tech is NOT started", async () => {
  renderHook(() => useFleetEmitter());
  await waitFor(() => expect(E.isEmitterRunning()).toBe(true));
  E.stopEmitter();
  await E.setPaused(true);
  renderHook(() => useFleetEmitter());
  await act(async () => {});
  expect(E.isEmitterRunning()).toBe(false);
  expect(mockReqPerm).toHaveBeenCalledTimes(1); // no start attempt while paused
});

it("H2 · permission re-granted in Settings → foreground resumes tracking without relaunch", async () => {
  mockReqPerm.mockResolvedValueOnce({ status: "denied" });
  renderHook(() => useFleetEmitter());
  await waitFor(() => expect(E.getEmitterStatus()).toBe("no_permission"));
  mockGetPerm.mockResolvedValue({ status: "granted" });
  await foreground();
  await waitFor(() => expect(E.isEmitterRunning()).toBe(true));
});

it("H3 · still denied on foreground → stays stopped and never re-prompts (read-only check)", async () => {
  mockReqPerm.mockResolvedValue({ status: "denied" });
  renderHook(() => useFleetEmitter());
  await waitFor(() => expect(E.getEmitterStatus()).toBe("no_permission"));
  mockGetPerm.mockResolvedValue({ status: "denied" });
  await foreground();
  expect(E.isEmitterRunning()).toBe(false);
  expect(mockReqPerm).toHaveBeenCalledTimes(1);
  expect(mockGetPerm).toHaveBeenCalledTimes(1);
});

it("H4 · never overrides an explicit pause, even if permission is granted on foreground", async () => {
  mockReqPerm.mockResolvedValueOnce({ status: "denied" });
  renderHook(() => useFleetEmitter());
  await waitFor(() => expect(E.getEmitterStatus()).toBe("no_permission"));
  await AsyncStorage.setItem(PAUSE_KEY, "1"); // tech paused (key-level) while denied
  await foreground();
  expect(E.isEmitterRunning()).toBe(false);
  expect(mockGetPerm).not.toHaveBeenCalled();
});

it("H5 · non-tech (admin) → no auto-start and no foreground resume listener from the hook", async () => {
  mockUser = { id: "a1", role: "admin" };
  renderHook(() => useFleetEmitter());
  await act(async () => {});
  expect(E.isEmitterRunning()).toBe(false);
  expect(appHandlers).toHaveLength(0);
});

it("B1 · banner only for no_permission; Open Settings + dismiss work; hides once tracking resumes", async () => {
  const spy = jest.spyOn(Linking, "openSettings").mockResolvedValue(undefined as any);
  const q = render(<FleetPermissionBanner />);
  expect(q.queryByTestId("fleet-permission-banner")).toBeNull(); // stopped → hidden
  mockReqPerm.mockResolvedValueOnce({ status: "denied" });
  await act(async () => { await E.startEmitter(); });
  expect(q.getByTestId("fleet-permission-banner")).toBeTruthy();
  fireEvent.press(q.getByTestId("fleet-permission-banner-settings"));
  expect(spy).toHaveBeenCalledTimes(1);
  fireEvent.press(q.getByTestId("fleet-permission-banner-dismiss"));
  expect(q.queryByTestId("fleet-permission-banner")).toBeNull();
  await act(async () => { await E.startEmitter(); }); // re-granted → active
  expect(q.queryByTestId("fleet-permission-banner")).toBeNull();
});

it("T1 · regression: FleetPauseToggle still pauses + resumes (switch = tracking on)", async () => {
  const q = render(<FleetPauseToggle />);
  const sw = await waitFor(() => q.getByTestId("fleet-pause-toggle"));
  expect(sw.props.value).toBe(true); // default ON on first launch
  await act(async () => { fireEvent(sw, "valueChange", false); });
  expect(await AsyncStorage.getItem(PAUSE_KEY)).toBe("1");
  expect(E.getEmitterStatus()).toBe("paused");
  expect(q.getByText("Paused for this shift")).toBeTruthy();
  await act(async () => { fireEvent(q.getByTestId("fleet-pause-toggle"), "valueChange", true); });
  expect(await AsyncStorage.getItem(PAUSE_KEY)).toBeNull();
  expect(E.isEmitterRunning()).toBe(true);
});
