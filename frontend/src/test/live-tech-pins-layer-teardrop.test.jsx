/**
 * Phase M1 · Feb-2026 — LiveTechPinsLayer pin-color + halo tests.
 *
 * Locks:
 *   1. Pin color sources from ``techColorById.get(user_id)`` when
 *      present, or from ``colorFromId`` fallback otherwise.
 *   2. Fresh pings (``staleness_s < 120``) carry a halo group;
 *      stale ones do NOT.
 *   3. The pre-existing 15-min ``stale`` UI dimmer is preserved
 *      (``data-stale="true"`` at ≥ 900 s).
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// Stub the maps adapter so ``AdvancedMarker`` / ``InfoWindow``
// render as plain wrappers — pins live in the DOM tree we can
// query.
vi.mock("../lib/maps", () => ({
  AdvancedMarker: ({ children }) => <div data-testid="map-marker-slot">{children}</div>,
  InfoWindow:     ({ children }) => <div data-testid="map-info-slot">{children}</div>,
}));
vi.mock("@/theme", () => ({
  colors: {
    onSurface: "#0F172A", muted: "#64748B", border: "#E2E8F0",
  },
}));

import LiveTechPinsLayer from "@/pages/dispatch/LiveTechPinsLayer";
import { colorFromId } from "@/components/maps/TeardropPin";


const _positions = [
  // Fresh (staleness < 120 s) — must carry halo.
  { user_id: "u-alice", user_name: "Alice Fresh", lat: 33.7, lon: -112.2,
     staleness_s: 30, accuracy_m: 8 },
  // Amber (between 120 and 300 s) — no halo.
  { user_id: "u-bob",   user_name: "Bob Middle",  lat: 33.71, lon: -112.21,
     staleness_s: 200, accuracy_m: 10 },
  // Stale (> 15 min) — no halo, dimmer engages.
  { user_id: "u-carl",  user_name: "Carl Stale",  lat: 33.72, lon: -112.22,
     staleness_s: 1000, accuracy_m: 15 },
];


describe("LiveTechPinsLayer · Phase M1 teardrop", () => {
  it("uses techColorById.get(user_id) when the admin has pinned a color", () => {
    const techColorById = new Map([
      ["u-alice", "#DB2777"], // custom pink
    ]);
    render(<LiveTechPinsLayer positions={_positions} techColorById={techColorById} />);
    const svg = screen.getByTestId("dispatch-live-tech-pin-u-alice");
    const body = screen.getByTestId("dispatch-live-tech-pin-u-alice-body");
    expect(body.getAttribute("fill")).toBe("#DB2777");
    expect(svg.getAttribute("data-pulse")).toBe("true");
  });

  it("falls back to ``colorFromId`` when the admin has NOT set a color", () => {
    render(<LiveTechPinsLayer positions={_positions} techColorById={new Map()} />);
    const body = screen.getByTestId("dispatch-live-tech-pin-u-bob-body");
    expect(body.getAttribute("fill")).toBe(colorFromId("u-bob"));
  });

  it("halo group renders ONLY on fresh pings (staleness < 120 s)", () => {
    render(<LiveTechPinsLayer positions={_positions} />);
    // Fresh — halo present.
    expect(
      screen.getByTestId("dispatch-live-tech-pin-u-alice-halo"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("dispatch-live-tech-pin-u-alice").getAttribute("data-pulse"),
    ).toBe("true");
    // Amber (>=120) — no halo.
    expect(
      screen.queryByTestId("dispatch-live-tech-pin-u-bob-halo"),
    ).toBeNull();
    expect(
      screen.getByTestId("dispatch-live-tech-pin-u-bob").getAttribute("data-pulse"),
    ).toBe("false");
    // Stale — no halo.
    expect(
      screen.queryByTestId("dispatch-live-tech-pin-u-carl-halo"),
    ).toBeNull();
    expect(
      screen.getByTestId("dispatch-live-tech-pin-u-carl").getAttribute("data-pulse"),
    ).toBe("false");
  });

  it("preserves the 15-min UI dimmer via ``data-stale``", () => {
    render(<LiveTechPinsLayer positions={_positions} />);
    // 1000 s = 16.6 min → stale.
    expect(
      screen.getByTestId("dispatch-live-tech-u-carl").getAttribute("data-stale"),
    ).toBe("true");
    // 30 s → not stale.
    expect(
      screen.getByTestId("dispatch-live-tech-u-alice").getAttribute("data-stale"),
    ).toBe("false");
  });
});
