/**
 * Phase CAD-2-FIX · Feb-2026 — Auto width×length label lock.
 *
 * Fills a CAD-2 spec-compliance gap identified in the audit: no
 * test previously locked the rectangular pool + spa dimension
 * label. This file locks:
 *
 *   1. A 4-coord ``pool`` element renders a
 *      ``cad-shape-dims-<id>`` label with ``<w>' × <l>'`` text
 *      derived from the coord bbox scaled by canvas dims.
 *   2. Same for ``spa``.
 *   3. ``boundary`` shape does NOT emit a width×length label —
 *      per spec, area/dimension labels apply to pool/spa/paver
 *      only, never to the outer property boundary.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("react-konva", async () => {
  const React = await import("react");
  const p = (kind) => (({ children, ...props }) =>
    React.createElement("div", { "data-konva-kind": kind, ...props }, children));
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
  },
}));

vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: "design-wxl" }),
  Link: ({ to, children, ...rest }) =>
    <a href={to} {...rest}>{children}</a>,
}));


beforeEach(() => {
  getSpy.mockReset(); putSpy.mockReset();
  putSpy.mockResolvedValue({});
  global.fetch = vi.fn().mockResolvedValue({
    ok: false, status: 424,
    json: () => Promise.resolve({ detail: { error_code: "no" } }),
    headers: new Headers(),
  });
  global.URL.createObjectURL = vi.fn(() => "blob:noop");
  global.URL.revokeObjectURL = vi.fn();
});

afterEach(() => { delete global.fetch; });


import CadEditor from "@/pages/cad/Editor.jsx";


// Rectangle 0.2..0.5 × 0.3..0.6 on a 60×40 ft canvas:
//   width_ft  = (0.5-0.2)*60 = 18'
//   length_ft = (0.6-0.3)*40 = 12'
const RECT_COORDS = [
  { x: 0.2, y: 0.3 }, { x: 0.5, y: 0.3 },
  { x: 0.5, y: 0.6 }, { x: 0.2, y: 0.6 },
];


describe("CAD-2-FIX · pool/spa auto width×length label", () => {
  it("4-coord pool renders a dims label with the bbox in feet",
    async () => {
    getSpy.mockResolvedValue({
      id: "design-wxl", name: "WxL pool",
      canvas_w_ft: 60, canvas_h_ft: 40,
      boundary: [],
      elements: [
        { id: "el-pool", type: "pool", coords: RECT_COORDS },
      ],
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    const dims = screen.getByTestId("cad-shape-dims-el-pool");
    expect(dims).toBeTruthy();
    expect(dims.getAttribute("data-label-text")).toBe("18' × 12'");
    // Area label ALSO renders alongside (sqft).
    const area = screen.getByTestId("cad-shape-label-el-pool");
    expect(area.getAttribute("data-label-text")).toMatch(/sq ft$/);
  });

  it("4-coord spa renders the same width×length label", async () => {
    getSpy.mockResolvedValue({
      id: "design-wxl", name: "WxL spa",
      canvas_w_ft: 60, canvas_h_ft: 40,
      boundary: [],
      elements: [
        { id: "el-spa", type: "spa", coords: RECT_COORDS },
      ],
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    const dims = screen.getByTestId("cad-shape-dims-el-spa");
    expect(dims).toBeTruthy();
    expect(dims.getAttribute("data-label-text")).toBe("18' × 12'");
  });

  it("boundary element renders WITHOUT a width×length or sqft label "
     + "(spec: no area computed for the outer property boundary)",
    async () => {
    getSpy.mockResolvedValue({
      id: "design-wxl", name: "Boundary only",
      canvas_w_ft: 60, canvas_h_ft: 40,
      boundary: [],
      elements: [
        { id: "el-bnd", type: "boundary", coords: RECT_COORDS },
      ],
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    // No dims label.
    expect(screen.queryByTestId("cad-shape-dims-el-bnd")).toBeNull();
    // No sqft label either.
    expect(screen.queryByTestId("cad-shape-label-el-bnd")).toBeNull();
  });
});
