/**
 * Phase CAD-1 · Feb-2026 — Map backdrop rendering.
 *
 * Locks the contract:
 *   1. When the loaded design has a ``customer_id``, the editor
 *      fires ``fetch(/api/cad/map-tile?...)`` exactly once with an
 *      ``Authorization: Bearer <token>`` header sourced from
 *      ``localStorage``.
 *   2. On a successful response the ``<img data-testid=
 *      "cad-map-backdrop-img">`` renders with the ``URL.createObject
 *      URL(blob)`` url and the sidebar surface reflects the metadata
 *      headers (lat / lng / zoom / feet_per_pixel + status pill).
 *   3. On a 424 ``customer_address_missing`` error the editor does
 *      NOT crash — it renders the ``cad-map-error-banner`` and keeps
 *      the drawing surface live.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const { getSpy, putSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  putSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get: (...a) => getSpy(...a),
    put: (...a) => putSpy(...a),
  },
}));

vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: "design-map" }),
  Link: ({ to, children, ...rest }) =>
    <a href={to} {...rest}>{children}</a>,
}));


let fetchSpy;
let createObjURLSpy;

beforeEach(() => {
  getSpy.mockReset();
  putSpy.mockReset();
  putSpy.mockResolvedValue({});
  fetchSpy = vi.fn();
  global.fetch = fetchSpy;
  // jsdom lacks ``URL.createObjectURL``; stub it.
  createObjURLSpy = vi.fn(() => "blob:mock-backdrop");
  global.URL.createObjectURL = createObjURLSpy;
  global.URL.revokeObjectURL = vi.fn();
  localStorage.setItem("token", "test-jwt-abc");
});

afterEach(() => {
  delete global.fetch;
  localStorage.removeItem("token");
});


import CadEditor from "@/pages/cad/Editor.jsx";


function _mapHeaders({
  lat = 25.7617, lng = -80.1918, zoom = 19,
  feetPerPixel = 0.88, source = "cache",
} = {}) {
  return new Headers({
    "X-Map-Lat": String(lat),
    "X-Map-Lng": String(lng),
    "X-Map-Zoom": String(zoom),
    "X-Feet-Per-Pixel": String(feetPerPixel),
    "X-Geocode-Source": source,
    "Content-Type": "image/png",
  });
}


describe("CAD-1 · CadEditor map backdrop", () => {
  it("fetches the map tile on mount when the design has a customer_id",
    async () => {
    getSpy.mockResolvedValue({
      id: "design-map",
      name: "With customer",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
      customer_id: "cust-42",
    });
    const blob = new Blob([new Uint8Array([137, 80, 78, 71])], {
      type: "image/png",
    });
    fetchSpy.mockResolvedValue({
      ok: true,
      status: 200,
      blob: () => Promise.resolve(blob),
      headers: _mapHeaders({ source: "cache" }),
    });
    render(<CadEditor />);
    // Design + map load.
    await waitFor(() =>
      expect(screen.queryByTestId("cad-map-backdrop-img")).toBeTruthy(),
    );
    // fetch called with the map-tile URL, auth header, and the
    // canvas-baseline size.
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, opts] = fetchSpy.mock.calls[0];
    expect(url).toContain("/api/cad/map-tile");
    expect(url).toContain("customer_id=cust-42");
    expect(url).toContain("zoom=19");
    expect(url).toContain("size=800x500");
    expect(opts.headers.Authorization).toBe("Bearer test-jwt-abc");
    // ``URL.createObjectURL`` fed the blob into the <img> src.
    expect(createObjURLSpy).toHaveBeenCalledWith(blob);
    const img = screen.getByTestId("cad-map-backdrop-img");
    expect(img.getAttribute("src")).toBe("blob:mock-backdrop");
    // Sidebar metadata surfaced from the response headers.
    expect(screen.getByTestId("cad-map-lat-value").textContent).toBe("25.76170");
    expect(screen.getByTestId("cad-map-lng-value").textContent).toBe("-80.19180");
    expect(screen.getByTestId("cad-map-zoom-value").textContent).toBe("19");
    expect(screen.getByTestId("cad-map-status-pill").textContent)
      .toMatch(/Cached/i);
    // Scale bar overlay renders since we have a feet_per_pixel now.
    expect(screen.getByTestId("cad-scale-bar-overlay")).toBeTruthy();
  });

  it("renders the error banner on 424 customer_address_missing "
     + "and keeps the drawing surface live", async () => {
    getSpy.mockResolvedValue({
      id: "design-map",
      name: "Bad address",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
      customer_id: "cust-noaddr",
    });
    fetchSpy.mockResolvedValue({
      ok: false,
      status: 424,
      json: () => Promise.resolve({
        detail: { error_code: "customer_address_missing" },
      }),
      headers: new Headers(),
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-map-error-banner")).toBeTruthy(),
    );
    // Banner shows the server error_code.
    expect(screen.getByTestId("cad-map-error-banner").textContent)
      .toContain("customer_address_missing");
    // Status pill flipped to error state.
    expect(screen.getByTestId("cad-map-status-pill").textContent)
      .toMatch(/Error/i);
    // Canvas still renders — user can draw on a blank surface.
    expect(screen.getByTestId("cad-canvas")).toBeTruthy();
    // No <img> since the map failed.
    expect(screen.queryByTestId("cad-map-backdrop-img")).toBeNull();
  });
});
