/**
 * Feb-2026 · ScheduleMap — Numbered pins + Tech/Day color toggle.
 *
 * Locks the contract that:
 *   1. Every stop renders a numeric label matching ``route_index + 1``.
 *   2. Fill = assigned tech's brand color (gray fallback).
 *   3. Stroke = service-day color derived from ``scheduled_date``
 *      (gray fallback when the date is missing / unparseable).
 *   4. The Tech / Day toggle emphasises one channel visually — the
 *      SAME fill + stroke are always plumbed through; only
 *      ``strokeWidth`` + ``fillOpacity`` change per mode.
 *   5. Preference persists to ``localStorage`` and survives an
 *      unmount / remount.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";


// Mock @vis.gl/react-google-maps BEFORE importing the component so
// the map/marker DOM boils down to plain divs jsdom is happy with.
vi.mock("@vis.gl/react-google-maps", () => ({
  Map: ({ children, style }) => (
    <div data-testid="mock-map" style={style}>{children}</div>
  ),
  AdvancedMarker: ({ children, position, onClick }) => (
    <div
      data-testid={`mock-marker-${position.lat}-${position.lng}`}
      onClick={onClick}
    >
      {children}
    </div>
  ),
  InfoWindow: ({ children }) => (
    <div data-testid="mock-infowindow">{children}</div>
  ),
  useMap: () => null,
}));


import ScheduleMap from "@/pages/schedule/ScheduleMap";
// Import the shared day palette so the tests assert against the
// SAME colors the component uses (never invent our own).
import { PIN_COLOR_BY_DAY } from "@/pages/dispatch/dispatchColors";


// Test dates chosen so each maps to a distinct weekday. All use
// bare ``YYYY-MM-DD`` so the component's ``getUTCDay`` code path
// picks the expected day regardless of the test runner's TZ.
//   2026-02-02 → Monday
//   2026-02-03 → Tuesday
//   2026-02-04 → Wednesday
const _MON = "2026-02-02";
const _TUE = "2026-02-03";
const _WED = "2026-02-04";


const _techs = [
  { id: "tech-a", name: "Alex Tech", display_color_hex: "#FF0000" },
  { id: "tech-b", name: "Bella Tech", display_color_hex: "#00FF00" },
];

const _techColorMap = new Map([
  ["tech-a", "#FF0000"],
  ["tech-b", "#00FF00"],
]);


function _mkJobs() {
  return [
    // route_index 0 → label "01", Monday → blue stroke, tech-a fill.
    {
      id: "job-1", customer_name: "Alice", address: "1 Palm",
      scheduled_time: "09:00", scheduled_date: _MON,
      technician_id: "tech-a", route_index: 0,
      location_lat: 33.75, location_lng: -112.35,
    },
    // route_index 1 → label "02", Tuesday → purple stroke, tech-b fill.
    {
      id: "job-2", customer_name: "Bob", address: "2 Oak",
      scheduled_time: "10:30", scheduled_date: _TUE,
      technician_id: "tech-b", route_index: 1,
      location_lat: 33.76, location_lng: -112.36,
    },
    // route_index 2 → label "03", Wednesday → green stroke.
    // Unassigned tech → GRAY fill fallback.
    {
      id: "job-3", customer_name: "Cara", address: "3 Elm",
      scheduled_time: "11:15", scheduled_date: _WED,
      technician_id: null, route_index: 2,
      location_lat: 33.77, location_lng: -112.37,
    },
    // No route_index (unslotted). Missing scheduled_date so the
    // stroke must fall back to gray as well.
    {
      id: "job-4", customer_name: "Dan", address: "4 Ash",
      scheduled_time: null, scheduled_date: null,
      technician_id: "tech-a", route_index: undefined,
      location_lat: 33.78, location_lng: -112.38,
    },
  ];
}


beforeEach(() => {
  cleanup();
  try { window.localStorage.clear(); } catch { /* jsdom */ }
});


describe("<ScheduleMap /> — numbered pins", () => {
  it("renders a numeric label for each stop matching route_index + 1", () => {
    render(<ScheduleMap jobs={_mkJobs()} techs={_techs}
                        techColorMap={_techColorMap} />);
    // formatPinLabel zero-pads single-digit route_index+1 values.
    expect(
      screen.getByTestId("schedule-map-pin-job-1-svg-label").textContent,
    ).toBe("01");
    expect(
      screen.getByTestId("schedule-map-pin-job-2-svg-label").textContent,
    ).toBe("02");
    expect(
      screen.getByTestId("schedule-map-pin-job-3-svg-label").textContent,
    ).toBe("03");
  });

  it("omits the numeric label when route_index is undefined (unslotted)", () => {
    render(<ScheduleMap jobs={_mkJobs()} techs={_techs}
                        techColorMap={_techColorMap} />);
    expect(
      screen.queryByTestId("schedule-map-pin-job-4-svg-label"),
    ).toBeNull();
  });
});


