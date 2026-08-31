/**
 * __tests__/mobile-navigate-route.test.tsx
 * Tests: URL building, disabled state, waypoint order.
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";
import { Linking, Alert, Platform } from "react-native";

jest.mock("@/src/theme", () => ({
  colors: {
    surface: "#fff", onSurface: "#000", surfaceSecondary: "#f4f4f5",
    surfaceTertiary: "#e4e4e7", border: "#e4e4e7", muted: "#717",
    brand: "#0284C7", error: "#DC2626",
  },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 },
  radius: { sm: 8, md: 12, lg: 16, pill: 999 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { sm: 12, base: 14, lg: 16, xl: 20 },
}));

import NavigateRouteButton, {
  buildRouteUrl,
} from "@/src/components/schedule/NavigateRouteButton";

describe("NavigateRouteButton", () => {
  beforeEach(() => jest.clearAllMocks());

  it("builds correct URL with multiple stops", () => {
    const jobs = [
      { id: "j1", address: "123 Main St", route_index: 1, status: "scheduled" },
      { id: "j2", address: "456 Oak Ave", route_index: 2, status: "scheduled" },
      { id: "j3", address: "789 Pine Rd", route_index: 3, status: "scheduled" },
    ];
    const url = buildRouteUrl(jobs);
    expect(url).toContain("destination=789+Pine+Rd");
    expect(url).toContain("waypoints=123+Main+St%7C456+Oak+Ave");
    expect(url).toContain("travelmode=driving");
    expect(url).toContain("api=1");
    console.log("✅ NAV-T1: multi-stop URL built correctly");
  });

  it("skips terminal (completed/cancelled) jobs", () => {
    const jobs = [
      { id: "j1", address: "123 Main St", route_index: 1, status: "completed" },
      { id: "j2", address: "456 Oak Ave", route_index: 2, status: "scheduled" },
      { id: "j3", address: "789 Pine Rd", route_index: 3, status: "cancelled" },
    ];
    const url = buildRouteUrl(jobs);
    expect(url).toContain("destination=456+Oak+Ave");
    expect(url).not.toContain("123+Main+St");
    expect(url).not.toContain("789+Pine+Rd");
    console.log("✅ NAV-T2: terminal jobs skipped");
  });

  it("returns null when no addressable jobs", () => {
    expect(buildRouteUrl([])).toBeNull();
    expect(buildRouteUrl([{ id: "j1", status: "completed", address: "x" }])).toBeNull();
    console.log("✅ NAV-T3: null when no addressable jobs");
  });

  it("single stop → destination only, no waypoints param", () => {
    const url = buildRouteUrl([
      { id: "j1", address: "123 Main St", route_index: 1, status: "active" },
    ]);
    expect(url).toContain("destination=123+Main+St");
    expect(url).not.toContain("waypoints");
    console.log("✅ NAV-T4: single stop, no waypoints");
  });

  it("prefers lat/lng over address", () => {
    const url = buildRouteUrl([
      {
        id: "j1",
        address: "123 Main St",
        latitude: 33.45,
        longitude: -112.07,
        route_index: 1,
        status: "scheduled",
      },
    ]);
    expect(url).toContain("33.45%2C-112.07");
    console.log("✅ NAV-T5: lat/lng preferred");
  });

  it("button disabled when 0 jobs", () => {
    const tree = render(<NavigateRouteButton jobs={[]} />);
    const btn = tree.getByTestId("schedule-navigate-route-btn");
    expect(btn.props.accessibilityState?.disabled).toBe(true);
    console.log("✅ NAV-T6: button disabled with 0 jobs");
  });

  it("button opens Linking.openURL on press", async () => {
    jest.spyOn(Linking, "canOpenURL").mockResolvedValue(true);
    jest.spyOn(Linking, "openURL").mockResolvedValue(undefined as any);
    const tree = render(
      <NavigateRouteButton
        jobs={[
          { id: "j1", address: "123 Main", route_index: 1, status: "active" },
        ]}
      />,
    );
    fireEvent.press(tree.getByTestId("schedule-navigate-route-btn"));
    await waitFor(() => {
      expect(Linking.openURL).toHaveBeenCalledWith(
        expect.stringContaining("google.com/maps/dir"),
      );
    });
    console.log("✅ NAV-T7: Linking.openURL called");
  });
});
