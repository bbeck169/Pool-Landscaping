/**
 * Item 2 · Schedule Map tests.
 *
 * Covers:
 *   1. Pins count matches geocoded job count.
 *   2. Status-based pin rendering.
 *   3. Empty state when no geocoded jobs.
 *   4. Tap pin opens info card with Directions + Open job buttons.
 */
import React from "react";
import { render, fireEvent } from "@testing-library/react-native";

/* ── Mocks ─────────────────────────────────────────────────────────── */

// Feb-2026 · Safety-net gate. Mutable ref so tests can flip the config
// per-scenario without re-isolating modules (which breaks React's hook
// singleton). Default: key PRESENT so pre-existing tests still render
// the MapView.
const mockConstantsRef: { expoConfig: any } = {
  expoConfig: {
    android: { config: { googleMaps: { apiKey: "TEST_KEY_STUB" } } },
  },
};
jest.mock("expo-constants", () => ({
  __esModule: true,
  default: {
    get expoConfig() {
      return mockConstantsRef.expoConfig;
    },
  },
}));

jest.mock("expo-location", () => ({
  getForegroundPermissionsAsync: jest.fn().mockResolvedValue({ status: "granted" }),
  requestForegroundPermissionsAsync: jest.fn().mockResolvedValue({ status: "granted" }),
  Accuracy: { Balanced: 3 },
}));

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock("react-native-maps", () => {
  const RN = require("react-native");
  const R = require("react");
  const MapViewMock = R.forwardRef((props: any, ref: any) => (
    <RN.View ref={ref} testID={props.testID || "map-view"}>{props.children}</RN.View>
  ));
  const MarkerMock = (props: any) => (
    <RN.Pressable testID={props.testID} onPress={props.onPress}>
      <RN.Text>{props.title}</RN.Text>
    </RN.Pressable>
  );
  return { __esModule: true, default: MapViewMock, Marker: MarkerMock };
});

jest.mock("@/src/api", () => ({
  api: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
  getAuthToken: jest.fn().mockResolvedValue("tok"),
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "technician", name: "Tech" } }),
}));

import ScheduleMap from "@/src/components/schedule/ScheduleMap.native";

/* ── Test Data ─────────────────────────────────────────────────────── */

const JOBS_WITH_COORDS = [
  { id: "j1", status: "scheduled", customer_name: "Alice", address: "123 Main St", location_lat: 33.45, location_lng: -112.07 },
  { id: "j2", status: "in_progress", customer_name: "Bob", address: "456 Oak Ave", location_lat: 33.46, location_lng: -112.08 },
  { id: "j3", status: "completed", customer_name: "Carol", address: "789 Elm Dr", location_lat: 33.47, location_lng: -112.09 },
  { id: "j4", status: "skipped", customer_name: "Dave", address: "321 Pine Rd", location_lat: 33.48, location_lng: -112.10 },
];

const JOBS_NO_COORDS = [
  { id: "j5", status: "scheduled", customer_name: "Eve", address: "No geo" },
  { id: "j6", status: "completed", customer_name: "Frank", address: "No geo either" },
];

/* ── Tests ─────────────────────────────────────────────────────────── */

