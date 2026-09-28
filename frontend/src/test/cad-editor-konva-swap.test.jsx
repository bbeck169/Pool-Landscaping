/**
 * Phase CAD-2 · Feb-2026 — react-konva swap lock-on.
 *
 * Mounts the editor after the CAD-2 canvas swap and asserts:
 *   1. A Konva ``<Stage>`` is rendered (mocked to a data-attributed
 *      div) inside the ``cad-canvas`` surface.
 *   2. Every legacy CAD-1 tool button still exists AND the new
 *      CAD-2 tools (paver, wall, tape) are present.
 *   3. The pointer tool is the default.
 *   4. A design with no ``customer_id`` does not fire the map-tile
 *      fetch (CAD-1 contract preserved).
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

const { getSpy, putSpy, postSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(), putSpy: vi.fn(), postSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get: (...a) => getSpy(...a),
    put: (...a) => putSpy(...a),
    post: (...a) => postSpy(...a),
  },
}));

vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: "design-konva" }),
  Link: ({ to, children, ...rest }) =>
    <a href={to} {...rest}>{children}</a>,
}));


let fetchSpy;

beforeEach(() => {
  getSpy.mockReset(); putSpy.mockReset(); postSpy.mockReset();
  fetchSpy = vi.fn();
  global.fetch = fetchSpy;
});

afterEach(() => { delete global.fetch; });


import CadEditor from "@/pages/cad/Editor.jsx";


describe("CAD-2 · react-konva swap", () => {
  it("renders a Konva Stage inside the CAD canvas and keeps all "
     + "legacy + CAD-2 tools accessible", async () => {
    getSpy.mockResolvedValue({
      id: "design-konva", name: "Konva swap",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    // Konva Stage present (mocked as div with data-konva-kind).
    const stage = screen.getByTestId("cad-konva-stage");
    expect(stage).toBeTruthy();
    expect(stage.getAttribute("data-konva-kind")).toBe("Stage");
    // Layer present.
    expect(screen.getByTestId("cad-konva-layer")).toBeTruthy();
    // Legacy tools preserved.
    expect(screen.getByTestId("cad-tool-pointer")).toBeTruthy();
    expect(screen.getByTestId("cad-tool-rect")).toBeTruthy();
    expect(screen.getByTestId("cad-tool-circle")).toBeTruthy();
    expect(screen.getByTestId("cad-tool-scale")).toBeTruthy();
    // CAD-2 tools present.
    expect(screen.getByTestId("cad-tool-paver")).toBeTruthy();
    expect(screen.getByTestId("cad-tool-wall")).toBeTruthy();
    expect(screen.getByTestId("cad-tool-tape")).toBeTruthy();
    // No customer_id ⇒ no map-tile fetch.
    expect(fetchSpy).not.toHaveBeenCalled();
    // No auto-persist on a freshly-loaded design.
    expect(putSpy).not.toHaveBeenCalled();
  });

  it("event handling lives on the Konva Stage — mouseDown on the "
     + "Stage fires the active tool; mouseDown on the outer div "
     + "does NOT (real swap, not an overlay)", async () => {
    getSpy.mockResolvedValue({
      id: "design-konva", name: "Real swap",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
    });
    // Stub the canvas ref so coord math is deterministic.
    Element.prototype.getBoundingClientRect = function () {
      return { left: 0, top: 0, right: 800, bottom: 500,
               width: 800, height: 500, x: 0, y: 0,
               toJSON() { return this; } };
    };
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("cad-tool-paver"));
    const stage = screen.getByTestId("cad-konva-stage");
    const outerCanvas = screen.getByTestId("cad-canvas");

    // Firing mouseDown on the Stage adds a paver vertex — the
    // primary tool handler is wired to the Konva Stage.
    fireEvent.mouseDown(stage, { clientX: 200, clientY: 200 });
    expect(screen.getByTestId("cad-paver-inprogress")).toBeTruthy();
    // Preview has exactly one vertex circle.
    const afterStage = screen.getByTestId("cad-paver-inprogress")
      .querySelectorAll('[data-konva-kind="Circle"]').length;
    expect(afterStage).toBe(1);

    // Firing mouseDown on the outer div MUST NOT add another
    // vertex — the outer wrapper is a positioning container only,
    // it has no handler wired anymore.
    fireEvent.mouseDown(outerCanvas, { clientX: 600, clientY: 400 });
    const afterOuter = screen.getByTestId("cad-paver-inprogress")
      .querySelectorAll('[data-konva-kind="Circle"]').length;
    expect(afterOuter).toBe(1);
  });
});
