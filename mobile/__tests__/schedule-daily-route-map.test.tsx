/**
 * Feb-2026 · Daily Route Map — Jest suite.
 *
 * Covers 9 behavioural assertions of DailyRouteMap.tsx:
 *   1. Returns null (hides entire component) when 0 jobs.
 *   2. Renders the fallback banner when EXPO_PUBLIC_MAPBOX_TOKEN is missing.
 *   3. Renders one numbered pin per job that resolves coords; jobs
 *      without coords stay off the map (still would show in list).
 *   4. Pin numbers use job.route_index when present.
 *   5. Pin numbers fall back to 1-based list position when route_index is absent.
 *   6. Pin fill color reflects status kind — completed → gray, could_not_service
 *      → amber, everything else → brand blue. Completed shows a check badge;
 *      CNS shows a warning badge.
 *   7. Chevron toggle collapses & re-expands the map; the AsyncStorage key
 *      is scoped by user_id and only writes on a user-driven toggle.
 *   8. Tapping a pin opens the callout (customer name + address + time
 *      window + Open button); tapping "Open" routes to /job/{id}/checklist.
 *   9. Coord resolver prefers job.property.location.{lat,lng}, then flat
 *      location_lat/lng, then legacy job.location and service_address
 *      shapes; unresolved jobs are excluded from the pin set.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

/* ── Mocks ─────────────────────────────────────────────────────────── */

// AsyncStorage — use the official jest mock so `.getItem`/`.setItem`
// resolve cleanly without hitting the null native module.
jest.mock("@react-native-async-storage/async-storage", () =>
  require("@react-native-async-storage/async-storage/jest/async-storage-mock"),
);

const mockRouterPush = jest.fn();
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockRouterPush }),
}));

// @rnmapbox/maps — no native module in Jest. Render the children so
// PointAnnotation children (our RoutePinView) mount and their inner
// testIDs are queryable via getByTestId. Camera + MapView both act
// as passthrough Views.
jest.mock("@rnmapbox/maps", () => {
  const RN = require("react-native");
  const R = require("react");
  const Passthrough = R.forwardRef((props: any, ref: any) =>
    R.createElement(RN.View, { ref, testID: props.testID }, props.children),
  );
  const CameraMock = R.forwardRef((_props: any, ref: any) => {
    R.useImperativeHandle(
      ref,
      () => ({ fitBounds: jest.fn(), setCamera: jest.fn() }),
      [],
    );
    return null;
  });
  const PointAnnotationMock = (props: any) =>
    R.createElement(
      RN.Pressable,
      { testID: props.id, onPress: props.onSelected },
      props.children,
    );
  return {
    __esModule: true,
    default: {
      MapView: Passthrough,
      Camera: CameraMock,
      PointAnnotation: PointAnnotationMock,
    },
  };
});

/* ── Suite helpers ─────────────────────────────────────────────────── */

const AsyncStorageMock = require("@react-native-async-storage/async-storage");
const ORIG_TOKEN = process.env.EXPO_PUBLIC_MAPBOX_TOKEN;

beforeEach(() => {
  AsyncStorageMock.clear && AsyncStorageMock.clear();
  mockRouterPush.mockClear();
  process.env.EXPO_PUBLIC_MAPBOX_TOKEN = "pk.test.token";
});

afterAll(() => {
  process.env.EXPO_PUBLIC_MAPBOX_TOKEN = ORIG_TOKEN;
});

// Import AFTER mocks so the module under test picks them up.
import DailyRouteMap, {
  resolveJobCoords,
  statusKind,
} from "@/src/components/schedule/DailyRouteMap";

/* ── Fixtures ──────────────────────────────────────────────────────── */

const JOB_A = {
  id: "j1",
  status: "scheduled",
  route_index: 1,
  customer_name: "Alice Waters",
  address: "123 Palm Ln, Phoenix, AZ",
  scheduled_time: "09:00",
  scheduled_time_end: "09:45",
  property: { location: { lat: 33.45, lng: -112.07 } },
};
const JOB_B = {
  id: "j2",
  status: "completed",
  route_index: 2,
  customer_name: "Bob Reed",
  address: "456 Oak St, Phoenix, AZ",
  scheduled_time: "10:15",
  location_lat: 33.46,
  location_lng: -112.08,
};
const JOB_C = {
  id: "j3",
  status: "could_not_service",
  route_index: 3,
  customer_name: "Carol Yin",
  address: "789 Elm Dr, Phoenix, AZ",
  scheduled_time: "11:00",
  location: { lat: 33.47, lng: -112.09 },
};
const JOB_D_NOGEO = {
  id: "j4",
  status: "scheduled",
  customer_name: "Dave Missing",
  address: "No coords here",
  scheduled_time: "12:00",
};
const JOB_E_LEGACY_SVC_ADDR = {
  id: "j5",
  status: "scheduled",
  customer_name: "Eve Legacy",
  address: "Legacy shape",
  scheduled_time: "13:00",
  service_address: { coordinates: { lat: 33.48, lng: -112.10 } },
};

