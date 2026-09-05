/**
 * DailyRouteMap web-variant isolation test.
 *
 * Proves that the ``.web.tsx`` fallback does NOT reach for the
 * native map module. Phase K46 · Feb-2026 — flipped the bomb from
 * ``@rnmapbox/maps`` (removed) to ``react-native-maps`` (kept for
 * native but must never load on web).
 */

/* ── Bomb mock: any attempt to require react-native-maps will throw ── */
jest.mock("react-native-maps", () => {
  throw new Error("react-native-maps must NOT be imported on web");
});

/* ── Regression guard: @rnmapbox/maps stays out of the resolver ── */
// Attempting to mock a module that doesn't exist would throw at
// jest.mock time and mask the actual test — so instead we assert
// via source inspection inside the suite below.

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
import { readFileSync } from "fs";
import { resolve } from "path";

// Import the .web variant DIRECTLY — this proves it never reaches for the native map.
import DailyRouteMapWeb, {
  resolveJobCoords,
  statusKind,
} from "@/src/components/schedule/DailyRouteMap.web";

describe("DailyRouteMap.web — web fallback isolation", () => {
  it("imports without triggering react-native-maps", () => {
    // If we got here, the bomb mock was never hit — the web variant
    // successfully loaded without any native-maps dependency.
    expect(DailyRouteMapWeb).toBeDefined();
    expect(typeof DailyRouteMapWeb).toBe("function");
  });

  it("Phase K46 · web variant source does NOT reference @rnmapbox/maps", () => {
    const src = readFileSync(
      resolve(__dirname, "../src/components/schedule/DailyRouteMap.web.tsx"),
      "utf8",
    );
    expect(src).not.toMatch(/from\s+["']@rnmapbox\/maps["']/);
    expect(src).not.toMatch(/require\(["']@rnmapbox\/maps["']\)/);
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
