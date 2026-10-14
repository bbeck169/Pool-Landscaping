/**
 * Live Tech GPS pins — mobile parity for web 6db3c4f57.
 *
 *  A. useLiveTechLocations hook
 *     1. admin → default ON, immediate fetch + 30s poll
 *     2. technician → default OFF, never polls, canRead=false
 *     3. AppState background → stop + abort in-flight; active → resume
 *     4. unmount → interval cleared, listener removed, request aborted
 *     5. toggle persists to AsyncStorage `live_tech_overlay.<user_id>`
 *     6. persisted "0" overrides the admin default
 *  B. pure helpers — staleness → color, formatAge
 *  C. ScheduleMap.native integration — toggle, staleness-colored pins,
 *     info card, tech sees no toggle
 */
import React from "react";
import { AppState } from "react-native";
import { render, renderHook, act, waitFor, fireEvent } from "@testing-library/react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

/* ── Mocks ─────────────────────────────────────────────────────── */
const mockGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: { get: (...a: any[]) => mockGet(...a), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
  getAuthToken: jest.fn().mockResolvedValue("tok"),
}));

let mockUser: any = { id: "u-admin", role: "admin", name: "Admin" };
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: mockUser }) }));

let appStateCb: ((s: string) => void) | null = null;
const removeSpy = jest.fn();
jest.spyOn(AppState, "addEventListener").mockImplementation((_t: string, cb: any) => {
  appStateCb = cb;
  return { remove: removeSpy } as any;
});

