/**
 * Phase CAD-2 · Feb-2026 — Icon library placement.
 *
 * User selects an icon in the sidebar, clicks on the canvas, and
 * an ``elements[]`` entry with ``type: icon`` + the chosen icon
 * key persists via PUT.
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
  useParams: () => ({ id: "design-icons" }),
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


describe("CAD-2 · icon library", () => {
  it("select tree icon + click canvas = elements[] gets a tree icon "
     + "element", async () => {
    getSpy.mockResolvedValue({
      id: "design-icons", name: "Icons test",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    // Library section visible.
    expect(screen.getByTestId("cad-icon-library-section")).toBeTruthy();
    // Plants + lighting: assert every documented option is
    // pickable.
    for (const k of [
      "tree", "shrub", "bush", "palm", "grass",
      "path_light", "spot_light", "wall_light",
    ]) {
      expect(screen.getByTestId(`cad-icon-${k}`)).toBeTruthy();
    }
    // Pick tree.
    fireEvent.click(screen.getByTestId("cad-icon-tree"));
    // Place on canvas.
    const canvas = screen.getByTestId("cad-canvas");
    fireEvent.mouseDown(canvas, { clientX: 400, clientY: 250 });

    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const lastCall = putSpy.mock.calls[putSpy.mock.calls.length - 1];
    const [path, body] = lastCall;
    expect(path).toBe("/designs/design-icons");
    const icons = body.elements.filter((e) => e.type === "icon");
    expect(icons).toHaveLength(1);
    expect(icons[0].props?.icon).toBe("tree");
    expect(icons[0].coords).toHaveLength(1);
    expect(icons[0].coords[0].x).toBeCloseTo(0.5, 5);
    expect(icons[0].coords[0].y).toBeCloseTo(0.5, 5);
  });
});
