/**
 * Phase 17 Additions · Feb-2026 — vitest for color modes, shift
 * dialog, active shifts sidebar, and unrouted panel.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@vis.gl/react-google-maps", () => ({
  Map: ({ children, gestureHandling }) => (
    <div data-testid="dispatch-google-map"
         data-gesture-handling={gestureHandling}>{children}</div>
  ),
  AdvancedMarker: ({ children, position }) => (
    <div data-lat={position?.lat}>{children}</div>
  ),
  InfoWindow: ({ children }) => <div>{children}</div>,
  useMap: () => null,
  APIProvider: ({ children }) => <>{children}</>,
}));
vi.mock("@googlemaps/markerclusterer", () => ({
  MarkerClusterer: class { clearMarkers() {} },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const { apiGetMock, apiPostMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(), apiPostMock: vi.fn(),
}));
vi.mock("@/api", () => ({ api: { get: apiGetMock, post: apiPostMock } }));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin", id: "u-1", name: "Admin" } }),
}));

import DispatchBoardPage from "@/pages/dispatch/DispatchBoardPage";
import {
  colorForPin, loadPinColorMode, savePinColorMode, PIN_COLOR_BY_DAY,
} from "@/pages/dispatch/dispatchColors";

const BOARD = {
  pins: [{
    customer_id: "c-1", name: "Alpha", address: "1 Ave",
    lat: 33.7, lng: -112.3,
    tags: [], category_ids: [], service_days: ["mon"],
    assigned_tech_ids: ["t-mike"], is_scheduled_this_day: true,
    tech_color_hex: "#4F46E5", crew_label: "Pool", crew_color_hex: "#0ea5e9",
    service_day: "mon", override_source_tech_id: null,
  }],
  route_stops: [{
    customer_id: "c-1", name: "Alpha", address: "1 Ave",
    lat: 33.7, lng: -112.3,
    tech_color_hex: "#4F46E5", crew_label: "Pool", crew_color_hex: "#0ea5e9",
    service_day: "mon", override_source_tech_id: null,
  }],
  tech_load: [{ tech_user_id: "t-mike", name: "Mike", count: 1, color_hex: "#4F46E5" }],
  unrouted_customers: [{
    customer_id: "u-1", name: "Uma Unrouted", address: "99 U Ave",
    lat: 33.9, lng: -112.5, tags: [], category_ids: [],
    service_days: [], assigned_tech_ids: [], reason: "no_service_day",
  }],
  global_view: false, day: "mon", tech_user_id: "t-mike",
};

const ACTIVE_SHIFTS = { items: [{
  id: "ov-1", source_tech_user_id: "t-src", target_tech_user_id: "t-tgt",
  source_tech_name: "Src Tech", target_tech_name: "Tgt Tech",
  customer_ids: ["c-1", "c-2"], stop_count: 2,
  end_at: new Date(Date.now() + 3 * 86400_000).toISOString(),
  start_at: new Date().toISOString(), scope: "partial",
}], total: 1 };

beforeEach(() => {
  try { localStorage.clear(); } catch { /* jsdom */ }
  apiGetMock.mockReset(); apiPostMock.mockReset();
  apiGetMock.mockImplementation((path) => {
    if (path.startsWith("/dispatch/board")) return Promise.resolve(BOARD);
    if (path.startsWith("/dispatch/reassign")) return Promise.resolve(ACTIVE_SHIFTS);
    if (path.startsWith("/users")) return Promise.resolve([
      { id: "t-mike", name: "Mike", display_color_hex: "#4F46E5" },
      { id: "t-tgt", name: "Tgt Tech", display_color_hex: "#F97316" },
    ]);
    return Promise.resolve(null);
  });
});

