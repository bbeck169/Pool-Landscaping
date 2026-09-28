/**
 * Phase CAD-2 · Feb-2026 — Tape Measure tool.
 *
 * Locks:
 *   1. Two clicks emit a tape overlay with a ``12' 6"``-formatted
 *      label using ``feet_per_pixel`` (or the canvas dims when the
 *      user hasn't calibrated).
 *   2. Non-persistent by default — no PUT fires, no element saved.
 *   3. When the "Persist measurement" checkbox is checked BEFORE
 *      the second click, the tape saves into ``design.elements``
 *      with ``type: dimension`` + ``persist_dimension: true``.
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
  useParams: () => ({ id: "design-tape" }),
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


describe("CAD-2 · tape measure", () => {
  it("two clicks non-persistent = ephemeral overlay, no PUT",
    async () => {
    // Canvas 60×40 ft, click from (100, 250) → (400, 250):
    // dx = 300/800 = 0.375 normalized × 60 ft = 22.5 ft → 22' 6".
    getSpy.mockResolvedValue({
      id: "design-tape", name: "Tape test",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );

    fireEvent.click(screen.getByTestId("cad-tool-tape"));
    // Persist checkbox visible but unchecked.
    const cb = screen.getByTestId("cad-tape-persist-checkbox");
    expect(cb.checked).toBe(false);

    const canvas = screen.getByTestId("cad-canvas");
    fireEvent.mouseDown(canvas, { clientX: 100, clientY: 250 });
    fireEvent.mouseDown(canvas, { clientX: 400, clientY: 250 });

    // Overlay rendered with 12' 6"-format label ("22' 6\"" here).
    const overlay = screen.getByTestId("cad-tape-inprogress");
    expect(overlay.getAttribute("data-label-text")).toBe("22' 6\"");
    // No PUT — ephemeral.
    expect(putSpy).not.toHaveBeenCalled();
  });

  it("persist checkbox checked = tape persists into elements[]",
    async () => {
    getSpy.mockResolvedValue({
      id: "design-tape", name: "Tape persist",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );

    fireEvent.click(screen.getByTestId("cad-tool-tape"));
    fireEvent.click(screen.getByTestId("cad-tape-persist-checkbox"));
    const canvas = screen.getByTestId("cad-canvas");
    fireEvent.mouseDown(canvas, { clientX: 100, clientY: 250 });
    fireEvent.mouseDown(canvas, { clientX: 400, clientY: 250 });

    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const [_path, body] = putSpy.mock.calls[putSpy.mock.calls.length - 1];
    const dims = body.elements.filter((e) => e.type === "dimension");
    expect(dims).toHaveLength(1);
    expect(dims[0].props?.persist_dimension).toBe(true);
    expect(dims[0].coords).toHaveLength(2);
  });
});