jest.mock("expo-constants", () => ({
  __esModule: true,
  default: { expoConfig: { android: { config: { googleMaps: { apiKey: "TEST_KEY_STUB" } } } } },
}));
jest.mock("expo-location", () => ({
  getForegroundPermissionsAsync: jest.fn().mockResolvedValue({ status: "granted" }),
  requestForegroundPermissionsAsync: jest.fn().mockResolvedValue({ status: "granted" }),
  Accuracy: { Balanced: 3 },
}));
jest.mock("expo-router", () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock("react-native-maps", () => {
  const RN = require("react-native");
  const R = require("react");
  const MapViewMock = R.forwardRef((props: any, ref: any) => (
    <RN.View ref={ref} testID={props.testID || "map-view"}>{props.children}</RN.View>
  ));
  const MarkerMock = (props: any) => (
    <RN.Pressable testID={props.testID} onPress={props.onPress}>
      <RN.Text>{props.title}</RN.Text>
      {props.children}
    </RN.Pressable>
  );
  return { __esModule: true, default: MapViewMock, Marker: MarkerMock };
});

import {
  useLiveTechLocations,
  colorForStaleness,
  formatAge,
  shouldDefaultEnabled,
  POLL_INTERVAL_MS,
} from "@/src/hooks/useLiveTechLocations";
import ScheduleMap from "@/src/components/schedule/ScheduleMap.native";

const PINGS = [
  { user_id: "t1", user_name: "Mike", lat: 33.45, lon: -112.07, captured_at: "x", age_seconds: 45, staleness: "live" },
  { user_id: "t2", user_name: "Luis", lat: 33.46, lon: -112.08, captured_at: "x", age_seconds: 300, staleness: "recent" },
  { user_id: "t3", user_name: "Jose", lat: 33.47, lon: -112.09, captured_at: "x", age_seconds: 5400, staleness: "stale" },
];
const liveCalls = () => mockGet.mock.calls.filter((c) => c[0] === "/workforce/live-locations");

beforeEach(async () => {
  jest.useFakeTimers();
  mockGet.mockReset();
  mockGet.mockResolvedValue({ pings: PINGS, server_time: "2026-10-14T00:00:00Z" });
  removeSpy.mockReset();
  appStateCb = null;
  mockUser = { id: "u-admin", role: "admin", name: "Admin" };
  await AsyncStorage.clear();
});
afterEach(() => {
  jest.useRealTimers();
});

/* ── A. hook ───────────────────────────────────────────────────── */
describe("useLiveTechLocations", () => {
  it("1. admin → default ON, immediate fetch then every 30s", async () => {
    const { result } = renderHook(() => useLiveTechLocations());
    await waitFor(() => expect(liveCalls().length).toBe(1));
    expect(result.current.enabled).toBe(true);
    await waitFor(() => expect(result.current.pings).toHaveLength(3));
    expect(result.current.serverTime).toBe("2026-10-14T00:00:00Z");
    expect(liveCalls()[0][1].signal).toBeDefined();

    await act(async () => { jest.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(liveCalls().length).toBe(2);
    await act(async () => { jest.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(liveCalls().length).toBe(3);
  });

  it("2. technician → default OFF, never polls", async () => {
    mockUser = { id: "u-tech", role: "technician", department: "pool_tech" };
    const { result } = renderHook(() => useLiveTechLocations());
    await act(async () => { jest.advanceTimersByTime(POLL_INTERVAL_MS * 3); });
    expect(result.current.enabled).toBe(false);
    expect(result.current.canRead).toBe(false);
    expect(liveCalls()).toHaveLength(0);
    // Even a forced setEnabled(true) cannot poll a 403-only endpoint.
    await act(async () => { result.current.setEnabled(true); });
    await act(async () => { jest.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(liveCalls()).toHaveLength(0);
  });

  it("3. AppState background pauses (aborts in-flight), active resumes", async () => {
    let lastSignal: AbortSignal | undefined;
    mockGet.mockImplementation((_p: string, o: any) => {
      lastSignal = o?.signal;
      return new Promise(() => {}); // never resolves → stays in flight
    });
    renderHook(() => useLiveTechLocations());
    await waitFor(() => expect(liveCalls().length).toBe(1));
    expect(appStateCb).toBeTruthy();

    act(() => { appStateCb!("background"); });
    expect(lastSignal!.aborted).toBe(true);
    await act(async () => { jest.advanceTimersByTime(POLL_INTERVAL_MS * 3); });
    expect(liveCalls().length).toBe(1); // paused

    act(() => { appStateCb!("active"); });
    expect(liveCalls().length).toBe(2); // immediate fetch on resume
    await act(async () => { jest.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(liveCalls().length).toBe(3); // interval restarted
  });

  it("4. unmount → interval cleared, AppState listener removed, request aborted", async () => {
    let lastSignal: AbortSignal | undefined;
    mockGet.mockImplementation((_p: string, o: any) => {
      lastSignal = o?.signal;
      return new Promise(() => {});
    });
    const { unmount } = renderHook(() => useLiveTechLocations());
    await waitFor(() => expect(liveCalls().length).toBe(1));
    unmount();
    expect(removeSpy).toHaveBeenCalled();
    expect(lastSignal!.aborted).toBe(true);
    await act(async () => { jest.advanceTimersByTime(POLL_INTERVAL_MS * 3); });
    expect(liveCalls().length).toBe(1);
  });

  it("5. toggle persists to AsyncStorage keyed by user_id; OFF clears pings + stops polling", async () => {
    const { result } = renderHook(() => useLiveTechLocations());
    await waitFor(() => expect(result.current.pings).toHaveLength(3));

    await act(async () => { result.current.setEnabled(false); });
    expect(await AsyncStorage.getItem("live_tech_overlay.u-admin")).toBe("0");
    expect(result.current.enabled).toBe(false);
    expect(result.current.pings).toHaveLength(0);
    const n = liveCalls().length;
    await act(async () => { jest.advanceTimersByTime(POLL_INTERVAL_MS * 2); });
    expect(liveCalls().length).toBe(n);

    await act(async () => { result.current.setEnabled(true); });
    expect(await AsyncStorage.getItem("live_tech_overlay.u-admin")).toBe("1");
    await waitFor(() => expect(liveCalls().length).toBe(n + 1));
  });

  it("6. persisted \"0\" overrides the admin default (no fetch)", async () => {
    await AsyncStorage.setItem("live_tech_overlay.u-admin", "0");
    const { result } = renderHook(() => useLiveTechLocations());
    await waitFor(() => expect(result.current.enabled).toBe(false));
    await act(async () => { jest.advanceTimersByTime(POLL_INTERVAL_MS * 2); });
    expect(liveCalls()).toHaveLength(0);
  });
});

/* ── B. helpers ────────────────────────────────────────────────── */
describe("live-tech helpers", () => {
  it("staleness → color (green / yellow / gray; unknown → gray)", () => {
    expect(colorForStaleness("live")).toBe("#22c55e");
    expect(colorForStaleness("recent")).toBe("#eab308");
    expect(colorForStaleness("stale")).toBe("#94a3b8");
    expect(colorForStaleness("bogus")).toBe("#94a3b8");
    expect(colorForStaleness(undefined)).toBe("#94a3b8");
  });

  it("formatAge", () => {
    expect(formatAge(45)).toBe("45s ago");
    expect(formatAge(300)).toBe("5m ago");
    expect(formatAge(3600)).toBe("1h ago");
    expect(formatAge(5400)).toBe("1h 30m ago");
    expect(formatAge(-3)).toBe("0s ago");
  });

  it("role gate matches backend _GPS_READ_ROLES", () => {
    for (const r of ["admin", "super_admin", "owner", "manager", "dispatcher", "ADMIN"]) {
      expect(shouldDefaultEnabled(r)).toBe(true);
    }
    for (const r of ["technician", "customer", "", undefined]) {
      expect(shouldDefaultEnabled(r as any)).toBe(false);
    }
  });
});

/* ── C. ScheduleMap integration ────────────────────────────────── */
const JOBS = [
  { id: "j1", status: "scheduled", customer_name: "Alice", address: "1 Main", location_lat: 33.4, location_lng: -112.0 },
];
const flat = (st: any) => Object.assign({}, ...[].concat(st).flat(Infinity).filter(Boolean));

describe("ScheduleMap · live-tech overlay", () => {
  it("admin: toggle ON, staleness-colored pins, press → info card", async () => {
    const { getByTestId, findByTestId, getByText } = render(<ScheduleMap jobs={JOBS} />);
    const toggle = getByTestId("schedule-map-live-tech-toggle");
    expect(getByText("Live techs on")).toBeTruthy();
    expect(toggle.props.accessibilityState).toEqual({ checked: true });

    await findByTestId("schedule-map-live-tech-pin-t1");
    expect(flat(getByTestId("schedule-map-live-tech-dot-t1").props.style).backgroundColor).toBe("#22c55e");
    expect(flat(getByTestId("schedule-map-live-tech-dot-t2").props.style).backgroundColor).toBe("#eab308");
    expect(flat(getByTestId("schedule-map-live-tech-dot-t3").props.style).backgroundColor).toBe("#94a3b8");
    expect(getByTestId("schedule-map-pin-j1")).toBeTruthy(); // job pins untouched

    fireEvent.press(getByTestId("schedule-map-live-tech-pin-t2"));
    expect(getByTestId("schedule-map-live-tech-info-t2")).toBeTruthy();
    expect(getByText("updated 5m ago")).toBeTruthy();
    expect(getByTestId("schedule-map-live-tech-staleness-t2")).toBeTruthy();

    // Toggle OFF → pins gone, preference saved.
    await act(async () => { fireEvent.press(toggle); });
    expect(getByText("Show live techs")).toBeTruthy();
    await waitFor(() => expect(() => getByTestId("schedule-map-live-tech-pin-t1")).toThrow());
    expect(await AsyncStorage.getItem("live_tech_overlay.u-admin")).toBe("0");
  });

  it("technician: no toggle, no live pins, no live-locations call", async () => {
    mockUser = { id: "u-tech", role: "technician", department: "landscaping" };
    const { queryByTestId } = render(<ScheduleMap jobs={JOBS} />);
    await act(async () => { jest.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(queryByTestId("schedule-map-live-tech-toggle")).toBeNull();
    expect(queryByTestId("schedule-map-live-tech-pin-t1")).toBeNull();
    expect(liveCalls()).toHaveLength(0);
  });

  it("no mapped jobs but live techs → map still renders the tech pins", async () => {
    const { findByTestId, queryByTestId } = render(<ScheduleMap jobs={[]} />);
    await findByTestId("schedule-map-live-tech-pin-t1");
    expect(queryByTestId("schedule-map-empty")).toBeNull();
  });
});
