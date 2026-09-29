/**
 * Phase CAD-3.5b · Feb-2026 — Realistic paver textures.
 *
 * Locks:
 *   1. Paver renders with ``fillPatternImage`` (data-fill-mode
 *      "pattern") when the material image loads.
 *   2. Material picker persists ``material_id`` in the save payload.
 *   3. Missing / failed texture falls back to flat fill
 *      (data-fill-mode "flat") without console spam.
 *   4. Newly-drawn pavers ship with a default ``material_id``.
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
  useParams: () => ({ id: "design-pv" }),
  Link: ({ to, children, ...rest }) =>
    <a href={to} {...rest}>{children}</a>,
}));


// Patched Image constructor — instances start fire-onload / fire-
// onerror manually via the ``__resolve()`` / ``__reject()`` helpers.
// Default behaviour: synchronously fire ``onload`` when ``src`` is
// assigned so the paver's `useEffect` transitions to the pattern
// path deterministically (jsdom has no real image loading).
let _imageMode = "load"; // "load" | "error" | "pending"

class _FakeImage {
  constructor() {
    this._src = null;
    this.onload = null;
    this.onerror = null;
  }
  set src(v) {
    this._src = v;
    // Fire on the next microtask so react state updates settle.
    Promise.resolve().then(() => {
      if (_imageMode === "load" && this.onload) this.onload();
      else if (_imageMode === "error" && this.onerror) this.onerror();
    });
  }
  get src() { return this._src; }
}


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
  _imageMode = "load";
  global.Image = _FakeImage;
  window.Image = _FakeImage;
});

afterEach(() => { delete global.fetch; });


import CadEditor from "@/pages/cad/Editor.jsx";


function _paverDesign(paverProps = {}) {
  return {
    id: "design-pv", name: "u",
    canvas_w_ft: 60, canvas_h_ft: 40,
    elements: [{
      id: "pv-1", type: "paver",
      coords: [
        { x: 0.2, y: 0.2 }, { x: 0.6, y: 0.2 },
        { x: 0.6, y: 0.6 }, { x: 0.2, y: 0.6 },
      ],
      props: { material_id: "travertine", ...paverProps },
      computed: { area_sqft: 400 },
    }],
    boundary: [],
  };
}


async function _mountWith(design) {
  getSpy.mockResolvedValue(design);
  render(<CadEditor />);
  await waitFor(() =>
    expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
  );
}


describe("CAD-3.5b · paver texture rendering", () => {
  it("renders with fillPatternImage when the material image loads",
    async () => {
      _imageMode = "load";
      await _mountWith(_paverDesign());
      const shape = screen.getByTestId("cad-shape-pv-1");
      await waitFor(() => {
        expect(shape.getAttribute("data-fill-mode")).toBe("pattern");
      });
      expect(shape.getAttribute("data-material-id")).toBe("travertine");
    });

  it("falls back to flat fill when the image fails to load",
    async () => {
      _imageMode = "error";
      await _mountWith(_paverDesign());
      const shape = screen.getByTestId("cad-shape-pv-1");
      await waitFor(() => {
        expect(shape.getAttribute("data-fill-mode")).toBe("flat");
      });
      // Material id still travels with the element even on the
      // fallback path so the export layer can render the legend.
      expect(shape.getAttribute("data-material-id")).toBe("travertine");
    });
});


describe("CAD-3.5b · paver material picker", () => {
  it("changing material persists material_id in the save payload",
    async () => {
      _imageMode = "load";
      await _mountWith(_paverDesign());
      fireEvent.click(screen.getByTestId("cad-shape-pv-1"));
      const select = await waitFor(() =>
        screen.getByTestId("cad-paver-material-select"),
      );
      putSpy.mockClear();
      fireEvent.change(select, { target: { value: "slate" } });
      await waitFor(() => expect(putSpy).toHaveBeenCalled());
      const body = putSpy.mock.calls[putSpy.mock.calls.length - 1][1];
      const pv = body.elements.find((el) => el.id === "pv-1");
      expect(pv.props.material_id).toBe("slate");
    });

  it("changing material is Undoable via the shared snapshot infra",
    async () => {
      _imageMode = "load";
      await _mountWith(_paverDesign());
      fireEvent.click(screen.getByTestId("cad-shape-pv-1"));
      const select = await waitFor(() =>
        screen.getByTestId("cad-paver-material-select"),
      );
      fireEvent.change(select, { target: { value: "flagstone" } });
      await waitFor(() => expect(putSpy).toHaveBeenCalled());
      putSpy.mockClear();
      fireEvent.click(screen.getByTestId("cad-undo-btn"));
      await waitFor(() => expect(putSpy).toHaveBeenCalled());
      const body = putSpy.mock.calls[putSpy.mock.calls.length - 1][1];
      const pv = body.elements.find((el) => el.id === "pv-1");
      expect(pv.props.material_id).toBe("travertine");
    });
});


describe("CAD-3.5b · new paver defaults", () => {
  it("newly-drawn paver has a material_id on creation", async () => {
    _imageMode = "load";
    await _mountWith({
      id: "design-pv", name: "u",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
    });
    fireEvent.click(screen.getByTestId("cad-tool-paver"));
    const stage = screen.getByTestId("cad-konva-stage");
    fireEvent.mouseDown(stage, { clientX: 100, clientY: 100 });
    fireEvent.mouseDown(stage, { clientX: 200, clientY: 100 });
    fireEvent.mouseDown(stage, { clientX: 200, clientY: 200 });
    fireEvent.click(screen.getByTestId("cad-paver-finish"));
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const body = putSpy.mock.calls[putSpy.mock.calls.length - 1][1];
    const pv = (body.elements || []).find((el) => el.type === "paver");
    expect(pv).toBeTruthy();
    // Default is the first material in the catalog.
    expect(pv.props.material_id).toBe("travertine");
  });
});
