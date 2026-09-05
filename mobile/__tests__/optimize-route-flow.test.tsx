/**
 * Feb-2026 · Optimize Route mobile flow — Jest suite (sub-phase B).
 *
 * Covers 8 behavioural assertions built on top of the DailyRouteMap
 * component. All API calls are mocked; expo-location is mocked to
 * simulate both the granted + denied permission paths.
 *
 *   1. Pill hidden when < 2 pending / reshufflable jobs.
 *   2. Pill hidden when the auto-preview returns no_change / 0 savings.
 *   3. GPS permission denied → fallback path uses first pending stop's
 *      coords, note visible in the preview modal.
 *   4. Tech role Apply → POST /jobs/route-optimization/request with the
 *      correct body, shows the "suggestion sent" toast, pill disables.
 *   5. Admin role Apply → POST /jobs/route-optimization/apply, undo toast
 *      renders with the "Undo" button.
 *   6. Undo tap within 10 s → POST /jobs/route-optimization/undo, toast
 *      clears.
 *   7. Undo tap after 10 s → toast auto-dismissed, no /undo call fires.
 *   8. Cancel button on the preview modal closes it without any /request
 *      or /apply API call.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

/* ── Mocks (declared before imports) ─────────────────────────────── */

jest.mock("@react-native-async-storage/async-storage", () =>
  require("@react-native-async-storage/async-storage/jest/async-storage-mock"),
);

const mockRouterPush = jest.fn();
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockRouterPush }),
}));

// Phase K46 · react-native-maps — mirror the mock used in
// schedule-daily-route-map.test.tsx. MapView acts as a passthrough
// View; Marker forwards its ``onPress`` and identifier so callout
// interactions remain queryable in Jest.
jest.mock("react-native-maps", () => {
  const RN = require("react-native");
  const R = require("react");
  const MapViewMock = R.forwardRef((props: any, ref: any) => {
    R.useImperativeHandle(
      ref,
      () => ({
        fitToCoordinates: jest.fn(),
        animateToRegion: jest.fn(),
        animateCamera: jest.fn(),
      }),
      [],
    );
    return R.createElement(
      RN.View,
      { ref, testID: props.testID },
      props.children,
    );
  });
  const MarkerMock = (props: any) =>
    R.createElement(
      RN.Pressable,
      { testID: props.identifier, onPress: props.onPress },
      props.children,
    );
  return {
    __esModule: true,
    default: MapViewMock,
    Marker: MarkerMock,
    Callout: (p: any) => R.createElement(RN.View, null, p.children),
    Polyline: () => null,
    PROVIDER_GOOGLE: "google",
  };
});

// expo-location — permission + position are controlled per-test.
const mockGetForegroundPerms = jest.fn();
const mockRequestForegroundPerms = jest.fn();
const mockGetCurrentPosition = jest.fn();
jest.mock("expo-location", () => ({
  getForegroundPermissionsAsync: (...a: any[]) => mockGetForegroundPerms(...a),
  requestForegroundPermissionsAsync: (...a: any[]) => mockRequestForegroundPerms(...a),
  getCurrentPositionAsync: (...a: any[]) => mockGetCurrentPosition(...a),
  Accuracy: { Balanced: 3 },
}));

// API mock — the module under test only calls .post(...).
const mockApiPost = jest.fn();
jest.mock("@/src/api", () => ({
  api: { post: (...a: any[]) => mockApiPost(...a) },
  getAuthToken: async () => "tok",
}));

// Role mock — flipped per test via mockAuthUser.role.
const mockAuthUser: { role: string; id: string } = { role: "technician", id: "u_tech" };
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: mockAuthUser }),
}));

const AsyncStorageMock = require("@react-native-async-storage/async-storage");

/* ── Component under test ──────────────────────────────────────── */

import DailyRouteMap from "@/src/components/schedule/DailyRouteMap";

/* ── Fixtures ──────────────────────────────────────────────────── */

const SCHEDULED_DATE = "2026-05-01";

/** Three reshufflable jobs with coords — enough for the pill to consider showing. */
const THREE_PENDING = [
  { id: "j1", status: "scheduled", route_index: 1, scheduled_date: SCHEDULED_DATE,
    customer_name: "Alice", address: "1 Palm Ln",
    scheduled_time: "09:00", scheduled_time_end: "09:45",
    property: { location: { lat: 33.45, lng: -112.07 } } },
  { id: "j2", status: "scheduled", route_index: 2, scheduled_date: SCHEDULED_DATE,
    customer_name: "Bob", address: "2 Oak St",
    scheduled_time: "10:15",
    property: { location: { lat: 33.46, lng: -112.08 } } },
  { id: "j3", status: "scheduled", route_index: 3, scheduled_date: SCHEDULED_DATE,
    customer_name: "Carol", address: "3 Elm Dr",
    scheduled_time: "11:00",
    property: { location: { lat: 33.47, lng: -112.09 } } },
];