describe("<ScheduleMap /> — fill (tech) + stroke (day)", () => {
  it("fill matches the assigned tech's brand color from techColorMap", () => {
    render(<ScheduleMap jobs={_mkJobs()} techs={_techs}
                        techColorMap={_techColorMap} />);
    expect(
      screen.getByTestId("schedule-map-pin-job-1-svg-body")
        .getAttribute("data-color"),
    ).toBe("#FF0000");
    expect(
      screen.getByTestId("schedule-map-pin-job-2-svg-body")
        .getAttribute("data-color"),
    ).toBe("#00FF00");
  });

  it("stroke matches the scheduled-day's palette color", () => {
    render(<ScheduleMap jobs={_mkJobs()} techs={_techs}
                        techColorMap={_techColorMap} />);
    // Monday = PIN_COLOR_BY_DAY.mon, Tuesday = .tue, etc.
    const bodyMon = screen.getByTestId("schedule-map-pin-job-1-svg-body");
    const bodyTue = screen.getByTestId("schedule-map-pin-job-2-svg-body");
    const bodyWed = screen.getByTestId("schedule-map-pin-job-3-svg-body");
    expect(bodyMon.getAttribute("data-stroke")).toBe(PIN_COLOR_BY_DAY.mon);
    expect(bodyTue.getAttribute("data-stroke")).toBe(PIN_COLOR_BY_DAY.tue);
    expect(bodyWed.getAttribute("data-stroke")).toBe(PIN_COLOR_BY_DAY.wed);
  });

  it("unassigned technician → gray fill fallback", () => {
    render(<ScheduleMap jobs={_mkJobs()} techs={_techs}
                        techColorMap={_techColorMap} />);
    expect(
      screen.getByTestId("schedule-map-pin-job-3-svg-body")
        .getAttribute("data-color"),
    ).toBe("#94A3B8");
  });

  it("missing scheduled_date → gray stroke fallback", () => {
    render(<ScheduleMap jobs={_mkJobs()} techs={_techs}
                        techColorMap={_techColorMap} />);
    expect(
      screen.getByTestId("schedule-map-pin-job-4-svg-body")
        .getAttribute("data-stroke"),
    ).toBe("#94A3B8");
  });

  it("no tech + no date → both channels gray", () => {
    const grayJob = [{
      id: "job-x", customer_name: "Grey", address: "x",
      scheduled_time: null, scheduled_date: null,
      technician_id: null, route_index: 0,
      location_lat: 33.75, location_lng: -112.35,
    }];
    render(<ScheduleMap jobs={grayJob} techs={_techs}
                        techColorMap={_techColorMap} />);
    const body = screen.getByTestId("schedule-map-pin-job-x-svg-body");
    expect(body.getAttribute("data-color")).toBe("#94A3B8");
    expect(body.getAttribute("data-stroke")).toBe("#94A3B8");
  });
});


describe("<ScheduleMap /> — Tech/Day color toggle", () => {
  it("Tech mode: thin stroke + fully opaque fill", () => {
    // Default (no localStorage) is Tech mode.
    render(<ScheduleMap jobs={_mkJobs()} techs={_techs}
                        techColorMap={_techColorMap} />);
    const body = screen.getByTestId("schedule-map-pin-job-1-svg-body");
    expect(body.getAttribute("data-stroke-width")).toBe("1");
    // fill-opacity 1 → the component passes ``1``; the SVG omits it
    // only when the caller leaves it undefined.
    expect(body.getAttribute("data-fill-opacity")).toBe("1");
  });

  it("Day mode: thicker stroke + dimmed fill (same channels, swapped emphasis)", () => {
    window.localStorage.setItem("schedule_map.pin_color_mode", "day");
    render(<ScheduleMap jobs={_mkJobs()} techs={_techs}
                        techColorMap={_techColorMap} />);
    const body = screen.getByTestId("schedule-map-pin-job-1-svg-body");
    expect(body.getAttribute("data-stroke-width")).toBe("3");
    expect(body.getAttribute("data-fill-opacity")).toBe("0.55");
    // The channels themselves must NOT swap — fill stays tech, stroke
    // stays day, per the "same logic, different emphasis" spec.
    expect(body.getAttribute("data-color")).toBe("#FF0000");
    expect(body.getAttribute("data-stroke")).toBe(PIN_COLOR_BY_DAY.mon);
  });

  it("toggle click flips mode and persists to localStorage", () => {
    render(<ScheduleMap jobs={_mkJobs()} techs={_techs}
                        techColorMap={_techColorMap} />);
    // Initial: Tech is active.
    const techBtn = screen.getByTestId("schedule-map-color-mode-tech");
    const dayBtn  = screen.getByTestId("schedule-map-color-mode-day");
    expect(techBtn.getAttribute("data-active")).toBe("true");
    expect(dayBtn.getAttribute("data-active")).toBe("false");
    // Click Day.
    fireEvent.click(dayBtn);
    expect(screen.getByTestId("schedule-map-color-mode-day")
      .getAttribute("data-active")).toBe("true");
    expect(
      window.localStorage.getItem("schedule_map.pin_color_mode"),
    ).toBe("day");
    // Body stroke-width now reflects the new mode.
    expect(
      screen.getByTestId("schedule-map-pin-job-1-svg-body")
        .getAttribute("data-stroke-width"),
    ).toBe("3");
  });

  it("keyboard: ArrowRight from Tech selects Day", () => {
    render(<ScheduleMap jobs={_mkJobs()} techs={_techs}
                        techColorMap={_techColorMap} />);
    const techBtn = screen.getByTestId("schedule-map-color-mode-tech");
    fireEvent.keyDown(techBtn, { key: "ArrowRight" });
    expect(screen.getByTestId("schedule-map-color-mode-day")
      .getAttribute("data-active")).toBe("true");
    expect(
      window.localStorage.getItem("schedule_map.pin_color_mode"),
    ).toBe("day");
  });

  it("persisted 'day' preference survives unmount → remount", () => {
    window.localStorage.setItem("schedule_map.pin_color_mode", "day");
    const { unmount } = render(
      <ScheduleMap jobs={_mkJobs()} techs={_techs}
                   techColorMap={_techColorMap} />,
    );
    expect(screen.getByTestId("schedule-map-color-mode-day")
      .getAttribute("data-active")).toBe("true");
    unmount();
    render(<ScheduleMap jobs={_mkJobs()} techs={_techs}
                        techColorMap={_techColorMap} />);
    expect(screen.getByTestId("schedule-map-color-mode-day")
      .getAttribute("data-active")).toBe("true");
  });
});
