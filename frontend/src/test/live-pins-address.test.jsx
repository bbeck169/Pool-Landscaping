/**
 * Phase G3 · Feb-2026 — Live tech pin InfoWindow address tests.
 *
 * Verifies the InfoWindow renders:
 *   • ``address.formatted`` when present.
 *   • "MAPBOX_ACCESS_TOKEN" hint when ``address_status="no_token"``.
 *   • Coordinate fallback otherwise.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// @vis.gl/react-google-maps needs a stub — AdvancedMarker + InfoWindow
// are just rendered as passthrough <div>s in tests.
vi.mock("@vis.gl/react-google-maps", () => ({
  AdvancedMarker: ({ children, onClick }) => (
    <button type="button" onClick={onClick}
            data-testid="stub-advanced-marker">
      {children}
    </button>
  ),
  InfoWindow: ({ children }) => (
    <div data-testid="stub-info-window">{children}</div>
  ),
}));

import LiveTechPinsLayer from "@/pages/dispatch/LiveTechPinsLayer";

const _basePos = (over = {}) => ({
  user_id: "u1", user_name: "Ana Tech",
  lat: 33.5, lon: -112.0,
  captured_at: "2026-02-14T09:00:00Z",
  staleness_s: 20, accuracy_m: 12,
  clock_in_id: "ci-1",
  ...over,
});

function _openInfo() {
  fireEvent.click(screen.getAllByTestId("stub-advanced-marker")[0]);
}

describe("LiveTechPinsLayer · address rendering", () => {
  it("shows the formatted address when present", () => {
    const positions = [_basePos({
      address: { formatted: "123 Main St, Peoria, AZ 85383" },
      address_status: "resolved",
    })];
    render(<LiveTechPinsLayer positions={positions} />);
    _openInfo();
    const info = screen.getByTestId("dispatch-live-tech-info-u1");
    expect(info.textContent).toContain("123 Main St, Peoria, AZ 85383");
  });

  it("shows the 'MAPBOX_ACCESS_TOKEN' hint when no_token", () => {
    const positions = [_basePos({
      address: null, address_status: "no_token",
    })];
    render(<LiveTechPinsLayer positions={positions} />);
    _openInfo();
    expect(
      screen.getByTestId("dispatch-live-tech-addr-notoken-u1"))
      .toBeInTheDocument();
  });

  it("shows the coordinate fallback when address missing without status",
     () => {
    const positions = [_basePos({
      address: null, address_status: "error",
    })];
    render(<LiveTechPinsLayer positions={positions} />);
    _openInfo();
    const fb = screen.getByTestId("dispatch-live-tech-addr-fallback-u1");
    expect(fb).toBeInTheDocument();
    expect(fb.textContent).toContain("33.50000");
    expect(fb.textContent).toContain("-112.00000");
  });
});