/** Only 1 reshufflable job (pill should hide). */
const ONE_PENDING = [THREE_PENDING[0]];

/* ── Setup / teardown ──────────────────────────────────────────── */

const _POSITIVE_PREVIEW = {
  proposed_order: ["j2", "j1", "j3"],
  miles_saved: 2.4,
  minutes_saved: 4.8,
  stops_affected: 2,
  no_change: false,
};
const _NOOP_PREVIEW = {
  proposed_order: ["j1", "j2", "j3"],
  miles_saved: 0,
  minutes_saved: 0,
  stops_affected: 0,
  no_change: true,
};

beforeEach(() => {
  jest.useFakeTimers();
  AsyncStorageMock.clear && AsyncStorageMock.clear();
  mockRouterPush.mockClear();
  mockApiPost.mockReset();
  mockGetForegroundPerms.mockReset();
  mockRequestForegroundPerms.mockReset();
  mockGetCurrentPosition.mockReset();
  mockAuthUser.role = "technician";
  mockAuthUser.id = "u_tech";
});

afterEach(() => {
  jest.useRealTimers();
});

/** Mount + settle initial auto-preview call so `showPill` derives cleanly. */
async function mountAndSettle(jobs: any[], previewResp: any | Error | null = _POSITIVE_PREVIEW) {
  if (previewResp && !(previewResp instanceof Error)) {
    mockApiPost.mockImplementation((path: string) => {
      if (path === "/jobs/route-optimization/preview") return Promise.resolve(previewResp);
      return Promise.resolve({});
    });
  } else if (previewResp instanceof Error) {
    mockApiPost.mockRejectedValue(previewResp);
  } else {
    mockApiPost.mockResolvedValue({});
  }
  const view = render(<DailyRouteMap jobs={jobs} userId="u_tech" />);
  // Flush the initial auto-preview effect.
  await act(async () => { await Promise.resolve(); });
  await act(async () => { await Promise.resolve(); });
  return view;
}

/* ═══════════════════════════════════════════════════════════════ */

