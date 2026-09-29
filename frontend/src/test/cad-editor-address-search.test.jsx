/**
 * Phase CAD-ADDR · Feb-2026 — Address-driven site mapping.
 *
 * Locks the editor's integration with ``AddressAutocomplete`` and
 * ``GET /api/cad/map-tile-by-coords``:
 *
 *   1. The sidebar exposes a ``cad-address-search`` field.
 *   2. Selecting an address fires ``fetch(/api/cad/map-tile-by-
 *      coords?...)`` with the caller-provided lat / lng / label.
 *   3. A successful blob response wires the ``<img>`` src to a
 *      ``URL.createObjectURL(blob)`` url AND a PUT to
 *      ``/designs/${id}`` persists the new map metadata.
 *   4. A 424 error surface renders the inline banner and does NOT
 *      crash the editor.
 *   5. Consecutive selections revoke the prior object URL before
 *      wiring the new one — no memory leak.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

vi.mock("react-konva", async () => {
  const R = await import("react");
  const p = (kind) => (({ children, ...props }) =>
    R.createElement("div", { "data-konva-kind": kind, ...props }, children));
  return {
    Stage: p("Stage"), Layer: p("Layer"), Group: p("Group"),
    Rect: p("Rect"), Circle: p("Circle"), Line: p("Line"),
    Text: p("KText"), Image: p("Image"),
  };
});

const { getSpy, putSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(), putSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get: (...a) => getSpy(...a),
    put: (...a) => putSpy(...a),
    post: vi.fn(),
  },
}));

vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: "design-addr" }),
  Link: ({ to, children, ...rest }) =>
    <a href={to} {...rest}>{children}</a>,
}));


// Stubbed AddressAutocomplete — replaces the real component with a
// pair of ``data-testid`` seeded buttons that fire ``onChange`` with
// the exact payload shape the real component emits.  Keeps the test
// focused on the editor's integration path (fetch + PUT + state
// updates) without pulling in the Google Places proxy flow.
vi.mock("@/components/common/AddressAutocomplete", () => ({
  default: ({ onChange, testId = "address-autocomplete" }) => (
    <div data-testid={`${testId}-wrapper`}>
      <input data-testid={testId} placeholder="stub" readOnly />
      <button
        data-testid={`${testId}-fire-miami`}
        onClick={() => onChange({
          street: "1 Test St", city: "Miami", state: "FL", zip: "33101",
          latitude: 25.7617, longitude: -80.1918,
          formatted: "1 Test St, Miami, FL 33101",
        })}
      >Miami</button>
      <button
        data-testid={`${testId}-fire-phoenix`}
        onClick={() => onChange({
          street: "2 Second Ave", city: "Phoenix", state: "AZ", zip: "85001",
          latitude: 33.4484, longitude: -112.0740,
          formatted: "2 Second Ave, Phoenix, AZ 85001",
        })}
      >Phoenix</button>
      <button
        data-testid={`${testId}-fire-manual`}
        onClick={() => onChange({
          street: "typed", formatted: "typed",
          // No latitude / longitude — manual input path.
        })}
      >Manual</button>
    </div>
  ),
}));


let fetchSpy;
let createObjURLSpy;
let revokeObjURLSpy;

beforeEach(() => {
  getSpy.mockReset(); putSpy.mockReset();
  putSpy.mockResolvedValue({});
  fetchSpy = vi.fn();
  global.fetch = fetchSpy;
  createObjURLSpy = vi.fn();
  revokeObjURLSpy = vi.fn();
  global.URL.createObjectURL = createObjURLSpy;
  global.URL.revokeObjectURL = revokeObjURLSpy;
  localStorage.setItem("token", "test-jwt-abc");
});

afterEach(() => {
  delete global.fetch;
  localStorage.removeItem("token");
});


import CadEditor from "@/pages/cad/Editor.jsx";


function _byCoordsHeaders({
  lat = 25.7617, lng = -80.1918, zoom = 19,
  feetPerPixel = 0.88, label = null,
} = {}) {
  const h = new Headers({
    "X-Map-Lat": String(lat),
    "X-Map-Lng": String(lng),
    "X-Map-Zoom": String(zoom),
    "X-Feet-Per-Pixel": String(feetPerPixel),
    "X-Geocode-Source": "coords",
    "Content-Type": "image/png",
  });
  if (label) h.set("X-Map-Label", label);
  return h;
}


// Design fixture with NO customer_id → the CAD-1 auto map-load
// stays off and every fetch call in the test comes from the
// address-search path.
const _seed = () => ({
  id: "design-addr", name: "Address drop",
  canvas_w_ft: 60, canvas_h_ft: 40,
  snap_threshold_px: 8,
  boundary: [
    { x: 0, y: 0 }, { x: 1, y: 0 },
    { x: 1, y: 1 }, { x: 0, y: 1 },
  ],
  elements: [],
});


describe("CAD-ADDR · address-driven map load", () => {
  it("renders the Site Address search field in the sidebar", async () => {
    getSpy.mockResolvedValue(_seed());
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-address-section")).toBeTruthy(),
    );
    expect(screen.getByTestId("cad-address-search")).toBeTruthy();
  });

  it("selection fires fetch(/api/cad/map-tile-by-coords) with the "
   + "caller-provided lat + lng + label", async () => {
    getSpy.mockResolvedValue(_seed());
    const blob = new Blob([new Uint8Array([137, 80, 78, 71])],
                          { type: "image/png" });
    createObjURLSpy.mockReturnValueOnce("blob:one");
    fetchSpy.mockResolvedValueOnce({
      ok: true, status: 200,
      blob: () => Promise.resolve(blob),
      headers: _byCoordsHeaders({ label: "1 Test St, Miami, FL 33101" }),
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-address-section")).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByTestId("cad-address-search-fire-miami"));
    });

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    const [url, opts] = fetchSpy.mock.calls[0];
    expect(url).toContain("/api/cad/map-tile-by-coords");
    expect(url).toContain("lat=25.7617");
    expect(url).toContain("lng=-80.1918");
    expect(url).toContain("zoom=19");
    expect(url).toContain("size=800x500");
    // ``URLSearchParams`` encodes spaces as ``+`` and commas as
    // ``%2C``. Decode both to check the round-trip label.
    const rawLabel = url.split("label=")[1] || "";
    expect(decodeURIComponent(rawLabel.replace(/\+/g, "%20")))
      .toBe("1 Test St, Miami, FL 33101");
    expect(opts.headers.Authorization).toBe("Bearer test-jwt-abc");
  });

  it("successful response wires the map + PUTs the design metadata",
   async () => {
    getSpy.mockResolvedValue(_seed());
    const blob = new Blob([new Uint8Array([137, 80, 78, 71])],
                          { type: "image/png" });
    createObjURLSpy.mockReturnValueOnce("blob:one");
    fetchSpy.mockResolvedValueOnce({
      ok: true, status: 200,
      blob: () => Promise.resolve(blob),
      headers: _byCoordsHeaders({
        lat: 25.7617, lng: -80.1918, zoom: 19,
        feetPerPixel: 0.88, label: "1 Test St, Miami, FL 33101",
      }),
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-address-section")).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByTestId("cad-address-search-fire-miami"));
    });

    // Backdrop <img> rendered with the object URL.
    await waitFor(() =>
      expect(screen.queryByTestId("cad-map-backdrop-img")).toBeTruthy());
    expect(screen.getByTestId("cad-map-backdrop-img")
                 .getAttribute("src")).toBe("blob:one");
    // Sidebar surface reflects the response headers.
    expect(screen.getByTestId("cad-map-lat-value").textContent)
      .toBe("25.76170");
    expect(screen.getByTestId("cad-map-lng-value").textContent)
      .toBe("-80.19180");
    // Address caption reflects the label header.
    expect(screen.getByTestId("cad-address-current-label").textContent)
      .toContain("1 Test St, Miami, FL 33101");
    // PUT lands with the new map metadata.
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const [ppath, pbody] = putSpy.mock.calls[
      putSpy.mock.calls.length - 1
    ];
    expect(ppath).toBe("/designs/design-addr");
    expect(pbody.map_center_lat).toBeCloseTo(25.7617, 4);
    expect(pbody.map_center_lng).toBeCloseTo(-80.1918, 4);
    expect(pbody.map_zoom).toBe(19);
    expect(pbody.feet_per_pixel).toBeCloseTo(0.88, 2);
  });

  it("424 response renders the error banner without crashing",
   async () => {
    getSpy.mockResolvedValue(_seed());
    fetchSpy.mockResolvedValueOnce({
      ok: false, status: 424,
      json: () => Promise.resolve({
        detail: { error_code: "google_maps_key_missing" },
      }),
      headers: new Headers(),
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-address-section")).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByTestId("cad-address-search-fire-miami"));
    });
    await waitFor(() =>
      expect(screen.queryByTestId("cad-map-error-banner")).toBeTruthy());
    expect(screen.getByTestId("cad-map-error-banner").textContent)
      .toContain("google_maps_key_missing");
    // Canvas still renders — the failure is non-fatal.
    expect(screen.getByTestId("cad-canvas")).toBeTruthy();
    // No <img> since the map load failed.
    expect(screen.queryByTestId("cad-map-backdrop-img")).toBeNull();
    // No PUT since the fetch never returned bytes.
    expect(putSpy).not.toHaveBeenCalled();
  });

  it("consecutive selections revoke the prior object URL before "
   + "wiring the new one", async () => {
    getSpy.mockResolvedValue(_seed());
    const blob1 = new Blob([new Uint8Array([137, 80, 78, 71])],
                           { type: "image/png" });
    const blob2 = new Blob([new Uint8Array([137, 80, 78, 71])],
                           { type: "image/png" });
    createObjURLSpy
      .mockReturnValueOnce("blob:first")
      .mockReturnValueOnce("blob:second");
    fetchSpy
      .mockResolvedValueOnce({
        ok: true, status: 200,
        blob: () => Promise.resolve(blob1),
        headers: _byCoordsHeaders({ lat: 25.7617, lng: -80.1918 }),
      })
      .mockResolvedValueOnce({
        ok: true, status: 200,
        blob: () => Promise.resolve(blob2),
        headers: _byCoordsHeaders({ lat: 33.4484, lng: -112.0740 }),
      });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-address-section")).toBeTruthy());

    // First selection.
    await act(async () => {
      fireEvent.click(screen.getByTestId("cad-address-search-fire-miami"));
    });
    await waitFor(() =>
      expect(screen.getByTestId("cad-map-backdrop-img")
                    .getAttribute("src")).toBe("blob:first"));
    expect(revokeObjURLSpy).not.toHaveBeenCalled();

    // Second selection.
    await act(async () => {
      fireEvent.click(screen.getByTestId("cad-address-search-fire-phoenix"));
    });
    await waitFor(() =>
      expect(screen.getByTestId("cad-map-backdrop-img")
                    .getAttribute("src")).toBe("blob:second"));
    // Prior blob URL revoked BEFORE the new one is surfaced.
    expect(revokeObjURLSpy).toHaveBeenCalledWith("blob:first");
  });

  it("manual-input event (no latitude / longitude) is ignored — "
   + "no fetch fires", async () => {
    getSpy.mockResolvedValue(_seed());
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-address-section")).toBeTruthy());
    // The manual-input onChange path in AddressAutocomplete fires
    // WITHOUT lat/lng — the editor's guard rejects it.
    fireEvent.click(screen.getByTestId("cad-address-search-fire-manual"));
    // Give any pending state updates a tick.
    await new Promise((r) => setTimeout(r, 10));
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
