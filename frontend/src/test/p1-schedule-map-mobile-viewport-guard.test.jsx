/**
 * Feb-2026 · P1 Schedule map mobile-viewport guard.
 *
 * The user's original P1 report ("Route map with N stops available on
 * the mobile app.") is a **misdiagnosis on the CRM side** — that
 * placeholder lives in `mobile/src/components/schedule/DailyRouteMap
 * .web.tsx:91` (the Expo Web fallback), NOT in this React CRM. The CRM
 * `<ScheduleMap>` has no viewport gate.
 *
 * This test is a **regression guard**: if a future PR ever adds a
 * mobile-viewport short-circuit rendering a placeholder in
 * `pages/schedule/ScheduleMap.jsx`, it fails.
 *
 * Assertions at 390×844 mobile viewport:
 *   1. `[data-testid="schedule-map-container"]` renders when jobs
 *      resolve to coords.
 *   2. Pins render (`[data-testid^="schedule-map-pin-"]`).
 *   3. The Expo-Web-only phrase "available on the mobile app" is
 *      NEVER present in the DOM.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

// Mock the maps adapter — the CRM `<Map>`, `<AdvancedMarker>`, and
// `<InfoWindow>` primitives come from `@/lib/maps` (google adapter).
// The real adapter needs an API key at runtime, so stub it to a
// deterministic shell that ScheduleMap can render children into.
vi.mock("../lib/maps", () => ({
  Map: ({ children, ...rest }) => (
    <div data-testid="mock-map" data-props={JSON.stringify(rest)}>{children}</div>
  ),
  AdvancedMarker: ({ children, position }) => (
    <div data-testid="mock-marker" data-lat={position?.lat} data-lng={position?.lng}>
      {children}
    </div>
  ),
  InfoWindow: ({ children }) => (
    <div data-testid="mock-infowindow">{children}</div>
  ),
}));

import ScheduleMap from "../pages/schedule/ScheduleMap";

const JOBS = [
  { id: "job-1", customer_name: "Alpha", location_lat: 33.51, location_lng: -112.01,
    technician_id: "u-1", scheduled_time: "09:00", address: "1 Main St" },
  { id: "job-2", customer_name: "Beta",  location_lat: 33.53, location_lng: -112.03,
    technician_id: "u-2", scheduled_time: "10:00", address: "2 Side Rd" },
  { id: "job-3", customer_name: "Gamma", location_lat: 33.55, location_lng: -112.05,
    technician_id: "u-1", scheduled_time: "11:00", address: "3 Elm Ct" },
  { id: "job-4", customer_name: "Delta", location_lat: 33.57, location_lng: -112.07,
    technician_id: "u-2", scheduled_time: "12:00", address: "4 Oak Ln" },
];
const TECHS = [
  { id: "u-1", name: "Alice" },
  { id: "u-2", name: "Bob" },
];
const COLOR_MAP = new Map([["u-1", "#ff0000"], ["u-2", "#00ff00"]]);

describe("Schedule map — mobile viewport guard", () => {
  beforeEach(() => {
    // Simulate the 390×844 mobile viewport in jsdom.
    Object.defineProperty(window, "innerWidth", {
      configurable: true, writable: true, value: 390,
    });
    Object.defineProperty(window, "innerHeight", {
      configurable: true, writable: true, value: 844,
    });
    // matchMedia stub — used by any downstream `useMediaQuery`.
    window.matchMedia = window.matchMedia || ((q) => ({
      matches: q.includes("max-width"),
      media: q,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
  });

  afterEach(() => cleanup());

  it("renders the real map container on 390px viewport (no placeholder)", () => {
    render(
      <ScheduleMap jobs={JOBS} techs={TECHS} techColorMap={COLOR_MAP} />,
    );
    const container = screen.getByTestId("schedule-map-container");
    expect(container).toBeInTheDocument();
    expect(screen.getByTestId("mock-map")).toBeInTheDocument();
  });

  it("renders one pin per job with valid coords", () => {
    render(
      <ScheduleMap jobs={JOBS} techs={TECHS} techColorMap={COLOR_MAP} />,
    );
    for (const j of JOBS) {
      expect(screen.getByTestId(`schedule-map-pin-${j.id}`)).toBeInTheDocument();
    }
  });

  it("never contains the Expo-Web placeholder phrase", () => {
    const { container } = render(
      <ScheduleMap jobs={JOBS} techs={TECHS} techColorMap={COLOR_MAP} />,
    );
    expect(container.textContent || "").not.toMatch(/available on the mobile app/i);
    expect(container.textContent || "").not.toMatch(/Route map with .* stops available/i);
  });

  it("returns null (not a placeholder) when zero jobs have coords", () => {
    const jobsNoCoords = [
      { id: "no-coord-1", customer_name: "NoCoord",
        location_lat: null, location_lng: null },
    ];
    const { container } = render(
      <ScheduleMap jobs={jobsNoCoords} techs={TECHS} techColorMap={COLOR_MAP} />,
    );
    // Empty-state contract: return null. No placeholder text either.
    expect(container.querySelector('[data-testid="schedule-map-container"]')).toBeNull();
    expect(container.textContent || "").not.toMatch(/available on the mobile app/i);
  });
});