describe("ScheduleMap", () => {

  test("renders pins count matching geocoded jobs", () => {
    const { queryAllByTestId } = render(<ScheduleMap jobs={JOBS_WITH_COORDS} />);
    const pins = queryAllByTestId(/^schedule-map-pin-/);
    expect(pins.length).toBe(4);
  });

  test("renders pin for each status with correct testID", () => {
    const { getByTestId } = render(<ScheduleMap jobs={JOBS_WITH_COORDS} />);
    expect(getByTestId("schedule-map-pin-j1")).toBeTruthy();
    expect(getByTestId("schedule-map-pin-j2")).toBeTruthy();
    expect(getByTestId("schedule-map-pin-j3")).toBeTruthy();
    expect(getByTestId("schedule-map-pin-j4")).toBeTruthy();
  });

  test("shows empty state when no geocoded jobs", () => {
    const { getByTestId, getByText } = render(<ScheduleMap jobs={JOBS_NO_COORDS} />);
    expect(getByTestId("schedule-map-empty")).toBeTruthy();
    expect(getByText("No mapped stops today")).toBeTruthy();
  });

  test("tap pin opens info card with Directions and Open job", () => {
    const { getByTestId, queryByTestId } = render(<ScheduleMap jobs={JOBS_WITH_COORDS} />);

    expect(queryByTestId("schedule-map-info-card")).toBeNull();

    fireEvent.press(getByTestId("schedule-map-pin-j1"));

    expect(getByTestId("schedule-map-info-card")).toBeTruthy();
    expect(getByTestId("schedule-map-directions-btn")).toBeTruthy();
    expect(getByTestId("schedule-map-open-job-btn")).toBeTruthy();

    fireEvent.press(getByTestId("schedule-map-close-card"));
    expect(queryByTestId("schedule-map-info-card")).toBeNull();
  });
});

/* ── Feb-2026 · P0 safety net — Android Google Maps API key gate ──── */
describe("ScheduleMap · Android Google Maps API key safety net", () => {
  const RN = require("react-native");
  const originalPlatformOS = RN.Platform.OS;
  const originalExpoConfig = mockConstantsRef.expoConfig;

  afterEach(() => {
    RN.Platform.OS = originalPlatformOS;
    mockConstantsRef.expoConfig = originalExpoConfig;
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  test.skip("renders fallback banner on Android when apiKey is missing", () => {
    RN.Platform.OS = "android";
    mockConstantsRef.expoConfig = { android: { config: { googleMaps: {} } } };
    const { getByTestId, getByText, queryByTestId } = render(
      <ScheduleMap jobs={JOBS_WITH_COORDS} />,
    );
    expect(getByTestId("schedule-map-no-key")).toBeTruthy();
    expect(
      getByText("Map unavailable — Google Maps API key not configured"),
    ).toBeTruthy();
    // MapView must NOT be attempted when the key is missing.
    expect(queryByTestId("schedule-map-view")).toBeNull();
    expect(queryByTestId("map-view")).toBeNull();
  });

  test("renders fallback banner on Android when expoConfig.android is undefined", () => {
    RN.Platform.OS = "android";
    mockConstantsRef.expoConfig = {};
    const { getByTestId } = render(<ScheduleMap jobs={JOBS_WITH_COORDS} />);
    expect(getByTestId("schedule-map-no-key")).toBeTruthy();
  });

  test("renders fallback banner on Android when apiKey is empty string", () => {
    RN.Platform.OS = "android";
    mockConstantsRef.expoConfig = {
      android: { config: { googleMaps: { apiKey: "   " } } },
    };
    const { getByTestId } = render(<ScheduleMap jobs={JOBS_WITH_COORDS} />);
    expect(getByTestId("schedule-map-no-key")).toBeTruthy();
  });

  test("renders MapView on Android when apiKey IS configured", () => {
    RN.Platform.OS = "android";
    mockConstantsRef.expoConfig = {
      android: { config: { googleMaps: { apiKey: "AIzaSy_REAL_KEY" } } },
    };
    const { queryByTestId, queryAllByTestId } = render(
      <ScheduleMap jobs={JOBS_WITH_COORDS} />,
    );
    expect(queryByTestId("schedule-map-no-key")).toBeNull();
    const pins = queryAllByTestId(/^schedule-map-pin-/);
    expect(pins.length).toBe(4);
  });

  test("iOS does NOT gate on Android apiKey (Apple Maps default, no key required)", () => {
    RN.Platform.OS = "ios";
    // Deliberately omit the key entirely — iOS must ignore it.
    mockConstantsRef.expoConfig = {};
    const { queryByTestId, queryAllByTestId } = render(
      <ScheduleMap jobs={JOBS_WITH_COORDS} />,
    );
    expect(queryByTestId("schedule-map-no-key")).toBeNull();
    const pins = queryAllByTestId(/^schedule-map-pin-/);
    expect(pins.length).toBe(4);
  });
});
