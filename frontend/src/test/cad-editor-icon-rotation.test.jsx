/**
 * Phase CAD-2.5 · Feb-2026 — Icon rotation handle.
 *
 * Preload a design with an icon element. In pointer mode, click
 * the icon body → the icon becomes ``selected`` and a rotation
 * handle appears above the icon centre
 * (``cad-icon-rotation-handle-<id>``). Drag the handle around the
 * icon centre to update ``props.rotation_deg``. Shift-drag snaps
 * to the nearest 15°.
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
  useParams: () => ({ id: "design-icon-rotate" }),
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


const _seed = (icon) => ({
  id: "design-icon-rotate", name: "Icon rotate",
  canvas_w_ft: 60, canvas_h_ft: 40,
  snap_threshold_px: 8,
  boundary: [
    { x: 0, y: 0 }, { x: 1, y: 0 },
    { x: 1, y: 1 }, { x: 0, y: 1 },
  ],
  elements: [icon],
});


describe("CAD-2.5 · icon rotation handle", () => {
  it("selecting an icon renders its rotation handle", async () => {
    getSpy.mockResolvedValue(_seed({
      id: "el-i", type: "icon",
      coords: [{ x: 0.5, y: 0.5 }],
      props: { icon: "tree", rotation_deg: 0 },
    }));
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("cad-shape-el-i"));
    expect(screen.getByTestId("cad-icon-rotation-handle-el-i"))
      .toBeTruthy();
  });

  it("icon renders with rotation transform on its Konva group", async () => {
    getSpy.mockResolvedValue(_seed({
      id: "el-i", type: "icon",
      coords: [{ x: 0.5, y: 0.5 }],
      props: { icon: "tree", rotation_deg: 45 },
    }));
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    const g = screen.getByTestId("cad-shape-el-i");
    // ``data-rotation-deg`` reflects ``props.rotation_deg`` on the
    // Konva group so the source-grep / render-side contract is
    // testable without a real Konva canvas.
    expect(g.getAttribute("data-rotation-deg")).toBe("45");
  });

  it("drag the handle 90° clockwise from up → rotation_deg ≈ 90"
   + " + PUT fires on mouseUp", async () => {
    getSpy.mockResolvedValue(_seed({
      id: "el-i", type: "icon",
      coords: [{ x: 0.5, y: 0.5 }],
      props: { icon: "tree", rotation_deg: 0 },
    }));
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("cad-shape-el-i"));
    const handle = screen.getByTestId("cad-icon-rotation-handle-el-i");
    const stage = screen.getByTestId("cad-konva-stage");
    // Icon centre in pixel space: 0.5 × 800, 0.5 × 500 = (400, 250).
    fireEvent.mouseDown(handle, { clientX: 400, clientY: 230 });
    // Drag directly to the right of the centre → 90°.
    fireEvent.mouseMove(stage, { clientX: 500, clientY: 250 });
    fireEvent.mouseUp(stage, { clientX: 500, clientY: 250 });
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const [_p, body] = putSpy.mock.calls[putSpy.mock.calls.length - 1];
    const icon = body.elements.find((e) => e.id === "el-i");
    expect(icon.props.rotation_deg).toBeCloseTo(90, 0);
  });

  it("Shift-drag snaps to the nearest 15° increment", async () => {
    getSpy.mockResolvedValue(_seed({
      id: "el-i", type: "icon",
      coords: [{ x: 0.5, y: 0.5 }],
      props: { icon: "tree", rotation_deg: 0 },
    }));
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("cad-shape-el-i"));
    const handle = screen.getByTestId("cad-icon-rotation-handle-el-i");
    const stage = screen.getByTestId("cad-konva-stage");
    fireEvent.mouseDown(handle, { clientX: 400, clientY: 230,
                                  shiftKey: true });
    // Icon centre = (400, 250). Canvas is 800×500 so normalised
    // dx per pixel = 1/800, dy per pixel = 1/500. Target a heading
    // that produces ≈ 20° in the normalised frame → snaps DOWN
    // to 15°. tan(70°) = 2.747 so ``dy_norm / dx_norm ≈ -2.747``.
    // Choose ``dx_pix = 40, dy_pix = -69`` → dy_norm/dx_norm =
    // (-69/500) / (40/800) ≈ -2.760 → atan2 offset from up ≈ 20°.
    fireEvent.mouseMove(stage, { clientX: 440, clientY: 181,
                                 shiftKey: true });
    fireEvent.mouseUp(stage, { clientX: 440, clientY: 181,
                               shiftKey: true });
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    let body = putSpy.mock.calls[putSpy.mock.calls.length - 1][1];
    let icon = body.elements.find((e) => e.id === "el-i");
    expect(icon.props.rotation_deg).toBe(15);

    // Second gesture — element still selected after gesture 1
    // (selection is independent of the ephemeral drag state).
    // Target ≈ 25° which snaps UP to 30°. tan(65°) = 2.145 so we
    // want dy_norm/dx_norm ≈ -2.145. dx_pix = 40, dy_pix = -54 →
    // dy_norm/dx_norm = (-54/500) / (40/800) = -2.160 → ~24.9°.
    putSpy.mockClear();
    const handle2 = screen.getByTestId("cad-icon-rotation-handle-el-i");
    fireEvent.mouseDown(handle2, { clientX: 400, clientY: 230,
                                   shiftKey: true });
    fireEvent.mouseMove(stage, { clientX: 440, clientY: 196,
                                 shiftKey: true });
    fireEvent.mouseUp(stage, { clientX: 440, clientY: 196,
                               shiftKey: true });
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    body = putSpy.mock.calls[putSpy.mock.calls.length - 1][1];
    icon = body.elements.find((e) => e.id === "el-i");
    expect(icon.props.rotation_deg).toBe(30);
  });
});
