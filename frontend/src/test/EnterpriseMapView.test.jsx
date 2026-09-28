/**
 * EMV · Feb-2026 — EnterpriseMapView vitest.
 *
 * Locks:
 *   1. Fetches /dispatch/enterprise-view on mount with default date range.
 *   2. Renders technicians in the sidebar with color swatch + counts.
 *   3. Shows the "hash_fallback" chip on techs with color_source="hash_fallback".
 *   4. Missing-coords banner renders only when missing_coordinates_count > 0.
 *   5. Truncated banner renders when truncated=true.
 *   6. 400 span-error surfaces via inline error state + toast.
 *   7. RBAC 403 renders inline error card + toast.
 *   8. Sidebar checkbox toggles tech visibility (bulk All / None).
 */
import React from "react";
import {
  render, screen, waitFor, fireEvent,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { toast } from "sonner";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(), success: vi.fn(),
    info: vi.fn(), warning: vi.fn(),
  },
}));

// Mock the maps adapter so vitest doesn't try to boot Google Maps.
vi.mock("@/lib/maps", () => {
  const React2 = require("react");
  const stub = (name) => ({ children }) =>
    React2.createElement("div", { "data-mock": name }, children);
  return {
    Map: stub("Map"),
    AdvancedMarker: stub("AdvancedMarker"),
    InfoWindow: stub("InfoWindow"),
    Polyline: stub("Polyline"),
    Marker: stub("Marker"),
    Pin: stub("Pin"),
    MapView: stub("MapView"),
    useMap: () => null,
    useMapsLibrary: () => null,
    MapsProviderGate: ({ children }) =>
      React2.createElement("div", null, children),
  };
});

// Mock the marker clusterer so it never touches the DOM.
vi.mock("@googlemaps/markerclusterer", () => ({
  MarkerClusterer: class {
    constructor() { /* no-op */ }
    clearMarkers() { /* no-op */ }
  },
}));

const { _apiMock } = vi.hoisted(() => ({
  _apiMock: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}));
vi.mock("@/api", () => ({ api: _apiMock }));

import EnterpriseMapView from "@/pages/dispatch/EnterpriseMapView";

const SAMPLE = {
  start_date: "2026-05-04",
  end_date: "2026-05-10",
  days_in_range: 7,
  technicians: [
    {
      id: "tech-a", name: "Alice Angler",
      display_color_hex: "#3B82F6",
      color_source: "db",
      job_count: 3,
    },
    {
      id: "tech-b", name: "Bruno Bouyant",
      display_color_hex: "#F97316",
      color_source: "hash_fallback",
      job_count: 1,
    },
  ],
  jobs: [
    {
      id: "j1", customer_id: "c1", customer_name: "Cust 1",
      technician_id: "tech-a", scheduled_date: "2026-05-04",
      route_index: 0, lat: 33.7, lng: -112.2,
      address: "1 A St", service_type: "pool", title: "Pool clean",
      status: "scheduled", has_coordinates: true,
    },
    {
      id: "j2", customer_id: "c2", customer_name: "Cust 2",
      technician_id: "tech-b", scheduled_date: "2026-05-05",
      route_index: 1, lat: 33.72, lng: -112.21,
      address: "2 B St", service_type: "landscape", title: "Yard trim",
      status: "scheduled", has_coordinates: true,
    },
  ],
  missing_coordinates_count: 0,
  truncated: false,
  total_jobs_matched: 2,
  cap: 2000,
};


