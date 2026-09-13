/**
 * Feb-2026 · ScheduleMap unit tests.
 *
 * The map delegates all Google-Maps DOM work to ``<Map>`` +
 * ``<AdvancedMarker>`` from ``@vis.gl/react-google-maps``. To
 * exercise the component's own logic (pin filtering, empty-state,
 * pin colour, info-window contents) we mock the library to render
 * plain divs so ``@testing-library/react`` can assert on them.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";


// Mock @vis.gl/react-google-maps BEFORE importing the component.
// The <Map> mock intentionally strips google-maps-specific props so
// React doesn't log DOM-attribute warnings during the test run.
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
  InfoWindow: ({ children, onCloseClick }) => (
    <div data-testid="mock-infowindow">
      <button onClick={onCloseClick} data-testid="mock-infowindow-close">×</button>
      {children}
    </div>
  ),
  // Feb-2026 · Round 2 flake fix — production `_ClusteredMarkers`
  // calls `useMap()` from `@vis.gl/react-google-maps`. Returning
  // `null` is safe: both `useEffect` hooks in `ScheduleMap.jsx`
  // early-return when `map` is falsy (verified against the current
  // source), so cluster wiring is a no-op in test and the DOM
  // assertions still fire.
  useMap: () => null,
}));


import ScheduleMap from "@/pages/schedule/ScheduleMap";


const _jobs = [
  {
    id: "job-1",
    customer_name: "Alice Adams",
    address: "123 Palm Way, Peoria",
    scheduled_time: "09:00",
    technician_id: "tech-a",
    location_lat: 33.75,
    location_lng: -112.35,
  },
  {
    id: "job-2",
    customer_name: "Bob Baker",
    address: "456 Oak Ln, Peoria",
    scheduled_time: "10:30",
    technician_id: "tech-b",
    location_lat: 33.76,
    location_lng: -112.36,
  },
  // Ungeocoded — should NOT render a pin.
  {
    id: "job-3",
    customer_name: "Cara Cole",
    address: "789 Elm Rd",
    scheduled_time: "12:00",
    technician_id: "tech-a",
    location_lat: null,
    location_lng: null,
  },
  // 0/0 sentinel — must be treated as ungeocoded.
  {
    id: "job-4",
    customer_name: "Dan Doe",
    address: "0/0 sentinel",
    scheduled_time: null,
    technician_id: null,
    location_lat: 0,
    location_lng: 0,
  },
];

const _techs = [
  { id: "tech-a", name: "Alex Tech", display_color_hex: "#FF0000" },
  { id: "tech-b", name: "Bella Tech", display_color_hex: "#00FF00" },
];

const _techColorMap = new Map([
  ["tech-a", "#FF0000"],
  ["tech-b", "#00FF00"],
]);


describe("<ScheduleMap />", () => {
  it("renders one pin per job with valid coords (2 of 4)", () => {
    render(<ScheduleMap jobs={_jobs} techs={_techs} techColorMap={_techColorMap} />);
    expect(screen.getByTestId("schedule-map-container")).toBeTruthy();
    expect(screen.getByTestId("schedule-map-pin-job-1")).toBeTruthy();
    expect(screen.getByTestId("schedule-map-pin-job-2")).toBeTruthy();
    expect(screen.queryByTestId("schedule-map-pin-job-3")).toBeNull();
    // 0/0 sentinel is treated as ungeocoded.
    expect(screen.queryByTestId("schedule-map-pin-job-4")).toBeNull();
  });

  it("returns null (no map) when no job has coords — empty-state contract", () => {
    const { container } = render(
      <ScheduleMap
        jobs={[_jobs[2], _jobs[3]]}
        techs={_techs}
        techColorMap={_techColorMap}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("uses techColorMap for the pin colour and falls back for unassigned", () => {
    render(<ScheduleMap jobs={_jobs} techs={_techs} techColorMap={_techColorMap} />);
    const pinA = screen.getByTestId("schedule-map-pin-job-1");
    const pinB = screen.getByTestId("schedule-map-pin-job-2");
    expect(pinA.getAttribute("style")).toContain("rgb(255, 0, 0)");
    expect(pinB.getAttribute("style")).toContain("rgb(0, 255, 0)");
  });

  it("falls back to slate-400 when a pinned job has no techColorMap entry", () => {
    const unassignedJob = {
      id: "job-un",
      customer_name: "Zed",
      address: "1 St",
      scheduled_time: "08:00",
      technician_id: null,
      location_lat: 33.77,
      location_lng: -112.37,
    };
    render(<ScheduleMap jobs={[unassignedJob]} techs={_techs} techColorMap={_techColorMap} />);
    const pin = screen.getByTestId("schedule-map-pin-job-un");
    // slate-400 → #94A3B8 → rgb(148, 163, 184).
    expect(pin.getAttribute("style")).toContain("rgb(148, 163, 184)");
  });

  it("shows an InfoWindow with customer, address, time, and tech name on click", () => {
    render(<ScheduleMap jobs={_jobs} techs={_techs} techColorMap={_techColorMap} />);
    // No InfoWindow before click.
    expect(screen.queryByTestId("schedule-map-infowindow")).toBeNull();
    fireEvent.click(screen.getByTestId("schedule-map-pin-job-1"));
    expect(screen.getByTestId("schedule-map-infowindow")).toBeTruthy();
    expect(screen.getByTestId("schedule-map-info-customer-job-1").textContent)
      .toBe("Alice Adams");
    expect(screen.getByTestId("schedule-map-info-address-job-1").textContent)
      .toBe("123 Palm Way, Peoria");
    expect(screen.getByTestId("schedule-map-info-time-job-1").textContent)
      .toBe("09:00");
    expect(screen.getByTestId("schedule-map-info-tech-job-1").textContent)
      .toMatch(/Alex Tech/);
  });

  it("clicking the same pin twice toggles the InfoWindow closed", () => {
    render(<ScheduleMap jobs={_jobs} techs={_techs} techColorMap={_techColorMap} />);
    const pin = screen.getByTestId("schedule-map-pin-job-1");
    fireEvent.click(pin);
    expect(screen.getByTestId("schedule-map-infowindow")).toBeTruthy();
    fireEvent.click(pin);
    expect(screen.queryByTestId("schedule-map-infowindow")).toBeNull();
  });

  it("renders 'Unassigned' as the tech name in the popover when technician_id is null", () => {
    const unassignedJob = {
      id: "job-un",
      customer_name: "Zed",
      address: "1 St",
      scheduled_time: null,
      technician_id: null,
      location_lat: 33.77,
      location_lng: -112.37,
    };
    render(<ScheduleMap jobs={[unassignedJob]} techs={_techs} techColorMap={_techColorMap} />);
    fireEvent.click(screen.getByTestId("schedule-map-pin-job-un"));
    expect(screen.getByTestId("schedule-map-info-tech-job-un").textContent)
      .toMatch(/Unassigned/);
  });
});
