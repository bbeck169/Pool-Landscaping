/**
 * DailyRouteMap web-variant isolation test.
 *
 * Proves that the ``.web.tsx`` fallback does NOT import @rnmapbox/maps.
 * Uses the same mock-and-throw pattern as the existing test suite.
 */

/* ── Bomb mock: any attempt to require @rnmapbox/maps will throw ── */
jest.mock("@rnmapbox/maps", () => {
  throw new Error("@rnmapbox/maps must NOT be imported on web");
});

/* ── Standard RN mocks ─────────────────────────────────────────── */
jest.mock("expo-router", () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn().mockResolvedValue(null),
  setItem: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { role: "technician" } }),
  AuthProvider: ({ children }: any) => children,
}));

import React from "react";
import { render } from "@testing-library/react-native";

// Import the .web variant DIRECTLY — this proves it never reaches for Mapbox.
import DailyRouteMapWeb, {
  resolveJobCoords,
  statusKind,
} from "@/src/components/schedule/DailyRouteMap.web";

describe("DailyRouteMap.web — web fallback isolation", () => {
  it("imports without triggering @rnmapbox/maps", () => {
    // If we got here, the bomb mock was never hit — the web variant
    // successfully loaded without any Mapbox dependency.
    expect(DailyRouteMapWeb).toBeDefined();
    expect(typeof DailyRouteMapWeb).toBe("function");
  });

  it("renders a placeholder when jobs have coords", () => {
    const jobs = [
      { id: "j1", status: "scheduled", location_lat: 33.45, location_lng: -112.07 },
    ];
    const { getByTestId } = render(
      <DailyRouteMapWeb jobs={jobs} userId="u1" />,
    );
    expect(getByTestId("schedule-daily-route-map")).toBeTruthy();
  });

  it("returns null when jobs array is empty", () => {
    const { toJSON } = render(
      <DailyRouteMapWeb jobs={[]} userId="u1" />,
    );
    expect(toJSON()).toBeNull();
  });

  it("exports resolveJobCoords and statusKind helpers", () => {
    expect(typeof resolveJobCoords).toBe("function");
    expect(typeof statusKind).toBe("function");
    expect(statusKind("completed")).toBe("completed");
    expect(resolveJobCoords({ id: "x", location_lat: 33, location_lng: -112 })).toEqual({
      lat: 33,
      lng: -112,
    });
  });
});