describe("Phase 17 additions", () => {
  it("pin color mode selector renders three modes and persists to localStorage", async () => {
    render(<MemoryRouter><DispatchBoardPage /></MemoryRouter>);
    await screen.findByTestId("dispatch-pin-color-bar");
    expect(screen.getByTestId("dispatch-pin-color-mode-tech")).toBeInTheDocument();
    expect(screen.getByTestId("dispatch-pin-color-mode-crew")).toBeInTheDocument();
    expect(screen.getByTestId("dispatch-pin-color-mode-service_day")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("dispatch-pin-color-mode-service_day"));
    expect(loadPinColorMode()).toBe("service_day");
    expect(screen.getByTestId("dispatch-color-legend-day")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("dispatch-pin-color-mode-crew"));
    expect(screen.getByTestId("dispatch-color-legend-crew")).toBeInTheDocument();
  });

  it("colorForPin returns day color in service_day mode, tech color in tech mode", () => {
    const pin = {
      tech_color_hex: "#AAAAAA", crew_color_hex: "#BBBBBB",
      service_day: "wed", assigned_tech_ids: ["x"],
    };
    expect(colorForPin(pin, "tech", {})).toBe("#AAAAAA");
    expect(colorForPin(pin, "crew", {})).toBe("#BBBBBB");
    expect(colorForPin(pin, "service_day", {})).toBe(PIN_COLOR_BY_DAY.wed);
  });

  it("unrouted panel renders count + reason + Suggest button", async () => {
    render(<MemoryRouter><DispatchBoardPage /></MemoryRouter>);
    await screen.findByTestId("dispatch-unrouted-panel");
    expect(screen.getByTestId("dispatch-unrouted-count").textContent).toBe("1");
    expect(screen.getByTestId("dispatch-unrouted-row-u-1")).toBeInTheDocument();
    expect(screen.getByTestId("dispatch-unrouted-reason-u-1").textContent)
      .toMatch(/No service day/i);
    // Suggest button POSTs.
    apiPostMock.mockResolvedValue({ items: [{
      customer_id: "u-1",
      suggestion: {
        tech_user_id: "t-mike", tech_name: "Mike", tech_color_hex: "#4F46E5",
        service_day: "wed", day_label: "Wed", insertion_index: 2,
        added_seconds: 420, added_meters: 1000,
        confidence: "high", rationale: "0.6 mi away on Mike's Wed route",
      },
      alternatives: [],
    }]});
    fireEvent.click(screen.getByTestId("dispatch-unrouted-suggest-u-1"));
    await waitFor(() => expect(apiPostMock).toHaveBeenCalledWith(
      "/dispatch/suggest-route",
      expect.objectContaining({ customer_ids: ["u-1"] }),
    ));
    // Suggestion card appears with confidence pill + Apply btn.
    expect(await screen.findByTestId("dispatch-unrouted-suggestion-u-1"))
      .toBeInTheDocument();
    expect(screen.getByTestId("dispatch-unrouted-confidence-u-1").textContent)
      .toMatch(/high/);
  });

  it("active shifts sidebar lists overrides and Cancel POSTs the endpoint", async () => {
    render(<MemoryRouter><DispatchBoardPage /></MemoryRouter>);
    await screen.findByTestId("active-shifts-sidebar");
    expect(screen.getByTestId("active-shifts-badge").textContent).toBe("1");
    expect(screen.getByTestId("active-shift-row-ov-1")).toBeInTheDocument();
    apiPostMock.mockResolvedValue({ ok: true });
    fireEvent.click(screen.getByTestId("active-shift-cancel-ov-1"));
    await waitFor(() => expect(apiPostMock).toHaveBeenCalledWith(
      "/dispatch/reassign/ov-1/cancel",
    ));
  });

  it("shift-route dialog: segmented toggle shows permanent help + ack checkbox required", async () => {
    render(<MemoryRouter><DispatchBoardPage /></MemoryRouter>);
    // Pick a tech so Shift Route becomes enabled.
    await screen.findByTestId("dispatch-tech-select");
    fireEvent.change(screen.getByTestId("dispatch-tech-select"), {
      target: { value: "t-mike" },
    });
    // Open dialog.
    fireEvent.click(await screen.findByTestId("dispatch-shift-route-btn"));
    expect(await screen.findByTestId("shift-route-dialog")).toBeInTheDocument();
    // Default week mode → help text is visible, no ack checkbox.
    expect(screen.getByTestId("shift-duration-week-help")).toBeInTheDocument();
    expect(screen.queryByTestId("shift-permanent-ack-checkbox")).toBeNull();
    // Toggle to Permanent → help changes + ack checkbox appears.
    fireEvent.click(screen.getByTestId("shift-duration-permanent"));
    expect(screen.getByTestId("shift-duration-permanent-help")).toBeInTheDocument();
    const ack = screen.getByTestId("shift-permanent-ack-checkbox");
    expect(ack).toBeInTheDocument();
    // Pick a target tech so target is set.
    fireEvent.change(screen.getByTestId("shift-target-tech-select"), {
      target: { value: "t-tgt" },
    });
    // Confirm button remains disabled without ack.
    expect(screen.getByTestId("shift-route-confirm-btn")).toBeDisabled();
    fireEvent.click(ack);
    expect(screen.getByTestId("shift-route-confirm-btn")).not.toBeDisabled();
  });

  it("shift-route dialog POSTs correct payload including duration flag", async () => {
    render(<MemoryRouter><DispatchBoardPage /></MemoryRouter>);
    await screen.findByTestId("dispatch-tech-select");
    fireEvent.change(screen.getByTestId("dispatch-tech-select"), {
      target: { value: "t-mike" },
    });
    fireEvent.click(await screen.findByTestId("dispatch-shift-route-btn"));
    // Fill target tech.
    fireEvent.change(await screen.findByTestId("shift-target-tech-select"), {
      target: { value: "t-tgt" },
    });
    apiPostMock.mockResolvedValue({
      id: "ov-new", start_at: "x", end_at: "y",
      customer_ids: ["c-1"], same_day_warning: false,
    });
    fireEvent.click(screen.getByTestId("shift-route-confirm-btn"));
    await waitFor(() => expect(apiPostMock).toHaveBeenCalledWith(
      "/dispatch/reassign",
      expect.objectContaining({
        source_tech_user_id: "t-mike",
        target_tech_user_id: "t-tgt",
        duration: "week",
        scope: "whole_route",
      }),
    ));
  });

  it("save persistence: savePinColorMode + loadPinColorMode round-trip", () => {
    savePinColorMode("crew");
    expect(loadPinColorMode()).toBe("crew");
    savePinColorMode("service_day");
    expect(loadPinColorMode()).toBe("service_day");
  });
});
