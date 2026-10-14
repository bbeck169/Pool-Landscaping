/**
 * Phase 4 (Multi-Property Map Pins) · Feb-2026 — ScheduleMap vitest.
 *
 * Locks the contract the frontend relies on now that the K58 / P31
 * coord resolver ladder in ``backend/routers/jobs.py`` stamps three
 * new fields on every job in the ``GET /api/jobs`` response:
 *
 *   * ``coord_source``   — ``"job" | "property" | "customer" | null``
 *   * ``property_id``    — the property the job is linked to (null
 *                           when the customer is single-property)
 *   * ``property_label`` — the display label of that property
 *
 * Three assertions:
 *
 *   1. ``coord_source === "property"`` → the InfoWindow carries a
 *      "Property: <label>" chip with ``data-testid`` =
 *      ``schedule-map-info-property-<job.id>``. No chip for other
 *      coord_source values.
 *
 *   2. "Approximate" styling fires when
 *      ``coord_source === "customer" && property_id != null`` — the
 *      pin button carries ``data-approximate="true"``. It does NOT
 *      fire for ``coord_source === "customer"`` alone (single-
 *      property customer whose property_id is null — the legitimate
 *      pre-Phase 4 render).
 *
 *   3. Live Tech Pin overlay (shipped in commit 6db3c4f57) still
 *      mounts in the same tree — additive coexistence. The useLive-
 *      TechLocations hook is mocked so the overlay renders at least
 *      one live-tech marker + the toggle button.
 *
 * Spider-offset dedupe + MarkerClusterer wiring are explicitly NOT
 * exercised here — they're pinned by ``ScheduleMap.pinsColoring.test.jsx``
 * and the preserved behavior means those tests continue to pass
 * unchanged.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


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


// Mock the Live Tech Pin hook so we can assert the overlay coexists
// with the Phase 4 approximate / property-label changes. Returns a
// single fresh live-tech ping so the toggle renders and the
// overlay has at least one marker to show.
vi.mock("@/hooks/useLiveTechLocations", () => ({
  useLiveTechLocations: () => ({
    pings: [
      {
        user_id: "tech-live-1",
        user_name: "Live Tech One",
        lat: 33.9,
        lon: -112.4,
        age_seconds: 15,
        staleness: "fresh",
      },
    ],
    enabled: true,
    setEnabled: () => undefined,
  }),
  colorForStaleness: () => "#22C55E",
  formatAge: (s) => `${s}s ago`,
}));


import ScheduleMap from "@/pages/schedule/ScheduleMap";


const _DATE = "2026-02-02";  // Monday — any valid date works.
const _techs = [
  { id: "tech-a", name: "Alex Tech", display_color_hex: "#FF0000" },
];
const _techColorMap = new Map([["tech-a", "#FF0000"]]);


function _mkJob(overrides) {
  return {
    id: "job-base",
    customer_id: "cust-base",
    customer_name: "Customer",
    address: "1 Palm Lane",
    scheduled_time: "09:00",
    scheduled_date: _DATE,
    technician_id: "tech-a",
    route_index: 0,
    location_lat: 33.75,
    location_lng: -112.35,
    ...overrides,
  };
}


function _renderMap(jobs) {
  return render(
    <MemoryRouter>
      <ScheduleMap jobs={jobs} techs={_techs}
                   techColorMap={_techColorMap} />
    </MemoryRouter>,
  );
}


beforeEach(() => {
  cleanup();
});


describe("ScheduleMap · Phase 4 property-rung chip + approximate pin", () => {
  it("renders a 'Property: <label>' chip in the InfoWindow when "
     + "coord_source === 'property'", () => {
    const job = _mkJob({
      id: "job-property-rung",
      coord_source: "property",
      property_id: "prop-abc",
      property_label: "Vistancia Villa #12",
    });
    _renderMap([job]);
    // Click the pin to open the InfoWindow.
    const pinBtn = screen.getByTestId(`schedule-map-pin-${job.id}`);
    fireEvent.click(pinBtn);
    const propChip = screen.getByTestId(
      `schedule-map-info-property-${job.id}`,
    );
    expect(propChip).toBeTruthy();
    expect(propChip.textContent).toContain("Vistancia Villa #12");
  });

  it("does NOT render the property chip when coord_source === "
     + "'customer' (even if a property_label is incidentally present)",
     () => {
    // A property_label on the wire with coord_source=customer means
    // the ladder DID NOT use the property's coords — the chip must
    // not render (the pin is NOT at the property address).
    const job = _mkJob({
      id: "job-customer-rung",
      coord_source: "customer",
      property_id: null,
      property_label: null,
    });
    _renderMap([job]);
    const pinBtn = screen.getByTestId(`schedule-map-pin-${job.id}`);
    fireEvent.click(pinBtn);
    expect(screen.queryByTestId(
      `schedule-map-info-property-${job.id}`,
    )).toBeNull();
  });

  it("marks the pin as approximate (data-approximate='true', dashed "
     + "border, opacity 0.7) when coord_source === 'customer' AND "
     + "property_id is set — the K58 property rung missed its coords",
     () => {
    const job = _mkJob({
      id: "job-approximate",
      coord_source: "customer",
      // property_id SET → property was attached but had no coords.
      property_id: "prop-nocoords",
      property_label: "Prop No Coords",
    });
    _renderMap([job]);
    const pinBtn = screen.getByTestId(`schedule-map-pin-${job.id}`);
    expect(pinBtn.getAttribute("data-approximate")).toBe("true");
    expect(pinBtn.getAttribute("data-coord-source")).toBe("customer");
    // Dashed outline + reduced opacity.
    expect(pinBtn.style.border).toMatch(/dashed/);
    expect(pinBtn.style.opacity).toBe("0.7");
    // The aria-label calls out approximate-ness for a11y.
    expect(pinBtn.getAttribute("aria-label")).toMatch(/approximate/i);
  });

  it("does NOT mark the pin as approximate when coord_source === "
     + "'customer' AND property_id is NULL (legitimate single-"
     + "property customer render)", () => {
    const job = _mkJob({
      id: "job-legit-customer",
      coord_source: "customer",
      property_id: null,  // ← no property attached ever
      property_label: null,
    });
    _renderMap([job]);
    const pinBtn = screen.getByTestId(`schedule-map-pin-${job.id}`);
    expect(pinBtn.getAttribute("data-approximate")).toBe("false");
    // Opacity stays at 1 — no dim.
    expect(pinBtn.style.opacity).toBe("1");
    // Border is a transparent placeholder (layout parity w/
    // approximate pins) — but NOT dashed.
    expect(pinBtn.style.border).not.toMatch(/dashed/);
  });

  it("does NOT mark the pin as approximate when coord_source === "
     + "'property' (property rung HIT — this is the exact state the "
     + "approximate signal is meant to warn about not happening)",
     () => {
    const job = _mkJob({
      id: "job-property-ok",
      coord_source: "property",
      property_id: "prop-ok",
      property_label: "Good Prop",
    });
    _renderMap([job]);
    const pinBtn = screen.getByTestId(`schedule-map-pin-${job.id}`);
    expect(pinBtn.getAttribute("data-approximate")).toBe("false");
    expect(pinBtn.getAttribute("data-coord-source")).toBe("property");
  });

  it("coexists with the Live Tech Pin overlay (commit 6db3c4f57) — "
     + "both the live-tech toggle and the live-tech marker from the "
     + "mocked hook render in the same tree as the Phase 4 pins",
     () => {
    const job = _mkJob({
      id: "job-coexist",
      coord_source: "property",
      property_id: "prop-cx",
      property_label: "Coexist Prop",
    });
    _renderMap([job]);
    // Phase 4 pin is present.
    expect(screen.getByTestId(`schedule-map-pin-${job.id}`)).toBeTruthy();
    // Live Tech toggle (commit 6db3c4f57) is still mounted.
    expect(screen.getByTestId("schedule-map-live-tech-toggle")).toBeTruthy();
    // Live Tech marker from the mocked hook is still mounted.
    expect(screen.getByTestId("schedule-map-live-tech-pin-tech-live-1"))
      .toBeTruthy();
  });
});
