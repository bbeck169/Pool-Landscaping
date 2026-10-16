/**
 * Feb-2026 · Schedule map — tech-label bug fix lock.
 *
 * Operator-reported bug: the schedule map legend + route pins
 * were rendering truncated UUIDs (``Tech b72852…``) because the
 * fallback stringified ``technician_id`` directly. This suite
 * locks the new shared resolver + its three render-sites:
 *
 *   1. ``resolveTechFirstName`` honest-fallback chain
 *      (first_name → name/display_name split → email local-part
 *      title-case → ``Tech <last-4-of-id>``).
 *   2. ``resolveTechInitials`` honest-fallback chain.
 *   3. Legend row renders first-name (NOT a truncated UUID).
 *   4. Numbered route-stop pin renders ``NN·II`` when initials
 *      resolve, falls back to the bare ``NN`` when they don't.
 *   5. Pin button ``title`` carries the full ``Stop NN —
 *      <FirstName>`` hover tooltip.
 *   6. Pre-fix string (``Tech <first-6-chars>…``) is absent from
 *      every surface post-fix.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";


// Mock @vis.gl/react-google-maps so the test is a pure React
// render — matches sibling schedule-map suites.
vi.mock("@vis.gl/react-google-maps", () => ({
  Map: ({ children }) => <div data-testid="google-map-stub">{children}</div>,
  AdvancedMarker: ({ children, position }) => (
    <div data-lat={position?.lat} data-lng={position?.lng}>{children}</div>
  ),
  InfoWindow: ({ children }) => <div>{children}</div>,
  useMap: () => null,
}));

vi.mock("@googlemaps/markerclusterer", () => ({
  MarkerClusterer: class {
    constructor() {}
    addMarker() {}
    removeMarker() {}
    clearMarkers() {}
    setMap() {}
  },
}));

vi.mock("@/hooks/useLiveTechLocations", () => ({
  useLiveTechLocations: () => ({
    pings: [], enabled: false, setEnabled: () => {},
  }),
  colorForStaleness: () => "#22C55E",
  formatAge: (s) => `${s}s ago`,
}));


import ScheduleMap, {
  resolveTechFirstName,
  resolveTechInitials,
} from "@/pages/schedule/ScheduleMap";


const PHOENIX_LAT = 33.60;
const PHOENIX_LNG = -112.10;

afterEach(() => cleanup());


// ─────────────────────────────────────────────────────────────
// Pure-function resolver coverage (fallback chain)
// ─────────────────────────────────────────────────────────────
describe("resolveTechFirstName · fallback chain", () => {
  it("(1) prefers ``first_name`` on the tech record", () => {
    const techs = [{ id: "t-fn", first_name: "Ethan",
                     name: "Ignored Name", email: "x@y.z" }];
    expect(resolveTechFirstName("t-fn", techs)).toBe("Ethan");
  });

  it("(2) falls back to the first token of ``name``", () => {
    const techs = [{ id: "t-nm", name: "Jane Doe" }];
    expect(resolveTechFirstName("t-nm", techs)).toBe("Jane");
  });

  it("(2) falls back to the first token of ``display_name``", () => {
    const techs = [{ id: "t-dn", display_name: "Casey Lee" }];
    expect(resolveTechFirstName("t-dn", techs)).toBe("Casey");
  });

  it("(3) falls back to title-cased email local-part first token", () => {
    const techs = [{ id: "t-em", email: "ethan.smith@example.com" }];
    expect(resolveTechFirstName("t-em", techs)).toBe("Ethan");
  });

  it("(3) handles upper-case local-parts cleanly", () => {
    const techs = [{ id: "t-em2", email: "ANNA.LEE@x.io" }];
    expect(resolveTechFirstName("t-em2", techs)).toBe("Anna");
  });

  it("(4) honest fallback is ``Tech <last-4-of-id>`` — NOT the pre-fix prefix", () => {
    // Pre-fix output was ``Tech b72852…`` (first 6 chars + ellipsis).
    // Post-fix uses the last 4 chars which are more useful for
    // operators disambiguating two unnamed techs. Also asserts the
    // output does NOT match the pre-fix shape.
    const techs = []; // tech not in list
    const out = resolveTechFirstName("b72852cf-aa11-45c3-9d50-abcd1234ef99", techs);
    expect(out).toBe("Tech ef99");
    expect(out).not.toMatch(/b72852/);
    expect(out).not.toMatch(/…/);
    expect(out).not.toMatch(/\.\.\./);
  });

  it("(4) short ids fall through to the raw id tail without padding", () => {
    expect(resolveTechFirstName("abc", [])).toBe("Tech abc");
  });

  it("returns ``Unassigned`` for a missing id", () => {
    expect(resolveTechFirstName(null, [])).toBe("Unassigned");
    expect(resolveTechFirstName("", [])).toBe("Unassigned");
    expect(resolveTechFirstName(undefined, [])).toBe("Unassigned");
  });

  it("resolves techs by ``user_id`` too (synth-row shape)", () => {
    const techs = [{ id: "sy-1", user_id: "u-sy-1", first_name: "Rita" }];
    expect(resolveTechFirstName("u-sy-1", techs)).toBe("Rita");
  });
});


describe("resolveTechInitials · fallback chain", () => {
  it("prefers first_name + last_name initials, upper-cased", () => {
    const techs = [{ id: "t", first_name: "ethan", last_name: "miller" }];
    expect(resolveTechInitials("t", techs)).toBe("EM");
  });

  it("falls back to the first two tokens of ``name``", () => {
    const techs = [{ id: "t", name: "Jane Doe Smith" }];
    expect(resolveTechInitials("t", techs)).toBe("JD");
  });

  it("single-token ``name`` returns a single letter", () => {
    const techs = [{ id: "t", name: "Prince" }];
    expect(resolveTechInitials("t", techs)).toBe("P");
  });

  it("email local-part first letter is used as a last resort", () => {
    const techs = [{ id: "t", email: "ethan.smith@x.io" }];
    expect(resolveTechInitials("t", techs)).toBe("E");
  });

  it("returns empty string when there is no name data at all", () => {
    expect(resolveTechInitials("t", [])).toBe("");
  });
});


// ─────────────────────────────────────────────────────────────
// Rendered coverage — legend + pin label + pin tooltip + no
// pre-fix truncated-UUID string anywhere on the surface.
// ─────────────────────────────────────────────────────────────
const _techs = [
  { id: "t-fn", first_name: "Ethan", last_name: "Miller",
    email: "em@example.com" },
  { id: "t-nm", name: "Jane Doe" },
  { id: "t-em", email: "ethan.smith@example.com" },
  // Intentionally omit the fourth tech from the list — the job
  // that references ``t-missing`` exercises the honest
  // ``Tech <last-4-of-id>`` fallback.
];

const _techColorMap = new Map([
  ["t-fn", "#EF4444"],
  ["t-nm", "#3B82F6"],
  ["t-em", "#22C55E"],
  ["t-missing-a1b2c3d4", "#A3A3A3"],
]);


function _jobsFixture() {
  return [
    { id: "j-fn", technician_id: "t-fn", route_index: 0,
      location_lat: PHOENIX_LAT, location_lng: PHOENIX_LNG,
      customer_name: "Ethan's Stop" },
    { id: "j-nm", technician_id: "t-nm", route_index: 0,
      location_lat: PHOENIX_LAT + 0.02,
      location_lng: PHOENIX_LNG + 0.02,
      customer_name: "Jane's Stop" },
    { id: "j-em", technician_id: "t-em", route_index: 0,
      location_lat: PHOENIX_LAT + 0.04,
      location_lng: PHOENIX_LNG + 0.04,
      customer_name: "Email-only Stop" },
    { id: "j-mi", technician_id: "t-missing-a1b2c3d4", route_index: 0,
      location_lat: PHOENIX_LAT + 0.06,
      location_lng: PHOENIX_LNG + 0.06,
      customer_name: "Unknown Tech Stop" },
  ];
}


describe("<ScheduleMap /> · tech-label bug fix", () => {
  it("renders the technician's FIRST NAME in each legend row", () => {
    render(<ScheduleMap jobs={_jobsFixture()} techs={_techs}
                        techColorMap={_techColorMap} />);
    expect(screen.getByTestId("schedule-map-tech-legend-t-fn")
      .textContent).toMatch(/Ethan/);
    expect(screen.getByTestId("schedule-map-tech-legend-t-nm")
      .textContent).toMatch(/Jane/);
    expect(screen.getByTestId("schedule-map-tech-legend-t-em")
      .textContent).toMatch(/Ethan/);
    // Honest fallback — tech not in list → ``Tech <last-4-of-id>``.
    expect(screen.getByTestId("schedule-map-tech-legend-t-missing-a1b2c3d4")
      .textContent).toMatch(/Tech c3d4/);
  });

  it("the pre-fix truncated-UUID pattern never appears on the legend", () => {
    render(<ScheduleMap jobs={_jobsFixture()} techs={_techs}
                        techColorMap={_techColorMap} />);
    // Pre-fix output was ``Tech <first-6>…``. The resolver cannot
    // produce this shape anymore — assert the entire legend is
    // clean of both the ellipsis character and the ASCII-ellipsis.
    const legend = screen.getByTestId("schedule-map-tech-legend");
    expect(legend.textContent).not.toMatch(/…/);
    expect(legend.textContent).not.toMatch(/\.\.\./);
    expect(legend.textContent).not.toMatch(/Tech a1b2c3/);
  });

  it("numbered route-stop pins render ``NN·II`` when initials resolve", () => {
    render(<ScheduleMap jobs={_jobsFixture()} techs={_techs}
                        techColorMap={_techColorMap} />);
    // Ethan Miller → EM; Jane Doe → JD; email-only ethan.smith → E.
    expect(screen.getByTestId("schedule-map-pin-j-fn-svg-label")
      .textContent).toBe("01·EM");
    expect(screen.getByTestId("schedule-map-pin-j-nm-svg-label")
      .textContent).toBe("01·JD");
    expect(screen.getByTestId("schedule-map-pin-j-em-svg-label")
      .textContent).toBe("01·E");
  });

  it("pins for techs with NO name data fall back to the bare stop number", () => {
    render(<ScheduleMap jobs={_jobsFixture()} techs={_techs}
                        techColorMap={_techColorMap} />);
    // ``t-missing-a1b2c3d4`` is not in ``_techs`` → no initials
    // available → the pin keeps the bare zero-padded stop
    // number (honest fallback, NOT a fabricated name).
    expect(screen.getByTestId("schedule-map-pin-j-mi-svg-label")
      .textContent).toBe("01");
  });

  it("pin button carries the full ``Stop NN — <FirstName>`` tooltip + aria-label", () => {
    render(<ScheduleMap jobs={_jobsFixture()} techs={_techs}
                        techColorMap={_techColorMap} />);
    const pinFn = screen.getByTestId("schedule-map-pin-j-fn");
    expect(pinFn.getAttribute("title")).toBe("Stop 01 — Ethan");
    expect(pinFn.getAttribute("aria-label"))
      .toMatch(/Stop 01 — Ethan/);
    expect(pinFn.getAttribute("data-tech-first-name")).toBe("Ethan");
    expect(pinFn.getAttribute("data-tech-initials")).toBe("EM");

    const pinNm = screen.getByTestId("schedule-map-pin-j-nm");
    expect(pinNm.getAttribute("title")).toBe("Stop 01 — Jane");
    expect(pinNm.getAttribute("data-tech-initials")).toBe("JD");
  });

  it("surfaces no truncated-UUID label anywhere on the rendered map", () => {
    render(<ScheduleMap jobs={_jobsFixture()} techs={_techs}
                        techColorMap={_techColorMap} />);
    // Walk the entire tree and assert the pre-fix string shape
    // (``Tech <6-hex>…``) is impossible by construction after
    // the fix.
    const root = document.body;
    expect(root.textContent).not.toMatch(/Tech [0-9a-f]{6}…/);
    expect(root.textContent).not.toMatch(/Tech [0-9a-f]{6}\.\.\./);
  });
});