/* ═══════════════════════════════════════════════════════════════════ */
describe("DailyRouteMap — Feb-2026 daily route map for tech schedule", () => {
  /* 1 ─────────────────────────────────────────────────────────────── */
  it("hides the entire component when 0 jobs are scheduled", () => {
    const { queryByTestId } = render(
      <DailyRouteMap jobs={[]} userId="tech-1" />,
    );
    expect(queryByTestId("schedule-daily-route-map")).toBeNull();
    expect(queryByTestId("schedule-daily-route-map-canvas")).toBeNull();
  });

  /* 2 ─────────────────────────────────────────────────────────────── */
  it("renders the fallback banner when the Mapbox token is missing", () => {
    delete process.env.EXPO_PUBLIC_MAPBOX_TOKEN;
    const { getByTestId, getByText, queryByTestId } = render(
      <DailyRouteMap jobs={[JOB_A]} userId="tech-1" />,
    );
    expect(getByTestId("schedule-daily-route-map-token-banner")).toBeTruthy();
    expect(getByText("Map unavailable — Mapbox token not configured")).toBeTruthy();
    // Map canvas should NOT render when the token is missing.
    expect(queryByTestId("schedule-daily-route-map-canvas")).toBeNull();
  });

  /* 3 ─────────────────────────────────────────────────────────────── */
  it("renders one numbered pin per coord-bearing job (skips no-geo jobs)", () => {
    const { queryAllByTestId, queryByTestId } = render(
      <DailyRouteMap
        jobs={[JOB_A, JOB_B, JOB_C, JOB_D_NOGEO]}
        userId="tech-1"
      />,
    );
    // 3 of 4 jobs have coords; JOB_D_NOGEO is silently dropped.
    // Count the OUTER PointAnnotation pressables (one per rendered pin).
    const pins = queryAllByTestId(/^schedule-daily-route-map-pin-j[123]$/);
    expect(pins.length).toBe(3);
    expect(queryByTestId("schedule-daily-route-map-pin-j4")).toBeNull();
  });

  /* 4 ─────────────────────────────────────────────────────────────── */
  it("labels pins with job.route_index when present", () => {
    const { getByTestId } = render(
      <DailyRouteMap jobs={[JOB_A, JOB_B, JOB_C]} userId="tech-1" />,
    );
    // getByTestId returns the RN.Text component; .props.children is the number.
    expect(getByTestId("schedule-daily-route-map-pin-num-j1").props.children).toBe(1);
    expect(getByTestId("schedule-daily-route-map-pin-num-j2").props.children).toBe(2);
    expect(getByTestId("schedule-daily-route-map-pin-num-j3").props.children).toBe(3);
  });

  /* 5 ─────────────────────────────────────────────────────────────── */
  it("falls back to 1-based list position when route_index is absent", () => {
    const jobs = [
      { ...JOB_A, route_index: undefined, route_order: undefined },
      { ...JOB_B, route_index: undefined, route_order: undefined },
      { ...JOB_C, route_index: undefined, route_order: undefined },
    ];
    const { getByTestId } = render(<DailyRouteMap jobs={jobs} userId="tech-1" />);
    expect(getByTestId("schedule-daily-route-map-pin-num-j1").props.children).toBe(1);
    expect(getByTestId("schedule-daily-route-map-pin-num-j2").props.children).toBe(2);
    expect(getByTestId("schedule-daily-route-map-pin-num-j3").props.children).toBe(3);
  });

  /* 6 ─────────────────────────────────────────────────────────────── */
  it("color-codes pins by status and stamps a badge for completed / CNS", () => {
    const { getByTestId, queryByTestId } = render(
      <DailyRouteMap jobs={[JOB_A, JOB_B, JOB_C]} userId="tech-1" />,
    );
    // Pin backgrounds via inline style — flatten & assert.
    const flatBg = (el: any) => {
      const arr = Array.isArray(el.props.style) ? el.props.style : [el.props.style];
      const merged: any = Object.assign({}, ...arr.filter(Boolean));
      return merged.backgroundColor;
    };
    expect(flatBg(getByTestId("schedule-daily-route-map-pin-view-j1"))).toBe("#2563EB"); // pending
    expect(flatBg(getByTestId("schedule-daily-route-map-pin-view-j2"))).toBe("#6B7280"); // completed
    expect(flatBg(getByTestId("schedule-daily-route-map-pin-view-j3"))).toBe("#F59E0B"); // CNS
    // Completed = check badge, CNS = warning badge, pending = neither.
    expect(getByTestId("schedule-daily-route-map-pin-badge-completed-j2")).toBeTruthy();
    expect(getByTestId("schedule-daily-route-map-pin-badge-cns-j3")).toBeTruthy();
    expect(queryByTestId("schedule-daily-route-map-pin-badge-completed-j1")).toBeNull();
    expect(queryByTestId("schedule-daily-route-map-pin-badge-cns-j1")).toBeNull();
  });

  /* 7 ─────────────────────────────────────────────────────────────── */
  it("chevron toggle collapses/expands and AsyncStorage is scoped by user_id", async () => {
    const { getByTestId, queryByTestId } = render(
      <DailyRouteMap jobs={[JOB_A, JOB_B]} userId="tech-42" />,
    );
    // Expanded by default → canvas visible, no storage write yet.
    expect(getByTestId("schedule-daily-route-map-canvas")).toBeTruthy();
    expect(await AsyncStorageMock.getItem("schedule_daily_map_expanded_v1:tech-42"))
      .toBeNull();

    // Collapse.
    await act(async () => {
      fireEvent.press(getByTestId("schedule-daily-route-map-toggle"));
    });
    await waitFor(() =>
      expect(queryByTestId("schedule-daily-route-map-canvas")).toBeNull(),
    );
    await waitFor(async () =>
      expect(
        await AsyncStorageMock.getItem("schedule_daily_map_expanded_v1:tech-42"),
      ).toBe("0"),
    );
    // Storage scoping — a different user_id must NOT share state.
    expect(
      await AsyncStorageMock.getItem("schedule_daily_map_expanded_v1:tech-999"),
    ).toBeNull();

    // Re-expand → canvas comes back, storage now "1".
    await act(async () => {
      fireEvent.press(getByTestId("schedule-daily-route-map-toggle"));
    });
    await waitFor(() =>
      expect(queryByTestId("schedule-daily-route-map-canvas")).toBeTruthy(),
    );
    await waitFor(async () =>
      expect(
        await AsyncStorageMock.getItem("schedule_daily_map_expanded_v1:tech-42"),
      ).toBe("1"),
    );
  });

  /* 8 ─────────────────────────────────────────────────────────────── */
  it("pin tap opens callout and Open button routes to /job/{id}/checklist", async () => {
    const { getByTestId, queryByTestId } = render(
      <DailyRouteMap jobs={[JOB_A, JOB_B]} userId="tech-1" />,
    );
    // No callout initially.
    expect(queryByTestId("schedule-daily-route-map-callout")).toBeNull();

    // Tap the PointAnnotation pressable (mock forwards onSelected → onPress).
    await act(async () => {
      fireEvent.press(getByTestId("schedule-daily-route-map-pin-j1"));
    });

    // Callout renders with the job's customer + address + time window.
    const callout = getByTestId("schedule-daily-route-map-callout");
    expect(callout).toBeTruthy();
    expect(getByTestId("schedule-daily-route-map-callout-name").props.children)
      .toBe("Alice Waters");
    expect(getByTestId("schedule-daily-route-map-callout-address").props.children)
      .toBe("123 Palm Ln, Phoenix, AZ");
    expect(getByTestId("schedule-daily-route-map-callout-time").props.children)
      .toBe("09:00 – 09:45");

    // Open button → router.push to job detail.
    await act(async () => {
      fireEvent.press(getByTestId("schedule-daily-route-map-callout-open"));
    });
    expect(mockRouterPush).toHaveBeenCalledWith("/job/j1/checklist");
    // Callout closes after Open.
    expect(queryByTestId("schedule-daily-route-map-callout")).toBeNull();
  });

  /* 9 ─────────────────────────────────────────────────────────────── */
  it("resolveJobCoords prefers property.location and falls back through legacy shapes", () => {
    // Canonical shape wins.
    expect(resolveJobCoords(JOB_A as any)).toEqual({ lat: 33.45, lng: -112.07 });
    // Flat legacy shape.
    expect(resolveJobCoords(JOB_B as any)).toEqual({ lat: 33.46, lng: -112.08 });
    // job.location legacy shape.
    expect(resolveJobCoords(JOB_C as any)).toEqual({ lat: 33.47, lng: -112.09 });
    // service_address.coordinates legacy shape.
    expect(resolveJobCoords(JOB_E_LEGACY_SVC_ADDR as any)).toEqual({
      lat: 33.48, lng: -112.10,
    });
    // No coords → null (excluded from pin set).
    expect(resolveJobCoords(JOB_D_NOGEO as any)).toBeNull();
    expect(resolveJobCoords({ id: "z", location_lat: 0, location_lng: 0 } as any)).toBeNull();

    // Status classifier — quick sanity round.
    expect(statusKind("completed")).toBe("completed");
    expect(statusKind("could_not_service")).toBe("cns");
    expect(statusKind("skipped")).toBe("cns");
    expect(statusKind("scheduled")).toBe("pending");
    expect(statusKind(undefined)).toBe("pending");
  });
});
