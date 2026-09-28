/**
 * Phase CAD-2 · Feb-2026 — Wall polyline tool.
 *
 * Locks the polyline flow — three clicks → Finish → an element
 * with ``type: wall`` + open coord list persists, and the rendered
 * wall carries a linear-ft label.
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
  useParams: () => ({ id: "design-wall" }),
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


describe("CAD-2 · wall polyline tool", () => {
  it("three clicks + finish = wall element with linear-ft label", async () => {
    getSpy.mockResolvedValue({
      id: "design-wall", name: "Wall test",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );

    fireEvent.click(screen.getByTestId("cad-tool-wall"));
    expect(screen.getByTestId("cad-wall-finish")).toBeTruthy();
    const stage = screen.getByTestId("cad-konva-stage");
    fireEvent.mouseDown(stage, { clientX: 80, clientY: 100 });
    fireEvent.mouseDown(stage, { clientX: 400, clientY: 100 });
    fireEvent.mouseDown(stage, { clientX: 720, clientY: 100 });
    expect(screen.getByTestId("cad-wall-inprogress")).toBeTruthy();

    fireEvent.click(screen.getByTestId("cad-wall-finish"));
    expect(screen.queryByTestId("cad-wall-inprogress")).toBeNull();

    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const lastCall = putSpy.mock.calls[putSpy.mock.calls.length - 1];
    const [path, body] = lastCall;
    expect(path).toBe("/designs/design-wall");
    const walls = body.elements.filter((e) => e.type === "wall");
    expect(walls).toHaveLength(1);
    expect(walls[0].coords).toHaveLength(3);
    // Linear-ft label rendered on the shape.
    const labels = screen.getAllByTestId(/^cad-shape-label-/);
    const wallLabel = labels.find(
      (l) => (l.getAttribute("data-label-text") || "")
                .trim().endsWith(" ft"),
    );
    expect(wallLabel).toBeTruthy();
  });
});
