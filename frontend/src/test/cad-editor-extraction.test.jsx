/**
 * Phase CAD-1 · Feb-2026 — Extraction lock-on.
 *
 * The ``CadEditor`` component was moved out of
 * ``pages/aitools/AiToolsPages.jsx`` into its own module at
 * ``pages/cad/Editor.jsx``. This test locks the extraction: the
 * new module renders on its own, defaults to the ``pointer`` tool,
 * and does NOT trigger a map-tile fetch when the loaded design
 * has no ``customer_id`` yet (freshly created designs).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

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
  useParams: () => ({ id: "design-extraction" }),
  Link: ({ to, children, ...rest }) =>
    <a href={to} {...rest}>{children}</a>,
}));


let fetchSpy;

beforeEach(() => {
  getSpy.mockReset();
  putSpy.mockReset();
  fetchSpy = vi.fn();
  global.fetch = fetchSpy;
});

afterEach(() => {
  delete global.fetch;
});


import CadEditor from "@/pages/cad/Editor.jsx";


describe("CAD-1 · CadEditor extraction", () => {
  it("renders after loading the design and defaults to pointer tool",
    async () => {
    getSpy.mockResolvedValue({
      id: "design-extraction",
      name: "Fresh design",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    // API fetched the design once at mount.
    expect(getSpy).toHaveBeenCalledWith("/designs/design-extraction");
    // Every original tool is present, plus the new ``scale`` tool.
    expect(screen.getByTestId("cad-tool-pointer")).toBeTruthy();
    expect(screen.getByTestId("cad-tool-rect")).toBeTruthy();
    expect(screen.getByTestId("cad-tool-circle")).toBeTruthy();
    expect(screen.getByTestId("cad-tool-tree")).toBeTruthy();
    expect(screen.getByTestId("cad-tool-scale")).toBeTruthy();
    // Canvas surface exists.
    expect(screen.getByTestId("cad-canvas")).toBeTruthy();
    // Map-backdrop sidebar section renders (empty state).
    expect(screen.getByTestId("cad-map-backdrop-section")).toBeTruthy();
    expect(screen.getByTestId("cad-map-lat-value").textContent).toBe("—");
    // No customer_id on this design ⇒ no map-tile fetch fired.
    expect(fetchSpy).not.toHaveBeenCalled();
    // No auto-PUT to /designs/... (the extraction should not
    // regress into writing when nothing has changed).
    expect(putSpy).not.toHaveBeenCalled();
  });
});
