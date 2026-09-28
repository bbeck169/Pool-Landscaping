/**
 * Phase CAD-3 · Feb-2026 — Site Plan PDF button + attachments strip.
 *
 * Locks:
 *   1. Button renders with ``cad-generate-site-plan-pdf`` testid,
 *      and empty state ("No PDFs generated yet") renders.
 *   2. Click fires ``POST /cad/designs/${id}/site-plan-pdf`` (via
 *      ``api.post``), shows the loading label, then on success a
 *      new ``cad-attachment-<media_id>`` entry appears in the
 *      attachments strip.
 *   3. Failure surfaces a toast — no attachment strip growth.
 *   4. Button is disabled when the design has no ``customer_id``.
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
  useParams: () => ({ id: "design-siteplan" }),
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


describe("CAD-3 · Site Plan PDF sidebar + attachments strip", () => {
  it("renders the button + empty state, disables when no customer",
    async () => {
    getSpy.mockResolvedValue({
      id: "design-siteplan", name: "No customer",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
      // NO customer_id.
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    const btn = screen.getByTestId("cad-generate-site-plan-pdf");
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(true);
    expect(screen.getByTestId("cad-attachments-empty")).toBeTruthy();
  });

  it("click POSTs /cad/designs/{id}/site-plan-pdf, updates the "
     + "attachments strip on success", async () => {
    getSpy.mockResolvedValue({
      id: "design-siteplan", name: "Ready",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
      customer_id: "cust-99",
      media_attachments: [],
    });
    postSpy.mockResolvedValue({
      media_id: "media-abc123",
      media_url: "/api/uploads/design_pdfs/tenant-a/media-abc123.pdf",
      filename: "site-plan-ready-2026-02-20.pdf",
      pages: 2,
      size_bytes: 12345,
      generated_at: "2026-02-20T10:00:00.000Z",
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    const btn = screen.getByTestId("cad-generate-site-plan-pdf");
    expect(btn.disabled).toBe(false);
    // Empty state visible before generation.
    expect(screen.getByTestId("cad-attachments-empty")).toBeTruthy();

    fireEvent.click(btn);
    // POST fired with the correct path + empty body.
    await waitFor(() => expect(postSpy).toHaveBeenCalled());
    const [postPath, postBody] = postSpy.mock.calls[0];
    expect(postPath).toBe("/cad/designs/design-siteplan/site-plan-pdf");
    expect(postBody).toEqual({});

    // Attachment row appears; empty state disappears.
    await waitFor(() =>
      expect(screen.queryByTestId("cad-attachment-media-abc123")).toBeTruthy(),
    );
    expect(screen.queryByTestId("cad-attachments-empty")).toBeNull();
    const row = screen.getByTestId("cad-attachment-media-abc123");
    expect(row.getAttribute("href"))
      .toBe("/api/uploads/design_pdfs/tenant-a/media-abc123.pdf");
    expect(row.getAttribute("target")).toBe("_blank");
    expect(row.textContent).toContain("site-plan-ready-2026-02-20.pdf");
    // 12345 bytes ≈ 12 KB.
    expect(row.textContent).toContain("12 KB");
  });

  it("failure keeps the attachments strip empty + toast surfaces",
    async () => {
    getSpy.mockResolvedValue({
      id: "design-siteplan", name: "Boom",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
      customer_id: "cust-99",
      media_attachments: [],
    });
    const err = new Error("server exploded");
    err.body = { detail: { error_code: "site_plan_render_failed" } };
    postSpy.mockRejectedValue(err);
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("cad-generate-site-plan-pdf"));
    await waitFor(() => expect(postSpy).toHaveBeenCalled());
    // Toast surfaced.
    await waitFor(() =>
      expect(screen.queryByTestId("ai-tool-toast")).toBeTruthy(),
    );
    expect(screen.getByTestId("ai-tool-toast").textContent)
      .toContain("site_plan_render_failed");
    // Attachments strip stays empty (no rows added).
    expect(screen.getByTestId("cad-attachments-empty")).toBeTruthy();
  });

  it("pre-existing media_attachments render on mount", async () => {
    getSpy.mockResolvedValue({
      id: "design-siteplan", name: "Prior",
      canvas_w_ft: 60, canvas_h_ft: 40,
      elements: [], boundary: [],
      customer_id: "cust-99",
      media_attachments: [
        { id: "old-1", kind: "site_plan_pdf",
          filename: "site-plan-prior-2026-02-10.pdf",
          url: "/api/uploads/design_pdfs/tenant-a/old-1.pdf",
          size_bytes: 8000,
          generated_at: "2026-02-10T09:00:00.000Z" },
      ],
    });
    render(<CadEditor />);
    await waitFor(() =>
      expect(screen.queryByTestId("cad-editor-page")).toBeTruthy(),
    );
    expect(screen.getByTestId("cad-attachment-old-1")).toBeTruthy();
    // No empty state when at least one attachment exists.
    expect(screen.queryByTestId("cad-attachments-empty")).toBeNull();
  });
});
