/**
 * Phase CAD-2 · Feb-2026 — MARCO Designer sidebar.
 *
 * User types a prompt, hits Generate, mocked ``POST /cad/generate``
 * returns shapes + reasoning + warnings. Preview shapes render on
 * canvas (as data-attributed divs via the react-konva mock).
 * Accept commits shapes via PUT ``/designs/{id}``. Discard clears
 * the preview.
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
  useParams: () => ({ id: "design-marco" }),
  Link: ({ to, children, ...rest }) =>
    <a href={to} {...rest}>{children}</a>,
}));


beforeEach(() => {
  getSpy.mockReset(); putSpy.mockReset(); postSpy.mockReset();
  putSpy.mockResolvedValue({});
  global.fetch = vi.fn().mockResolvedValue({
    ok: false, status: 424,
    json: () => Promise.resolve({ detail: { error_code: "no" } }),
    headers: new Headers(),
  });
  global.URL.createObjectURL = vi.fn(() => "blob:noop");
  global.URL.revokeObjectURL = vi.fn();
});

afterEach(() => { delete global.fetch; });


import CadEditor from "@/pages/cad/Editor.jsx";


describe("CAD-2 · MARCO Designer sidebar", () => {
  it("Generate → preview renders → Accept commits shapes to design",
    async () => {
    getSpy.mockResolvedValue({
      id: "design-marco", name: "Marco test",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
    });
    postSpy.mockResolvedValue({
      generation_id: "gen-abc",
      shapes: [
        { type: "pool",
          coords: [{ x: 0.2, y: 0.3 }, { x: 0.5, y: 0.3 },
                   { x: 0.5, y: 0.6 }, { x: 0.2, y: 0.6 }],
          icon: null, label: "Pool 15x30" },
        { type: "icon", icon: "tree",
          coords: [{ x: 0.1, y: 0.1 }],
          label: null },
      ],
      reasoning: "Pool anchored south, shade tree north.",
      warnings: ["shape 0 extends beyond property boundary — clamped"],
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );

    const textarea = screen.getByTestId("cad-marco-textarea");
    fireEvent.change(textarea, { target: { value: "add a pool + shade tree" } });
    fireEvent.click(screen.getByTestId("cad-marco-generate"));

    await waitFor(() => expect(postSpy).toHaveBeenCalled());
    const [postPath, postBody] = postSpy.mock.calls[0];
    expect(postPath).toBe("/cad/generate");
    expect(postBody.prompt).toBe("add a pool + shade tree");
    expect(postBody.design_id).toBe("design-marco");

    // Reasoning + warnings surfaced.
    await waitFor(() =>
      expect(screen.queryByTestId("cad-marco-reasoning")).toBeTruthy(),
    );
    expect(screen.getByTestId("cad-marco-reasoning").textContent)
      .toContain("Pool anchored");
    expect(screen.getByTestId("cad-marco-warnings").textContent)
      .toContain("clamped");
    // Preview shapes rendered on-canvas.
    expect(screen.getByTestId("cad-preview-shape-0")).toBeTruthy();
    expect(screen.getByTestId("cad-preview-shape-1")).toBeTruthy();

    // Accept commits.
    fireEvent.click(screen.getByTestId("cad-marco-accept"));
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const [_p, putBody] = putSpy.mock.calls[putSpy.mock.calls.length - 1];
    const types = putBody.elements.map((e) => e.type);
    expect(types).toContain("pool");
    expect(types).toContain("icon");
    // Preview cleared post-accept.
    expect(screen.queryByTestId("cad-preview-shape-0")).toBeNull();
  });

  it("Discard clears the preview without committing", async () => {
    getSpy.mockResolvedValue({
      id: "design-marco", name: "Marco discard",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
    });
    postSpy.mockResolvedValue({
      generation_id: "gen-x",
      shapes: [{ type: "spa",
                  coords: [{ x: 0.4, y: 0.4 }, { x: 0.6, y: 0.4 },
                           { x: 0.6, y: 0.5 }, { x: 0.4, y: 0.5 }],
                  icon: null, label: "Spa" }],
      reasoning: "Spa.",
      warnings: [],
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("cad-marco-textarea"),
                      { target: { value: "spa please" } });
    fireEvent.click(screen.getByTestId("cad-marco-generate"));
    await waitFor(() =>
      expect(screen.queryByTestId("cad-preview-shape-0")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("cad-marco-discard"));
    expect(screen.queryByTestId("cad-preview-shape-0")).toBeNull();
    // No PUT was issued.
    expect(putSpy).not.toHaveBeenCalled();
  });
});
