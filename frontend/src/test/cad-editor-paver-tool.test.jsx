/**
 * Phase CAD-2 · Feb-2026 — Pavers polygon tool.
 *
 * Locks:
 *   1. Activating the ``paver`` tool renders the "Close polygon"
 *      button.
 *   2. Three canvas clicks build the polygon vertex list.
 *   3. On close, an element with ``type: paver`` + closed ``coords``
 *      is added to ``design.elements`` and PUT to the server.
 *   4. The rendered paver element carries an in-shape label showing
 *      the computed ``sq ft``.
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
  useParams: () => ({ id: "design-paver" }),
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


describe("CAD-2 · paver polygon tool", () => {
  it("three clicks + close = paver element with sq ft label", async () => {
    getSpy.mockResolvedValue({
      id: "design-paver", name: "Paver test",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );

    // Activate paver tool.
    fireEvent.click(screen.getByTestId("cad-tool-paver"));
    expect(screen.getByTestId("cad-paver-finish")).toBeTruthy();

    const canvas = screen.getByTestId("cad-canvas");
    // Triangle vertices: (0.1, 0.1), (0.9, 0.1), (0.5, 0.9) → area
    // in pixel space = 0.5 * 0.8 * 0.8 = 0.32 (normalized), scaled
    // to 60×40 ft = 60 * 40 * 0.32 = 768 sq ft.
    fireEvent.mouseDown(canvas, { clientX: 80, clientY: 50 });
    fireEvent.mouseDown(canvas, { clientX: 720, clientY: 50 });
    fireEvent.mouseDown(canvas, { clientX: 400, clientY: 450 });
    // Preview polygon rendered.
    expect(screen.getByTestId("cad-paver-inprogress")).toBeTruthy();

    // Close.
    fireEvent.click(screen.getByTestId("cad-paver-finish"));
    // Preview cleared.
    expect(screen.queryByTestId("cad-paver-inprogress")).toBeNull();

    // PUT fired with the paver element.
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const lastCall = putSpy.mock.calls[putSpy.mock.calls.length - 1];
    const [path, body] = lastCall;
    expect(path).toBe("/designs/design-paver");
    const pavers = body.elements.filter((e) => e.type === "paver");
    expect(pavers).toHaveLength(1);
    expect(pavers[0].coords).toHaveLength(3);
    // Label present on the rendered paver.
    const labels = screen.getAllByTestId(/^cad-shape-label-/);
    const paverLabel = labels.find(
      (l) => (l.getAttribute("data-label-text") || "").includes("sq ft"),
    );
    expect(paverLabel).toBeTruthy();
  });
});
