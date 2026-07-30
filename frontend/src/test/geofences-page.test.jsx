// Phase G5a · Feb-2026 — Geofences admin page (Vitest).
//
// Mocks @vis.gl/react-google-maps so we can verify the list rendering,
// draw-mode toolbar, and no-maps-fallback form without requiring the
// real Google JS API. When REACT_APP_GOOGLE_MAPS_API_KEY is empty the
// page renders the ManualCreatePanel fallback instead of the map.
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const _list = {
  items: [
    { id: "f1", name: "Depot A", kind: "depot", shape: "circle",
      center_lat: 33.5, center_lon: -112.0, radius_m: 200,
      alert_on_enter: true, alert_on_exit: false, active: true,
      points: [] },
    { id: "f2", name: "Yard poly", kind: "custom", shape: "polygon",
      alert_on_enter: true, alert_on_exit: true, active: true,
      points: [
        { lat: 33.5, lon: -112.0 },
        { lat: 33.5, lon: -111.9 },
        { lat: 33.6, lon: -111.9 },
      ] },
  ],
  total: 2,
};

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path === "/geofences") return _list;
      if (path.startsWith("/geofences/")) {
        return { ..._list.items[0], recent_events: [] };
      }
      return {};
    }),
    post: vi.fn(async () => ({ id: "f3", name: "New", shape: "circle" })),
    patch: vi.fn(), del: vi.fn(async () => ({ archived: true })),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(),
           warning: vi.fn() },
}));

vi.mock("@vis.gl/react-google-maps", () => ({
  Map: ({ children }) => <div data-testid="mock-map">{children}</div>,
  useMap: () => null,
  APIProvider: ({ children }) => <>{children}</>,
  AdvancedMarker: ({ children }) => <>{children}</>,
  InfoWindow: ({ children }) => <>{children}</>,
}));

import GeofencesPage from "@/pages/admin/GeofencesPage";
import { api } from "@/api";

describe("GeofencesPage · G5a", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Force the "no maps key" fallback path so the test doesn't
    // depend on real Google JS being available.
    delete process.env.REACT_APP_GOOGLE_MAPS_API_KEY;
    delete process.env.REACT_APP_GOOGLE_API_KEY;
  });

  it("renders the fence list", async () => {
    render(<MemoryRouter><GeofencesPage /></MemoryRouter>);
    expect(await screen.findByTestId("geofences-title"))
      .toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("geofences-row-f1")).toBeInTheDocument();
      expect(screen.getByTestId("geofences-row-f2")).toBeInTheDocument();
    });
  });

  it("shows the ManualCreatePanel fallback when maps key is missing", async () => {
    render(<MemoryRouter><GeofencesPage /></MemoryRouter>);
    expect(await screen.findByTestId("geofences-manual-panel"))
      .toBeInTheDocument();
  });

  it("manual quick-create POSTs a circle fence and reloads", async () => {
    render(<MemoryRouter><GeofencesPage /></MemoryRouter>);
    await screen.findByTestId("geofences-manual-panel");
    fireEvent.change(screen.getByTestId("geofences-manual-name"),
      { target: { value: "Test Yard" } });
    fireEvent.change(screen.getByTestId("geofences-manual-lat"),
      { target: { value: "33.5" } });
    fireEvent.change(screen.getByTestId("geofences-manual-lon"),
      { target: { value: "-112.0" } });
    fireEvent.change(screen.getByTestId("geofences-manual-radius"),
      { target: { value: "150" } });
    fireEvent.click(screen.getByTestId("geofences-manual-save"));
    await waitFor(() => {
      const posts = api.post.mock.calls.filter((c) => c[0] === "/geofences");
      expect(posts.length).toBe(1);
      expect(posts[0][1].shape).toBe("circle");
      expect(posts[0][1].radius_m).toBe(150);
      expect(posts[0][1].center_lat).toBe(33.5);
    });
  });

  it("detail drawer opens and archive triggers DELETE", async () => {
    render(<MemoryRouter><GeofencesPage /></MemoryRouter>);
    fireEvent.click(await screen.findByTestId("geofences-open-f1"));
    await screen.findByTestId("geofences-detail-drawer");
    fireEvent.click(await screen.findByTestId("geofences-detail-archive"));
    await waitFor(() => {
      const dels = api.del.mock.calls.filter((c) => c[0] === "/geofences/f1");
      expect(dels.length).toBe(1);
    });
  });

  it("shows draw toolbar when maps key is present (isolated test)", async () => {
    process.env.REACT_APP_GOOGLE_MAPS_API_KEY = "test-key";
    render(<MemoryRouter><GeofencesPage /></MemoryRouter>);
    expect(await screen.findByTestId("geofences-draw-toolbar"))
      .toBeInTheDocument();
    expect(screen.getByTestId("geofences-draw-circle-btn")).toBeInTheDocument();
    expect(screen.getByTestId("geofences-draw-polygon-btn")).toBeInTheDocument();
    // Clicking should not throw even without a real map.
    fireEvent.click(screen.getByTestId("geofences-draw-circle-btn"));
    expect(screen.getByTestId("geofences-draw-cancel-btn")).toBeInTheDocument();
  });
});
