/**
 * Phase G3 · Feb-2026 — Driver Activity Route Map panel tests.
 *
 * Verifies:
 *   1. Route map renders 3 legend toggles.
 *   2. Loads /gps/route on mount and shows the SVG.
 *   3. Toggling "Polyline" removes the <polyline>.
 *   4. Toggling "Stops-only" hides the stop pins.
 *   5. Address fallback (coords) shown when stop has no address.
 *   6. "MAPBOX_ACCESS_TOKEN not set" banner rendered when
 *      mapbox_token_configured=false.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const _stops = [
  { id: "s-1", started_at: "2026-02-14T09:00:00Z",
    ended_at:   "2026-02-14T09:15:00Z", duration_s: 900,
    center_lat: 33.51, center_lon: -112.01,
    address: null, address_status: "no_token" },
  { id: "s-2", started_at: "2026-02-14T10:00:00Z",
    ended_at:   "2026-02-14T10:20:00Z", duration_s: 1200,
    center_lat: 33.53, center_lon: -112.03,
    address: null, address_status: "no_token" },
];
const _pings = [
  { lat: 33.51, lon: -112.01, captured_at: "2026-02-14T09:00:00Z" },
  { lat: 33.52, lon: -112.02, captured_at: "2026-02-14T09:30:00Z" },
  { lat: 33.53, lon: -112.03, captured_at: "2026-02-14T10:00:00Z" },
];

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path.startsWith("/users?role=technician"))
        return [{ id: "u-1", name: "Ana Tech", email: "ana@x.com" }];
      if (path.startsWith("/gps/stops"))
        return { user_name: "Ana Tech", stops: _stops };
      if (path.startsWith("/gps/route"))
        return {
          user_id: "u-1", user_name: "Ana Tech",
          from: "…", to: "…",
          stops: _stops, pings: _pings,
          pings_total: 3, pings_downsample_step: 1,
          mapbox_token_configured: false,
        };
      return {};
    }),
    post: vi.fn(async () => ({ status: "no_token", processed: 0,
                                 mapbox_token_configured: false })),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

if (typeof window !== "undefined" && !window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {} unobserve() {} disconnect() {}
  };
}

// SafeScrollContainer is a thin wrapper — pass through in tests.
vi.mock("@/components/layout/SafeScrollContainer", () => ({
  default: ({ children, ...rest }) => (
    <div {...rest}>{children}</div>
  ),
}));

import DriverActivityPage from "@/pages/admin/DriverActivityPage";
import { api } from "@/api";
import { _resetCacheForTest } from "@/hooks/useGpsRoute";

describe("DriverActivityPage · Route Map panel (G3)", () => {
  beforeEach(() => { vi.clearAllMocks(); _resetCacheForTest(); });

  it("renders the route map panel with three legend toggles", async () => {
    render(<MemoryRouter><DriverActivityPage /></MemoryRouter>);
    expect(await screen.findByTestId("driver-activity-route-map"))
      .toBeInTheDocument();
    expect(await screen.findByTestId("route-map-legend"))
      .toBeInTheDocument();
    expect(screen.getByTestId("route-map-toggle-polyline"))
      .toBeInTheDocument();
    expect(screen.getByTestId("route-map-toggle-stops"))
      .toBeInTheDocument();
    expect(screen.getByTestId("route-map-toggle-pings"))
      .toBeInTheDocument();
  });

  it("fires GET /gps/route with tech + day range on load", async () => {
    render(<MemoryRouter><DriverActivityPage /></MemoryRouter>);
    await waitFor(() => {
      const calls = api.get.mock.calls
        .filter((c) => typeof c[0] === "string"
                        && c[0].startsWith("/gps/route"));
      expect(calls.length).toBeGreaterThanOrEqual(1);
      expect(calls[0][0]).toContain("user_id=u-1");
      expect(calls[0][0]).toContain("from=");
      expect(calls[0][0]).toContain("to=");
    });
  });

  it("polyline layer toggles off", async () => {
    render(<MemoryRouter><DriverActivityPage /></MemoryRouter>);
    await screen.findByTestId("route-map-svg");
    // Polyline is on by default (>=2 stops).
    expect(screen.getByTestId("route-map-polyline")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("route-map-toggle-polyline"));
    await waitFor(() =>
      expect(screen.queryByTestId("route-map-polyline")).toBeNull());
  });

  it("stops-only layer toggles off", async () => {
    render(<MemoryRouter><DriverActivityPage /></MemoryRouter>);
    await screen.findByTestId("route-map-svg");
    expect(screen.getByTestId("route-map-stop-s-1")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("route-map-toggle-stops"));
    await waitFor(() =>
      expect(screen.queryByTestId("route-map-stop-s-1")).toBeNull());
  });

  it("shows the 'Address unavailable' fallback for un-geocoded stops",
     async () => {
    render(<MemoryRouter><DriverActivityPage /></MemoryRouter>);
    // Timeline row is rendered by the parent — pick one and check the
    // fallback element.
    await waitFor(() => {
      expect(
        screen.getByTestId("driver-activity-stop-addr-fallback-s-1"))
        .toBeInTheDocument();
    });
  });

  it("shows the MAPBOX_ACCESS_TOKEN warning banner when token unset",
     async () => {
    render(<MemoryRouter><DriverActivityPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("route-map-no-token-banner"))
        .toBeInTheDocument());
  });
});