describe("Optimize Route — mobile flow (sub-phase B)", () => {
  /* 1 ─────────────────────────────────────────────────────────── */
  it("hides the pill when reshufflable jobs count < 2", async () => {
    const { queryByTestId } = await mountAndSettle(ONE_PENDING, _POSITIVE_PREVIEW);
    expect(queryByTestId("optimize-route-pill")).toBeNull();
    // Auto-preview should not have been called with only 1 reshufflable stop.
    const previewCalls = mockApiPost.mock.calls.filter(
      (c) => c[0] === "/jobs/route-optimization/preview",
    );
    expect(previewCalls.length).toBe(0);
  });

  /* 2 ─────────────────────────────────────────────────────────── */
  it("hides the pill when the preview returns no_change / 0 savings", async () => {
    const { queryByTestId } = await mountAndSettle(THREE_PENDING, _NOOP_PREVIEW);
    expect(queryByTestId("optimize-route-pill")).toBeNull();
    // Auto-preview WAS called — but savings = 0 so pill stays hidden.
    const previewCalls = mockApiPost.mock.calls.filter(
      (c) => c[0] === "/jobs/route-optimization/preview",
    );
    expect(previewCalls.length).toBe(1);
  });

  /* 3 ─────────────────────────────────────────────────────────── */
  it("GPS-denied path uses first pending stop as origin + shows fallback note", async () => {
    mockGetForegroundPerms.mockResolvedValue({ status: "denied" });
    const { getByTestId } = await mountAndSettle(THREE_PENDING, _POSITIVE_PREVIEW);

    await waitFor(() => expect(getByTestId("optimize-route-pill")).toBeTruthy());
    // Reset mock so the pill-tap preview call is unambiguous.
    mockApiPost.mockClear();
    mockApiPost.mockResolvedValue(_POSITIVE_PREVIEW);

    await act(async () => { fireEvent.press(getByTestId("optimize-route-pill")); });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });

    // Preview call sent with the FIRST pending stop's coords (j1 → 33.45/-112.07).
    const tapPreview = mockApiPost.mock.calls.find(
      (c) => c[0] === "/jobs/route-optimization/preview",
    );
    expect(tapPreview).toBeTruthy();
    expect(tapPreview![1]).toMatchObject({
      date: SCHEDULED_DATE,
      current_lat: 33.45,
      current_lng: -112.07,
    });
    // Modal open + fallback note rendered.
    expect(getByTestId("optimize-route-preview-modal")).toBeTruthy();
    expect(getByTestId("optimize-route-preview-fallback-note")).toBeTruthy();
  });

  /* 4 ─────────────────────────────────────────────────────────── */
  it("tech Apply → POST /request, suggestion toast shows, pill disables", async () => {
    mockAuthUser.role = "technician";
    mockGetForegroundPerms.mockResolvedValue({ status: "granted" });
    mockGetCurrentPosition.mockResolvedValue({
      coords: { latitude: 33.44, longitude: -112.04 },
    });
    const { getByTestId, queryByTestId } = await mountAndSettle(THREE_PENDING, _POSITIVE_PREVIEW);
    await waitFor(() => expect(getByTestId("optimize-route-pill")).toBeTruthy());

    // Tap pill → GPS resolves → /preview re-runs (returns positive)
    mockApiPost.mockClear();
    mockApiPost.mockImplementation((path: string) => {
      if (path === "/jobs/route-optimization/preview") return Promise.resolve(_POSITIVE_PREVIEW);
      if (path === "/jobs/route-optimization/request") return Promise.resolve({ id: "req_1" });
      return Promise.resolve({});
    });

    await act(async () => { fireEvent.press(getByTestId("optimize-route-pill")); });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });

    // Tap Apply — tech path submits /request.
    await act(async () => { fireEvent.press(getByTestId("optimize-route-preview-apply")); });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });

    const requestCall = mockApiPost.mock.calls.find(
      (c) => c[0] === "/jobs/route-optimization/request",
    );
    expect(requestCall).toBeTruthy();
    expect(requestCall![1]).toMatchObject({ date: SCHEDULED_DATE });
    // No admin-only /apply was called.
    const applyCall = mockApiPost.mock.calls.find(
      (c) => c[0] === "/jobs/route-optimization/apply",
    );
    expect(applyCall).toBeUndefined();
    // Suggestion toast appeared; undo toast did NOT.
    expect(getByTestId("optimize-route-suggestion-toast")).toBeTruthy();
    expect(queryByTestId("optimize-route-undo-toast")).toBeNull();
    // Modal closed.
    expect(queryByTestId("optimize-route-preview-modal-visible")).toBeNull();
    // Pill hidden (pendingSubmitted flag).
    expect(queryByTestId("optimize-route-pill")).toBeNull();
  });

  /* 5 ─────────────────────────────────────────────────────────── */
  it("admin Apply → POST /apply, undo toast renders with Undo button", async () => {
    mockAuthUser.role = "admin";
    mockAuthUser.id = "u_admin";
    mockGetForegroundPerms.mockResolvedValue({ status: "granted" });
    mockGetCurrentPosition.mockResolvedValue({
      coords: { latitude: 33.44, longitude: -112.04 },
    });
    const { getByTestId, queryByTestId } = await mountAndSettle(THREE_PENDING, _POSITIVE_PREVIEW);
    await waitFor(() => expect(getByTestId("optimize-route-pill")).toBeTruthy());

    mockApiPost.mockClear();
    mockApiPost.mockImplementation((path: string) => {
      if (path === "/jobs/route-optimization/preview") return Promise.resolve(_POSITIVE_PREVIEW);
      if (path === "/jobs/route-optimization/apply") return Promise.resolve({
        applied_id: "applied_42", applied_at: "2026-05-01T09:00:00+00:00",
      });
      return Promise.resolve({});
    });

    await act(async () => { fireEvent.press(getByTestId("optimize-route-pill")); });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });

    await act(async () => { fireEvent.press(getByTestId("optimize-route-preview-apply")); });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });

    const applyCall = mockApiPost.mock.calls.find(
      (c) => c[0] === "/jobs/route-optimization/apply",
    );
    expect(applyCall).toBeTruthy();
    // Undo toast up, Undo button pressable, suggestion toast absent.
    expect(getByTestId("optimize-route-undo-toast")).toBeTruthy();
    expect(getByTestId("optimize-route-undo-btn")).toBeTruthy();
    expect(queryByTestId("optimize-route-suggestion-toast")).toBeNull();
  });

  /* 6 ─────────────────────────────────────────────────────────── */
  it("Undo tap within 10 s → POST /undo, toast clears", async () => {
    mockAuthUser.role = "admin";
    mockGetForegroundPerms.mockResolvedValue({ status: "granted" });
    mockGetCurrentPosition.mockResolvedValue({
      coords: { latitude: 33.44, longitude: -112.04 },
    });
    const { getByTestId, queryByTestId } = await mountAndSettle(THREE_PENDING, _POSITIVE_PREVIEW);
    await waitFor(() => expect(getByTestId("optimize-route-pill")).toBeTruthy());

    mockApiPost.mockImplementation((path: string) => {
      if (path === "/jobs/route-optimization/preview") return Promise.resolve(_POSITIVE_PREVIEW);
      if (path === "/jobs/route-optimization/apply") return Promise.resolve({
        applied_id: "applied_99",
      });
      if (path === "/jobs/route-optimization/undo") return Promise.resolve({ restored: 3 });
      return Promise.resolve({});
    });

    await act(async () => { fireEvent.press(getByTestId("optimize-route-pill")); });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { fireEvent.press(getByTestId("optimize-route-preview-apply")); });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });

    await act(async () => { fireEvent.press(getByTestId("optimize-route-undo-btn")); });
    await act(async () => { await Promise.resolve(); });

    const undoCall = mockApiPost.mock.calls.find(
      (c) => c[0] === "/jobs/route-optimization/undo",
    );
    expect(undoCall).toBeTruthy();
    expect(undoCall![1]).toEqual({ applied_id: "applied_99" });
    expect(queryByTestId("optimize-route-undo-toast")).toBeNull();
  });

  /* 7 ─────────────────────────────────────────────────────────── */
  it("Undo toast auto-dismisses after 10 s with no /undo call", async () => {
    mockAuthUser.role = "admin";
    mockGetForegroundPerms.mockResolvedValue({ status: "granted" });
    mockGetCurrentPosition.mockResolvedValue({
      coords: { latitude: 33.44, longitude: -112.04 },
    });
    const { getByTestId, queryByTestId } = await mountAndSettle(THREE_PENDING, _POSITIVE_PREVIEW);
    await waitFor(() => expect(getByTestId("optimize-route-pill")).toBeTruthy());

    mockApiPost.mockImplementation((path: string) => {
      if (path === "/jobs/route-optimization/preview") return Promise.resolve(_POSITIVE_PREVIEW);
      if (path === "/jobs/route-optimization/apply") return Promise.resolve({
        applied_id: "applied_late",
      });
      return Promise.resolve({});
    });

    await act(async () => { fireEvent.press(getByTestId("optimize-route-pill")); });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { fireEvent.press(getByTestId("optimize-route-preview-apply")); });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });
    expect(getByTestId("optimize-route-undo-toast")).toBeTruthy();

    // Advance past the 10-second window.
    await act(async () => { jest.advanceTimersByTime(11_000); });

    expect(queryByTestId("optimize-route-undo-toast")).toBeNull();
    // No client-side /undo call was fired.
    const undoCall = mockApiPost.mock.calls.find(
      (c) => c[0] === "/jobs/route-optimization/undo",
    );
    expect(undoCall).toBeUndefined();
  });

  /* 8 ─────────────────────────────────────────────────────────── */
  it("Cancel button closes the modal without an /apply or /request call", async () => {
    mockAuthUser.role = "technician";
    mockGetForegroundPerms.mockResolvedValue({ status: "granted" });
    mockGetCurrentPosition.mockResolvedValue({
      coords: { latitude: 33.44, longitude: -112.04 },
    });
    const { getByTestId, queryByTestId } = await mountAndSettle(THREE_PENDING, _POSITIVE_PREVIEW);
    await waitFor(() => expect(getByTestId("optimize-route-pill")).toBeTruthy());

    mockApiPost.mockClear();
    mockApiPost.mockResolvedValue(_POSITIVE_PREVIEW);
    await act(async () => { fireEvent.press(getByTestId("optimize-route-pill")); });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });
    expect(getByTestId("optimize-route-preview-modal")).toBeTruthy();

    // Cancel — no /request, no /apply.
    mockApiPost.mockClear();
    await act(async () => { fireEvent.press(getByTestId("optimize-route-preview-cancel")); });
    await act(async () => { await Promise.resolve(); });

    const bad = mockApiPost.mock.calls.find((c) =>
      c[0] === "/jobs/route-optimization/apply"
      || c[0] === "/jobs/route-optimization/request",
    );
    expect(bad).toBeUndefined();
    // Pill still visible (tech didn't submit) — pendingSubmitted stays false.
    expect(getByTestId("optimize-route-pill")).toBeTruthy();
    // Suggestion + undo toasts stay hidden.
    expect(queryByTestId("optimize-route-suggestion-toast")).toBeNull();
    expect(queryByTestId("optimize-route-undo-toast")).toBeNull();
  });
});
