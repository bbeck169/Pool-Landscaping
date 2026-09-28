/**
 * Phase CAD-2 · Feb-2026 — property-line snapping.
 *
 * When placing a new element within ``snap_threshold_px`` of an
 * existing edge (boundary polygon or existing element edge), the
 * new vertex snaps onto the edge instead of landing at the raw
 * click coordinates.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

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
  useParams: () => ({ id: "design-snap" }),
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
  Element.prototype.getBoundingClientRect = function () {
    return { left: 0, top: 0, right: 800, bottom: 500,
             width: 800, height: 500, x: 0, y: 0,
             toJSON() { return this; } };
  };
});

afterEach(() => { delete global.fetch; });


import CadEditor from "@/pages/cad/Editor.jsx";


describe("CAD-2 · property-line snapping", () => {
  it("paver vertex 6px inside the boundary snaps to the boundary edge",
    async () => {
    // Boundary rectangle covering the full 800×500 canvas. Click
    // at (400, 494) — 6px from the bottom edge. With
    // ``snap_threshold_px=8``, the vertex should snap to y=500
    // (i.e. y=1.0 normalized).
    getSpy.mockResolvedValue({
      id: "design-snap", name: "Snap",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [
        { x: 0, y: 0 }, { x: 1, y: 0 },
        { x: 1, y: 1 }, { x: 0, y: 1 },
      ],
      snap_threshold_px: 8,
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("cad-tool-paver"));
    const stage = screen.getByTestId("cad-konva-stage");
    // Vertex 1 — solidly interior.
    fireEvent.mouseDown(stage, { clientX: 200, clientY: 250 });
    // Vertex 2 — 6px above the bottom edge → should snap to y=1.
    fireEvent.mouseDown(stage, { clientX: 400, clientY: 494 });
    // Vertex 3 — interior again.
    fireEvent.mouseDown(stage, { clientX: 600, clientY: 250 });
    fireEvent.click(screen.getByTestId("cad-paver-finish"));

    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const [_p, body] = putSpy.mock.calls[putSpy.mock.calls.length - 1];
    const paver = body.elements.find((e) => e.type === "paver");
    expect(paver).toBeTruthy();
    // Second vertex snapped to the boundary bottom (y == 1).
    expect(paver.coords[1].y).toBeCloseTo(1.0, 3);
    // The other vertices did NOT snap (still their raw positions).
    expect(paver.coords[0].y).toBeCloseTo(0.5, 3);
    expect(paver.coords[2].y).toBeCloseTo(0.5, 3);
  });
});
