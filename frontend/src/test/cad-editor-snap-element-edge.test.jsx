/**
 * Phase CAD-2-FIX · Feb-2026 — Element-edge snap lock.
 *
 * The existing ``cad-editor-snap.test.jsx`` locks boundary-edge
 * snap. This one fills the audit-flagged gap by locking the
 * snap-to-EXISTING-element case. Preload a design with a pool at
 * a known rectangle. Activate the paver tool. Click 6px above the
 * pool's bottom edge (well inside the 8px threshold, far outside
 * the boundary-edge threshold). Assert the new paver vertex
 * snapped to the pool edge (``y == 0.5`` in normalized coords),
 * NOT to the boundary bottom at ``y == 1.0``.
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
  useParams: () => ({ id: "design-snap-elem" }),
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


describe("CAD-2-FIX · element-edge snap", () => {
  it("paver vertex 6px from an existing pool's bottom edge snaps "
     + "to that pool edge (not to the boundary)", async () => {
    // Full-canvas boundary AND a pool at x=[0.1..0.5], y=[0.1..0.5].
    // In pixel space: pool bottom edge is y=250, running x=80..400.
    // Boundary bottom is y=500.
    // Click at (200, 244) → 6px above pool bottom, 256px above
    // boundary bottom. Snap must go to the pool edge (y == 0.5),
    // NOT to boundary bottom (y == 1.0).
    getSpy.mockResolvedValue({
      id: "design-snap-elem", name: "Element snap",
      canvas_w_ft: 60, canvas_h_ft: 40,
      snap_threshold_px: 8,
      boundary: [
        { x: 0, y: 0 }, { x: 1, y: 0 },
        { x: 1, y: 1 }, { x: 0, y: 1 },
      ],
      elements: [
        { id: "el-pool", type: "pool",
          coords: [{ x: 0.1, y: 0.1 }, { x: 0.5, y: 0.1 },
                   { x: 0.5, y: 0.5 }, { x: 0.1, y: 0.5 }] },
      ],
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("cad-tool-paver"));
    const stage = screen.getByTestId("cad-konva-stage");
    // Vertex 1 — solidly interior, no snap.
    fireEvent.mouseDown(stage, { clientX: 600, clientY: 300 });
    // Vertex 2 — 6px above the pool's bottom edge. Should snap
    // to the pool edge (y == 0.5 normalized).
    fireEvent.mouseDown(stage, { clientX: 200, clientY: 244 });
    // Vertex 3 — interior again.
    fireEvent.mouseDown(stage, { clientX: 700, clientY: 400 });
    fireEvent.click(screen.getByTestId("cad-paver-finish"));

    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const [_p, body] = putSpy.mock.calls[putSpy.mock.calls.length - 1];
    const paver = body.elements.find((e) => e.type === "paver");
    expect(paver).toBeTruthy();
    // Second vertex snapped to the POOL edge (y = 0.5), not the
    // boundary bottom (y = 1.0).
    expect(paver.coords[1].y).toBeCloseTo(0.5, 3);
    expect(paver.coords[1].y).not.toBeCloseTo(1.0, 2);
    // The other vertices did NOT snap.
    expect(paver.coords[0].y).toBeCloseTo(0.6, 3);
    expect(paver.coords[2].y).toBeCloseTo(0.8, 3);
  });
});
