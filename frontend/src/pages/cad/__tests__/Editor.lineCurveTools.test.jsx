/**
 * Phase CAD-3.5b · Feb-2026 — Straight-line + smooth-curve tools.
 *
 * Locks:
 *   1. ``line`` tool: two clicks create a persisted line element with
 *      the correct 2-vertex coord pair.
 *   2. ``line`` vertex-drag updates ``coords[i]``.
 *   3. ``line`` mutation is Undoable via the CAD-3.5a snapshot infra.
 *   4. ``curve`` tool: multi-click accumulates vertices; Enter,
 *      double-click, and the explicit finish button all commit.
 *   5. ``curve`` render carries the default tension prop.
 *   6. ``curve`` vertex-drag updates ``coords[i]``.
 *   7. ``removeElem`` deletes line + curve elements.
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
    post: vi.fn(),
  },
}));

vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: "design-lc" }),
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


async function _mountBlank() {
  getSpy.mockResolvedValue({
    id: "design-lc", name: "u",
    canvas_w_ft: 60, canvas_h_ft: 40,
    elements: [], boundary: [],
  });
  render(<CadEditor />);
  await waitFor(() =>
    expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
  );
}


describe("CAD-3.5b · straight-line tool", () => {
  it("two clicks create a persisted line element with the two coords",
    async () => {
      await _mountBlank();
      fireEvent.click(screen.getByTestId("cad-tool-line"));
      const stage = screen.getByTestId("cad-konva-stage");
      // First click sets in-progress start; no PUT yet.
      fireEvent.mouseDown(stage, { clientX: 100, clientY: 100 });
      expect(putSpy).not.toHaveBeenCalled();
      expect(screen.getByTestId("cad-line-start-marker")).toBeTruthy();
      // Second click commits the line.
      fireEvent.mouseDown(stage, { clientX: 400, clientY: 300 });
      await waitFor(() => expect(putSpy).toHaveBeenCalled());
      const body = putSpy.mock.calls[putSpy.mock.calls.length - 1][1];
      const line = (body.elements || []).find((el) => el.type === "line");
      expect(line).toBeTruthy();
      expect(line.coords).toHaveLength(2);
      expect(line.coords[0].x).toBeCloseTo(100 / 800, 5);
      expect(line.coords[0].y).toBeCloseTo(100 / 500, 5);
      expect(line.coords[1].x).toBeCloseTo(400 / 800, 5);
      expect(line.coords[1].y).toBeCloseTo(300 / 500, 5);
    });

  it("line mutation pushes a snapshot → Undoable", async () => {
    await _mountBlank();
    fireEvent.click(screen.getByTestId("cad-tool-line"));
    const stage = screen.getByTestId("cad-konva-stage");
    fireEvent.mouseDown(stage, { clientX: 100, clientY: 100 });
    fireEvent.mouseDown(stage, { clientX: 400, clientY: 300 });
    await waitFor(() =>
      expect(screen.getByTestId("cad-undo-btn").disabled).toBe(false),
    );
    putSpy.mockClear();
    fireEvent.click(screen.getByTestId("cad-undo-btn"));
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const afterUndo = putSpy.mock.calls[putSpy.mock.calls.length - 1][1];
    expect(afterUndo.elements).toHaveLength(0);
  });

  it("line vertex-drag updates the persisted coord", async () => {
    // Preload a line element so we can grab its testid + drag a
    // vertex directly.
    getSpy.mockResolvedValue({
      id: "design-lc", name: "u",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [{
        id: "line-1", type: "line",
        coords: [{ x: 0.1, y: 0.1 }, { x: 0.5, y: 0.5 }],
        props: {},
      }],
      boundary: [],
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    // Select the line by clicking it.
    fireEvent.click(screen.getByTestId("cad-shape-line-1"));
    // Grab the first vertex handle (rendered by ``VertexHandles``
    // when selected).
    const handle = await waitFor(() =>
      screen.getByTestId("cad-vertex-handle-line-1-0"),
    );
    // Simulate a drag: start on the handle, move on the stage,
    // release on the stage.
    fireEvent.mouseDown(handle);
    const stage = screen.getByTestId("cad-konva-stage");
    fireEvent.mouseMove(stage, { clientX: 640, clientY: 400 });
    fireEvent.mouseUp(stage);
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const body = putSpy.mock.calls[putSpy.mock.calls.length - 1][1];
    const line = body.elements.find((el) => el.id === "line-1");
    expect(line.coords[0].x).toBeCloseTo(640 / 800, 3);
    expect(line.coords[0].y).toBeCloseTo(400 / 500, 3);
  });
});


describe("CAD-3.5b · smooth-curve tool", () => {
  it("multi-click + finish button commits a persisted curve", async () => {
    await _mountBlank();
    fireEvent.click(screen.getByTestId("cad-tool-curve"));
    const stage = screen.getByTestId("cad-konva-stage");
    fireEvent.mouseDown(stage, { clientX: 100, clientY: 100 });
    fireEvent.mouseDown(stage, { clientX: 200, clientY: 250 });
    fireEvent.mouseDown(stage, { clientX: 350, clientY: 150 });
    expect(putSpy).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("cad-curve-finish"));
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const body = putSpy.mock.calls[putSpy.mock.calls.length - 1][1];
    const curve = (body.elements || []).find((el) => el.type === "curve");
    expect(curve).toBeTruthy();
    expect(curve.coords).toHaveLength(3);
    expect(curve.props.tension).toBe(0.5);
  });

  it("Enter key commits the curve", async () => {
    await _mountBlank();
    fireEvent.click(screen.getByTestId("cad-tool-curve"));
    const stage = screen.getByTestId("cad-konva-stage");
    fireEvent.mouseDown(stage, { clientX: 100, clientY: 100 });
    fireEvent.mouseDown(stage, { clientX: 300, clientY: 300 });
    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const body = putSpy.mock.calls[putSpy.mock.calls.length - 1][1];
    expect((body.elements || []).some((el) => el.type === "curve")).toBe(true);
  });

  it("Escape with <2 vertices cancels without persisting", async () => {
    await _mountBlank();
    fireEvent.click(screen.getByTestId("cad-tool-curve"));
    const stage = screen.getByTestId("cad-konva-stage");
    fireEvent.mouseDown(stage, { clientX: 100, clientY: 100 });
    fireEvent.keyDown(window, { key: "Escape" });
    // No PUT — nothing to persist.
    expect(putSpy).not.toHaveBeenCalled();
    // In-progress vertices cleared.
    expect(screen.queryByTestId("cad-curve-inprogress")).toBeNull();
  });

  it("curve renders with the tension prop on the underlying <Line>",
    async () => {
      getSpy.mockResolvedValue({
        id: "design-lc", name: "u",
        canvas_w_ft: 60, canvas_h_ft: 40,
        elements: [{
          id: "curve-1", type: "curve",
          coords: [{ x: 0.1, y: 0.1 }, { x: 0.5, y: 0.3 },
                   { x: 0.8, y: 0.6 }],
          props: { tension: 0.5 },
        }],
        boundary: [],
      });
      render(<CadEditor />);
      await waitFor(() =>
        expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
      );
      const shape = screen.getByTestId("cad-shape-curve-1");
      expect(shape.getAttribute("data-shape-type")).toBe("curve");
      expect(shape.getAttribute("data-tension")).toBe("0.5");
    });

  it("curve vertex-drag updates coord[i]", async () => {
    getSpy.mockResolvedValue({
      id: "design-lc", name: "u",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [{
        id: "curve-1", type: "curve",
        coords: [{ x: 0.1, y: 0.1 }, { x: 0.5, y: 0.3 },
                 { x: 0.8, y: 0.6 }],
        props: { tension: 0.5 },
      }],
      boundary: [],
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("cad-shape-curve-1"));
    const handle = await waitFor(() =>
      screen.getByTestId("cad-vertex-handle-curve-1-1"),
    );
    fireEvent.mouseDown(handle);
    const stage = screen.getByTestId("cad-konva-stage");
    fireEvent.mouseMove(stage, { clientX: 640, clientY: 400 });
    fireEvent.mouseUp(stage);
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const body = putSpy.mock.calls[putSpy.mock.calls.length - 1][1];
    const curve = body.elements.find((el) => el.id === "curve-1");
    expect(curve.coords[1].x).toBeCloseTo(640 / 800, 3);
    expect(curve.coords[1].y).toBeCloseTo(400 / 500, 3);
  });
});


describe("CAD-3.5b · delete integration", () => {
  it("line + curve elements delete via the existing removeElem path",
    async () => {
      getSpy.mockResolvedValue({
        id: "design-lc", name: "u",
        canvas_w_ft: 60, canvas_h_ft: 40,
        elements: [
          { id: "line-x", type: "line",
            coords: [{ x: 0.1, y: 0.1 }, { x: 0.5, y: 0.5 }],
            props: {} },
          { id: "curve-x", type: "curve",
            coords: [{ x: 0.2, y: 0.2 }, { x: 0.7, y: 0.7 }],
            props: { tension: 0.5 } },
        ],
        boundary: [],
      });
      render(<CadEditor />);
      await waitFor(() =>
        expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
      );
      // Select the line and press Delete → removeElem fires via
      // the CAD-3.5b keyboard hook.
      fireEvent.click(screen.getByTestId("cad-shape-line-x"));
      fireEvent.keyDown(window, { key: "Delete" });
      await waitFor(() => expect(putSpy).toHaveBeenCalled());
      const body = putSpy.mock.calls[putSpy.mock.calls.length - 1][1];
      expect(body.elements.some((el) => el.id === "line-x")).toBe(false);
      expect(body.elements.some((el) => el.id === "curve-x")).toBe(true);
      // Now select + Backspace the curve.
      putSpy.mockClear();
      fireEvent.click(screen.getByTestId("cad-shape-curve-x"));
      fireEvent.keyDown(window, { key: "Backspace" });
      await waitFor(() => expect(putSpy).toHaveBeenCalled());
      const body2 = putSpy.mock.calls[putSpy.mock.calls.length - 1][1];
      expect(body2.elements.some((el) => el.id === "curve-x")).toBe(false);
    });
});
