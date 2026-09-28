/**
 * Phase CAD-1 · Feb-2026 — Scale-to-real-world tool.
 *
 * Locks the calibration flow:
 *   1. User activates the ``scale`` tool.
 *   2. Clicks two points on the canvas.
 *   3. Enters a known distance in feet at the ``window.prompt``.
 *   4. Component computes ``feet_per_pixel = known / pixelDistance``,
 *      updates the sidebar input, and PUTs the new value onto the
 *      design via ``/designs/{id}``.
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
  getSpy: vi.fn(),
  putSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get: (...a) => getSpy(...a),
    put: (...a) => putSpy(...a),
  },
}));

vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: "design-scale" }),
  Link: ({ to, children, ...rest }) =>
    <a href={to} {...rest}>{children}</a>,
}));


let fetchSpy;
let promptSpy;

beforeEach(() => {
  getSpy.mockReset();
  putSpy.mockReset();
  putSpy.mockResolvedValue({});
  fetchSpy = vi.fn().mockResolvedValue({
    // We DON'T need the map here — the scale tool works whether or
    // not the map has loaded. Simulate a failed fetch so the map
    // stays absent + the test focuses on the calibration flow.
    ok: false, status: 424,
    json: () => Promise.resolve({ detail: { error_code: "geocode_failed" } }),
    headers: new Headers(),
  });
  global.fetch = fetchSpy;
  global.URL.createObjectURL = vi.fn(() => "blob:noop");
  global.URL.revokeObjectURL = vi.fn();
  promptSpy = vi.spyOn(window, "prompt").mockReturnValue("10");
  // Stub canvas bounding rect so the pixel distance between the two
  // clicks is deterministic (jsdom otherwise returns all zeros).
  Element.prototype.getBoundingClientRect = function () {
    return { left: 0, top: 0, right: 800, bottom: 500,
             width: 800, height: 500, x: 0, y: 0,
             toJSON() { return this; } };
  };
});

afterEach(() => {
  delete global.fetch;
  promptSpy.mockRestore();
});


import CadEditor from "@/pages/cad/Editor.jsx";


describe("CAD-1 · CadEditor scale calibration tool", () => {
  it("two clicks + prompt = 10 → PUTs feet_per_pixel = 10/pxDist "
     + "onto the design", async () => {
    getSpy.mockResolvedValue({
      id: "design-scale",
      name: "Cal test",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
      customer_id: "cust-scale",
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    // Also wait for the (failed) map fetch to settle so any
    // stale-closure PUTs don't interfere with the assertion.
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    putSpy.mockClear();

    // Activate the scale tool.
    fireEvent.click(screen.getByTestId("cad-tool-scale"));
    const stage = screen.getByTestId("cad-konva-stage");
    // Click 1 — (100, 100) in the 800x500 bounding rect.
    fireEvent.mouseDown(stage, { clientX: 100, clientY: 100 });
    // First marker rendered.
    expect(screen.getByTestId("cad-scale-marker-0")).toBeTruthy();
    // Click 2 — (400, 500). Pixel distance = sqrt(300^2 + 400^2) = 500.
    fireEvent.mouseDown(stage, { clientX: 400, clientY: 500 });
    // Prompt fired, we returned "10". Expected ft/px = 10/500 = 0.02.
    expect(promptSpy).toHaveBeenCalled();
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    // The PUT that carries the new feet_per_pixel is the LAST one
    // (a mount-time metadata PUT may have preceded it).
    const putCalls = putSpy.mock.calls;
    const [path, body] = putCalls[putCalls.length - 1];
    expect(path).toBe("/designs/design-scale");
    expect(body).toHaveProperty("feet_per_pixel");
    expect(body.feet_per_pixel).toBeCloseTo(0.02, 4);
    // Sidebar input reflects the calibrated value.
    const fppInput = screen.getByTestId("cad-feet-per-pixel-input");
    expect(parseFloat(fppInput.value)).toBeCloseTo(0.02, 4);
    // Tool falls back to pointer after calibration, markers cleared.
    expect(screen.queryByTestId("cad-scale-marker-0")).toBeNull();
  });
});