describe("EMV · EnterpriseMapView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _apiMock.get.mockResolvedValue(SAMPLE);
  });

  it("fetches /dispatch/enterprise-view on mount", async () => {
    render(<EnterpriseMapView />);
    await waitFor(() => {
      expect(_apiMock.get).toHaveBeenCalledWith(
        "/dispatch/enterprise-view",
        expect.objectContaining({
          start_date: expect.any(String),
          end_date: expect.any(String),
        }),
      );
    });
  });

  it("renders the page title + subtitle", async () => {
    render(<EnterpriseMapView />);
    await waitFor(() => {
      expect(screen.getByTestId("emv-title")).toBeInTheDocument();
    });
    expect(screen.getByTestId("emv-subtitle")).toBeInTheDocument();
  });

  it("renders tech rows with counts and color swatch", async () => {
    render(<EnterpriseMapView />);
    await waitFor(() => {
      expect(screen.getByTestId("emv-sidebar-tech-row-tech-a")).toBeInTheDocument();
    });
    expect(screen.getByTestId("emv-sidebar-tech-row-tech-b")).toBeInTheDocument();
    expect(
      screen.getByTestId("emv-sidebar-tech-count-tech-a").textContent,
    ).toMatch(/3 jobs/);
    expect(
      screen.getByTestId("emv-sidebar-tech-count-tech-b").textContent,
    ).toMatch(/1 job/);
  });

  it("shows the fallback chip on hash_fallback techs only", async () => {
    render(<EnterpriseMapView />);
    await waitFor(() => {
      expect(
        screen.getByTestId("emv-sidebar-tech-fallback-tech-b"),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByTestId("emv-sidebar-tech-fallback-tech-a"),
    ).not.toBeInTheDocument();
  });

  it("renders missing-coords banner when count > 0", async () => {
    _apiMock.get.mockResolvedValueOnce({
      ...SAMPLE,
      missing_coordinates_count: 4,
      jobs: [
        ...SAMPLE.jobs,
        {
          id: "j3", customer_id: "c3", customer_name: "Cust 3",
          technician_id: "tech-a", scheduled_date: "2026-05-06",
          route_index: null, lat: null, lng: null,
          address: "", service_type: "", title: "No coords",
          status: "scheduled", has_coordinates: false,
        },
      ],
    });
    render(<EnterpriseMapView />);
    await waitFor(() => {
      expect(
        screen.getByTestId("emv-missing-coords-banner"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("emv-missing-coords-banner").textContent,
    ).toMatch(/4 jobs are missing/);
  });

  it("does NOT render missing-coords banner when count = 0", async () => {
    render(<EnterpriseMapView />);
    await waitFor(() => {
      expect(screen.getByTestId("emv-title")).toBeInTheDocument();
    });
    expect(
      screen.queryByTestId("emv-missing-coords-banner"),
    ).not.toBeInTheDocument();
  });

  it("renders truncated banner when truncated=true", async () => {
    _apiMock.get.mockResolvedValueOnce({
      ...SAMPLE, truncated: true, total_jobs_matched: 2500,
    });
    render(<EnterpriseMapView />);
    await waitFor(() => {
      expect(screen.getByTestId("emv-truncated-banner")).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("emv-truncated-banner").textContent,
    ).toMatch(/truncated to 2000/);
  });

  it("400 span-error surfaces via inline error state + toast", async () => {
    _apiMock.get.mockRejectedValueOnce({
      status: 400,
      data: { detail: "date range spans 20 days; max 14 allowed." },
    });
    render(<EnterpriseMapView />);
    await waitFor(() => {
      expect(screen.getByTestId("emv-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("emv-error").textContent).toMatch(/max 14/);
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringMatching(/max 14/i),
    );
  });

  it("403 RBAC error surfaces via inline error state", async () => {
    _apiMock.get.mockRejectedValueOnce({
      status: 403,
      data: { detail: "admin, manager, or super_admin only" },
    });
    render(<EnterpriseMapView />);
    await waitFor(() => {
      expect(screen.getByTestId("emv-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("emv-error").textContent).toMatch(/403/);
  });

  it("bulk None button hides all techs and can re-show via All", async () => {
    render(<EnterpriseMapView />);
    await waitFor(() => {
      expect(screen.getByTestId("emv-sidebar-tech-toggle-tech-a")).toBeInTheDocument();
    });
    const toggleA = screen.getByTestId("emv-sidebar-tech-toggle-tech-a");
    const toggleB = screen.getByTestId("emv-sidebar-tech-toggle-tech-b");
    expect(toggleA.checked).toBe(true);
    expect(toggleB.checked).toBe(true);
    fireEvent.click(screen.getByTestId("emv-sidebar-hide-all"));
    expect(toggleA.checked).toBe(false);
    expect(toggleB.checked).toBe(false);
    fireEvent.click(screen.getByTestId("emv-sidebar-show-all"));
    expect(toggleA.checked).toBe(true);
    expect(toggleB.checked).toBe(true);
  });

  it("refresh button re-invokes fetch", async () => {
    render(<EnterpriseMapView />);
    await waitFor(() => {
      expect(_apiMock.get).toHaveBeenCalledTimes(1);
    });
    fireEvent.click(screen.getByTestId("emv-refresh-button"));
    await waitFor(() => {
      expect(_apiMock.get).toHaveBeenCalledTimes(2);
    });
  });
});
