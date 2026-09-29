/**
 * Phase CAD-3.5a · Feb-2026 — Manual dimension label override.
 *
 * Locks:
 *   1. Setting ``label_manual`` on a dimension element renders the
 *      literal string INSTEAD of the auto-computed length.
 *   2. An empty string in the input clears the override → the
 *      auto-computed label surfaces again.
 *   3. ``label_manual`` round-trips through the save payload
 *      (visible in the last PUT body).
 *   4. ``label_manual`` restored from a loaded design payload
 *      renders on the initial paint.
 *   5. Setting the override pushes a snapshot on the undo stack →
 *      undo removes the override.
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
  useParams: () => ({ id: "design-dim" }),
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


// A design whose only element is a persisted dimension line 10-ft
// wide (0.5 → 0.75 on x @ canvas_w_ft=40 → 10 ft → auto label
// ``"10' 0\""``).
function _designWithDimension({ label_manual = undefined } = {}) {
  const el = {
    id: "dim-1", type: "dimension",
    coords: [{ x: 0.25, y: 0.5 }, { x: 0.5, y: 0.5 }],
    props: { persist_dimension: true },
  };
  if (label_manual !== undefined) el.label_manual = label_manual;
  return {
    id: "design-dim", name: "d",
    canvas_w_ft: 40, canvas_h_ft: 20,
    elements: [el], boundary: [],
  };
}


async function _mountAndSelect() {
  render(<CadEditor />);
  await waitFor(() =>
    expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
  );
  // Click the dimension shape to select it → surfaces the props panel.
  fireEvent.click(screen.getByTestId("cad-shape-dim-1"));
  await waitFor(() =>
    expect(screen.queryByTestId("cad-dimension-props-section")).toBeTruthy(),
  );
}


describe("CAD-3.5a · manual dimension label override", () => {
  it("no override → renders the auto-computed length", async () => {
    getSpy.mockResolvedValue(_designWithDimension());
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    const glyph = screen.getByTestId("cad-shape-dim-1");
    expect(glyph.getAttribute("data-label-text")).toBe("10' 0\"");
    expect(glyph.getAttribute("data-label-source")).toBe("auto");
  });

  it("setting label_manual renders the literal instead", async () => {
    getSpy.mockResolvedValue(_designWithDimension());
    await _mountAndSelect();
    const input = screen.getByTestId("cad-dimension-label-manual-input");
    fireEvent.change(input, { target: { value: "≈ 3.3 m" } });
    // Component re-renders with the manual override.
    await waitFor(() => {
      const glyph = screen.getByTestId("cad-shape-dim-1");
      expect(glyph.getAttribute("data-label-text")).toBe("≈ 3.3 m");
      expect(glyph.getAttribute("data-label-source")).toBe("manual");
    });
  });

  it("empty string clears the override → auto-computed label returns",
    async () => {
      getSpy.mockResolvedValue(_designWithDimension({ label_manual: "hardcoded" }));
      await _mountAndSelect();
      // Confirm initial state honors the loaded override.
      expect(
        screen.getByTestId("cad-shape-dim-1").getAttribute("data-label-text"),
      ).toBe("hardcoded");
      const input = screen.getByTestId("cad-dimension-label-manual-input");
      fireEvent.change(input, { target: { value: "" } });
      await waitFor(() => {
        const glyph = screen.getByTestId("cad-shape-dim-1");
        expect(glyph.getAttribute("data-label-text")).toBe("10' 0\"");
        expect(glyph.getAttribute("data-label-source")).toBe("auto");
      });
    });

  it("label_manual is present in the save payload", async () => {
    getSpy.mockResolvedValue(_designWithDimension());
    await _mountAndSelect();
    const input = screen.getByTestId("cad-dimension-label-manual-input");
    fireEvent.change(input, { target: { value: "12'-6\" A" } });
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const body = putSpy.mock.calls[putSpy.mock.calls.length - 1][1];
    const dim = (body.elements || []).find((el) => el.id === "dim-1");
    expect(dim).toBeTruthy();
    expect(dim.label_manual).toBe("12'-6\" A");
  });

  it("label_manual restored from a loaded design renders on first paint",
    async () => {
      getSpy.mockResolvedValue(_designWithDimension({ label_manual: "N-S: 12ft" }));
      render(<CadEditor />);
      await waitFor(() =>
        expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
      );
      const glyph = screen.getByTestId("cad-shape-dim-1");
      expect(glyph.getAttribute("data-label-text")).toBe("N-S: 12ft");
      expect(glyph.getAttribute("data-label-source")).toBe("manual");
    });

  it("clearing empty string does NOT persist a bare empty-string override",
    async () => {
      getSpy.mockResolvedValue(_designWithDimension({ label_manual: "wipe-me" }));
      await _mountAndSelect();
      const input = screen.getByTestId("cad-dimension-label-manual-input");
      fireEvent.change(input, { target: { value: "" } });
      await waitFor(() => expect(putSpy).toHaveBeenCalled());
      const body = putSpy.mock.calls[putSpy.mock.calls.length - 1][1];
      const dim = (body.elements || []).find((el) => el.id === "dim-1");
      // Empty string coerces to ``undefined`` (property omitted) so
      // the JSON payload stays clean — no ``"label_manual": ""`` in
      // the persisted shape.
      expect(dim.label_manual).toBeUndefined();
    });

  it("undo removes the manual-override mutation", async () => {
    getSpy.mockResolvedValue(_designWithDimension());
    await _mountAndSelect();
    const input = screen.getByTestId("cad-dimension-label-manual-input");
    fireEvent.change(input, { target: { value: "override-A" } });
    await waitFor(() =>
      expect(screen.getByTestId("cad-shape-dim-1")
        .getAttribute("data-label-text")).toBe("override-A"),
    );
    // Undo the override.
    fireEvent.click(screen.getByTestId("cad-undo-btn"));
    await waitFor(() =>
      expect(screen.getByTestId("cad-shape-dim-1")
        .getAttribute("data-label-source")).toBe("auto"),
    );
  });
});
