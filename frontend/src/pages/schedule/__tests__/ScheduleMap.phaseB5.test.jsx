/**
 * Phase B.5 · Feb-2026 — ScheduleMap: numbered pins (per-tech
 * sequence) + per-tech color legend vitest.
 *
 * Covers (7 cases):
 *   1. `_buildPerTechSequence` numbers jobs 1-N per tech using
 *      `route_index` when present (D.1 primary rule).
 *   2. `_buildPerTechSequence` falls back to `scheduled_at` sort
 *      within a tech group when `route_index` is missing (D.1-c).
 *   3. `_buildPerTechSequence` restarts at 1 for each distinct
 *      `technician_id` (D.2 — per-tech-independent numbering).
 *   4. `_buildPerTechSequence` counts a job sequenced before a
 *      coord-dropped job (D.3 — "count but hide" invariant: the
 *      visible pin numbers reflect the full sequence).
 *   5. Rendered pin carries `data-pin-sequence` from the hybrid
 *      resolver (full-render smoke test).
 *   6. Pins dropped by `_buildDedupedPins` (no coords) are NOT
 *      rendered, even though they occupy a sequence slot.
 *   7. Per-tech color legend renders one entry per tech on the day
 *      with the correct stop count.
 *
 * The google-maps wrapper (`../../lib/maps`) is mocked so the test
 * is a pure React render — matches the convention used by the
 * sibling `ScheduleMap.multiPropertyPins.test.jsx` + `.pinsColoring`.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

vi.mock("@vis.gl/react-google-maps", () => ({
  Map: ({ children }) => <div data-testid="google-map-stub">{children}</div>,
  AdvancedMarker: ({ children, position }) => (
    <div data-lat={position?.lat} data-lng={position?.lng}>{children}</div>
  ),
  InfoWindow: ({ children }) => <div>{children}</div>,
  useMap: () => null,
}));

// MarkerClusterer is dynamic — stub so the inner effect no-ops.
vi.mock("@googlemaps/markerclusterer", () => ({
  MarkerClusterer: class {
    constructor() {}
    addMarker() {}
    removeMarker() {}
    clearMarkers() {}
    setMap() {}
  },
}));

// Live-tech hook — return disabled so the overlay doesn't try to
// render against a fake Google Maps API.
vi.mock("@/hooks/useLiveTechLocations", () => ({
  useLiveTechLocations: () => ({
    pings: [], enabled: false, setEnabled: () => {},
  }),
  colorForStaleness: () => "#22C55E",
  formatAge: (s) => `${s}s ago`,
}));

import ScheduleMap, { _buildPerTechSequence }
  from "@/pages/schedule/ScheduleMap";


const PHOENIX_LAT = 33.60;
const PHOENIX_LNG = -112.10;

const _techs = [
  { id: "t1", name: "Alex Rivera" },
  { id: "t2", name: "Jamie Chen" },
];
const _techColorMap = new window.Map([
  ["t1", "#2563EB"],
  ["t2", "#DC2626"],
]);


describe("ScheduleMap · Phase B.5 per-tech sequence numbering", () => {
  afterEach(() => cleanup());

  // ──────────────────────────────────────────────────────────────
  // 1. route_index wins when present
  // ──────────────────────────────────────────────────────────────
  it("_buildPerTechSequence numbers 1..N per tech using route_index", () => {
    const jobs = [
      { id: "j1", technician_id: "t1", route_index: 2 },
      { id: "j2", technician_id: "t1", route_index: 0 },
      { id: "j3", technician_id: "t1", route_index: 1 },
    ];
    const seq = _buildPerTechSequence(jobs);
    expect(seq.get("j2")).toBe(1);
    expect(seq.get("j3")).toBe(2);
    expect(seq.get("j1")).toBe(3);
  });

  // ──────────────────────────────────────────────────────────────
  // 2. Fallback to scheduled_at within a tech group
  // ──────────────────────────────────────────────────────────────
  it("falls back to scheduled_at when route_index is missing", () => {
    const jobs = [
      { id: "jA", technician_id: "t1",
        scheduled_at: "2026-02-15T12:00:00Z" },
      { id: "jB", technician_id: "t1",
        scheduled_at: "2026-02-15T09:00:00Z" },
      { id: "jC", technician_id: "t1",
        scheduled_at: "2026-02-15T15:00:00Z" },
    ];
    const seq = _buildPerTechSequence(jobs);
    expect(seq.get("jB")).toBe(1);
    expect(seq.get("jA")).toBe(2);
    expect(seq.get("jC")).toBe(3);
  });

  // ──────────────────────────────────────────────────────────────
  // 3. Numbering restarts per tech
  // ──────────────────────────────────────────────────────────────
  it("restarts numbering at 1 for each distinct technician_id", () => {
    const jobs = [
      { id: "j1", technician_id: "t1", route_index: 0 },
      { id: "j2", technician_id: "t1", route_index: 1 },
      { id: "j3", technician_id: "t2", route_index: 0 },
      { id: "j4", technician_id: "t2", route_index: 1 },
      { id: "j5", technician_id: "t2", route_index: 2 },
    ];
    const seq = _buildPerTechSequence(jobs);
    // Tech 1: j1=1, j2=2
    expect(seq.get("j1")).toBe(1);
    expect(seq.get("j2")).toBe(2);
    // Tech 2: j3=1, j4=2, j5=3 (independent)
    expect(seq.get("j3")).toBe(1);
    expect(seq.get("j4")).toBe(2);
    expect(seq.get("j5")).toBe(3);
  });

  // ──────────────────────────────────────────────────────────────
  // 4. Count-but-hide invariant: a coord-less job still occupies a slot
  // ──────────────────────────────────────────────────────────────
  it("counts coord-dropped jobs so visible pins keep their numbers", () => {
    const jobs = [
      // j1 has coords.
      { id: "j1", technician_id: "t1", route_index: 0,
        location_lat: PHOENIX_LAT, location_lng: PHOENIX_LNG },
      // j2 is a map "miss" — no coords. Still sequenced #2.
      { id: "j2", technician_id: "t1", route_index: 1,
        location_lat: null, location_lng: null },
      // j3 has coords — sequenced #3.
      { id: "j3", technician_id: "t1", route_index: 2,
        location_lat: PHOENIX_LAT + 0.01,
        location_lng: PHOENIX_LNG + 0.01 },
    ];
    const seq = _buildPerTechSequence(jobs);
    expect(seq.get("j1")).toBe(1);
    expect(seq.get("j2")).toBe(2);  // sequenced even though invisible
    expect(seq.get("j3")).toBe(3);
  });

  // ──────────────────────────────────────────────────────────────
  // 5. Rendered pin carries data-pin-sequence from the hybrid resolver
  // ──────────────────────────────────────────────────────────────
  it("renders data-pin-sequence on each visible pin", () => {
    const jobs = [
      { id: "jA", technician_id: "t1", route_index: 0,
        location_lat: PHOENIX_LAT, location_lng: PHOENIX_LNG,
        customer_name: "Customer A" },
      { id: "jB", technician_id: "t1", route_index: 1,
        location_lat: PHOENIX_LAT + 0.02,
        location_lng: PHOENIX_LNG + 0.02,
        customer_name: "Customer B" },
    ];
    render(
      <ScheduleMap jobs={jobs} techs={_techs}
                    techColorMap={_techColorMap} />,
    );
    expect(screen.getByTestId("schedule-map-pin-jA")
      .getAttribute("data-pin-sequence")).toBe("1");
    expect(screen.getByTestId("schedule-map-pin-jB")
      .getAttribute("data-pin-sequence")).toBe("2");
  });

  // ──────────────────────────────────────────────────────────────
  // 6. Coord-dropped jobs don't render a pin
  // ──────────────────────────────────────────────────────────────
  it("does NOT render a pin for jobs dropped by _buildDedupedPins", () => {
    const jobs = [
      { id: "jOK", technician_id: "t1", route_index: 0,
        location_lat: PHOENIX_LAT, location_lng: PHOENIX_LNG },
      { id: "jDROP", technician_id: "t1", route_index: 1,
        location_lat: null, location_lng: null },
    ];
    render(
      <ScheduleMap jobs={jobs} techs={_techs}
                    techColorMap={_techColorMap} />,
    );
    expect(screen.getByTestId("schedule-map-pin-jOK")).toBeTruthy();
    expect(screen.queryByTestId("schedule-map-pin-jDROP")).toBeNull();
  });

  // ──────────────────────────────────────────────────────────────
  // 7. Per-tech color legend renders one entry per tech + stop count
  // ──────────────────────────────────────────────────────────────
  it("renders the per-tech color legend with correct stop counts", () => {
    const jobs = [
      { id: "a", technician_id: "t1", route_index: 0,
        location_lat: PHOENIX_LAT, location_lng: PHOENIX_LNG },
      { id: "b", technician_id: "t1", route_index: 1,
        location_lat: PHOENIX_LAT + 0.01,
        location_lng: PHOENIX_LNG + 0.01 },
      // t2 has 3 stops — one with no coords (count still 3).
      { id: "c", technician_id: "t2", route_index: 0,
        location_lat: PHOENIX_LAT + 0.02,
        location_lng: PHOENIX_LNG + 0.02 },
      { id: "d", technician_id: "t2", route_index: 1,
        location_lat: PHOENIX_LAT + 0.03,
        location_lng: PHOENIX_LNG + 0.03 },
      { id: "e", technician_id: "t2", route_index: 2,
        location_lat: null, location_lng: null },
    ];
    render(
      <ScheduleMap jobs={jobs} techs={_techs}
                    techColorMap={_techColorMap} />,
    );
    expect(screen.getByTestId("schedule-map-tech-legend")).toBeTruthy();
    expect(screen.getByTestId("schedule-map-tech-legend-t1")
      .textContent).toMatch(/Alex Rivera/);
    expect(screen.getByTestId("schedule-map-tech-legend-count-t1")
      .textContent).toMatch(/2 stops/);
    expect(screen.getByTestId("schedule-map-tech-legend-t2")
      .textContent).toMatch(/Jamie Chen/);
    expect(screen.getByTestId("schedule-map-tech-legend-count-t2")
      .textContent).toMatch(/3 stops/);
  });
});
