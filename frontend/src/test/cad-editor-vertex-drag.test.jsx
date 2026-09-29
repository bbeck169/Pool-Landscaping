/**
 * Phase CAD-2.5 · Feb-2026 — Polygon vertex-drag editing.
 *
 * Preload a design with a paver polygon under the shell. In
 * pointer mode, click the shape body → the shape becomes
 * ``selected`` and Konva ``<Circle>`` vertex handles appear at
 * each vertex (``cad-vertex-handle-<id>-<i>``). Drag one handle
 * by a known offset — the corresponding ``element.coords`` entry
 * live-updates, the auto sqft label re-renders, snap-to-boundary
 * still fires within threshold, and a PUT lands on mouseUp.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

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
  useParams: () => ({ id: "design-vertex-drag" }),
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


// Boilerplate — a 60ft × 40ft canvas, full-canvas boundary, and a
// paver polygon whose vertex #1 sits solidly inside the canvas.
const _seed = (elements) => ({
  id: "design-vertex-drag", name: "Vertex drag",
  canvas_w_ft: 60, canvas_h_ft: 40,
  snap_threshold_px: 8,
  boundary: [
    { x: 0, y: 0 }, { x: 1, y: 0 },
    { x: 1, y: 1 }, { x: 0, y: 1 },
  ],
  elements,
});


describe("CAD-2.5 · polygon vertex-drag", () => {
  it("selecting a paver renders one vertex handle per vertex", async () => {
    getSpy.mockResolvedValue(_seed([
      { id: "el-p", type: "paver",
        coords: [
          { x: 0.2, y: 0.2 }, { x: 0.4, y: 0.2 },
          { x: 0.4, y: 0.4 }, { x: 0.2, y: 0.4 },
        ] },
    ]));
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    // Click the paver body → selected.
    fireEvent.click(screen.getByTestId("cad-shape-el-p"));
    // Four handles, one per vertex.
    for (let i = 0; i < 4; i++) {
      expect(screen.getByTestId(`cad-vertex-handle-el-p-${i}`))
        .toBeTruthy();
    }
  });

  it("drag vertex #0 to a new position + mouseUp → coords updated"
   + " + PUT fires + sqft label re-renders", async () => {
    getSpy.mockResolvedValue(_seed([
      { id: "el-p", type: "paver",
        coords: [
          { x: 0.2, y: 0.2 }, { x: 0.4, y: 0.2 },
          { x: 0.4, y: 0.4 }, { x: 0.2, y: 0.4 },
        ] },
    ]));
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("cad-shape-el-p"));
    // Baseline sqft: 12 ft × 8 ft = 96 sq ft (rectangle spans
    // 0.2..0.4 normalized on a 60 × 40 ft canvas).
    const baselineLabel = screen.getByTestId("cad-shape-label-el-p");
    expect(baselineLabel.getAttribute("data-label-text"))
      .toBe("96 sq ft");

    const handle = screen.getByTestId("cad-vertex-handle-el-p-0");
    const stage = screen.getByTestId("cad-konva-stage");
    // Start drag on the vertex handle (its current pixel is
    // (0.2, 0.2) × (800, 500) = (160, 100)).
    fireEvent.mouseDown(handle, { clientX: 160, clientY: 100 });
    // Drag to (80, 60) — normalized (0.1, 0.12). Well inside the
    // canvas so no snap fires.
    fireEvent.mouseMove(stage, { clientX: 80, clientY: 60 });
    // On live drag the label should re-render with the new area.
    const liveLabel = screen.getByTestId("cad-shape-label-el-p");
    expect(liveLabel.getAttribute("data-label-text"))
      .not.toBe("96 sq ft");
    // Release → PUT fires.
    fireEvent.mouseUp(stage, { clientX: 80, clientY: 60 });
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const [_p, body] = putSpy.mock.calls[putSpy.mock.calls.length - 1];
    const paver = body.elements.find((e) => e.id === "el-p");
    expect(paver.coords[0].x).toBeCloseTo(0.1, 3);
    expect(paver.coords[0].y).toBeCloseTo(0.12, 3);
  });

  it("snap-to-boundary fires when a vertex is dragged within"
   + " the snap threshold of the boundary edge", async () => {
    getSpy.mockResolvedValue(_seed([
      { id: "el-p", type: "paver",
        coords: [
          { x: 0.2, y: 0.2 }, { x: 0.4, y: 0.2 },
          { x: 0.4, y: 0.4 }, { x: 0.2, y: 0.4 },
        ] },
    ]));
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("cad-shape-el-p"));
    const handle = screen.getByTestId("cad-vertex-handle-el-p-0");
    const stage = screen.getByTestId("cad-konva-stage");
    fireEvent.mouseDown(handle, { clientX: 160, clientY: 100 });
    // Drag to (300, 4) — 4px from boundary top (y=0), inside the
    // 8px snap threshold. Snap must send the vertex to y = 0.
    fireEvent.mouseMove(stage, { clientX: 300, clientY: 4 });
    fireEvent.mouseUp(stage, { clientX: 300, clientY: 4 });
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const [_p, body] = putSpy.mock.calls[putSpy.mock.calls.length - 1];
    const paver = body.elements.find((e) => e.id === "el-p");
    expect(paver.coords[0].y).toBeCloseTo(0.0, 3);
  });
});
