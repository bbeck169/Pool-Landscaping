/**
 * TD-cad-phase1 · Oct-2026 — vitest suite for GAP-A SitePlansAside
 * + GAP-F "Download JSON" button in CAD Editor.
 *
 * §1 fetch by property_id → correct query shape
 * §2 fetch by quote_id → correct query shape
 * §3 empty state renders when response is []
 * §4 thumbnail renders when design.thumbnail is set
 * §5 thumbnail placeholder when design.thumbnail is null
 * §6 "+ New site plan" href has property_id= (property mode)
 * §7 "+ New site plan" href has quote_id= (quote mode)
 * §8 customer_id forwarded in new-plan href when provided
 * §9 Editor Download JSON button present (source-regex lock)
 * §10 Download JSON filename pattern lock (source-regex)
 * §11 Editor byte-identical safeguard — all pre-existing CAD testids
 *     (cad-save, cad-name, cad-editor-page, cad-undo-btn) remain in
 *     the source (regression lock).
 */
import React from "react";
import fs from "fs";
import path from "path";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("@/api", () => ({
  api: { get: apiGet, post: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));
vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#f6f6f6",
    onSurface: "#111", onSurfaceSecondary: "#444",
    muted: "#888", border: "#ddd", brand: "#06c",
  },
}));

import SitePlansAside from "@/components/cad/SitePlansAside";

const EDITOR_SRC = fs.readFileSync(
  path.resolve(__dirname, "..", "pages", "cad", "Editor.jsx"), "utf8",
);


function _mount(mode, id, customerId) {
  return render(
    <MemoryRouter>
      <SitePlansAside mode={mode} id={id} customerId={customerId} />
    </MemoryRouter>,
  );
}


describe("TD-cad-phase1 · SitePlansAside · GAP-A FE widgets", () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiGet.mockResolvedValue([]);
  });


  // §1
  it("property mode fetches with ?property_id=<id>", async () => {
    _mount("property", "prop-1");
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    expect(apiGet.mock.calls[0][0]).toBe("/designs?property_id=prop-1");
  });

  // §2
  it("quote mode fetches with ?quote_id=<id>", async () => {
    _mount("quote", "quote-X");
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    expect(apiGet.mock.calls[0][0]).toBe("/designs?quote_id=quote-X");
  });

  // §3
  it("renders empty state when no designs attached", async () => {
    apiGet.mockResolvedValue([]);
    _mount("property", "prop-1");
    expect(
      await screen.findByTestId("site-plans-empty-property")
    ).toBeTruthy();
  });

  // §4
  it("renders thumbnail when design.thumbnail is set", async () => {
    apiGet.mockResolvedValue([
      { id: "d-1", name: "Pool plan", thumbnail: "data:image/png;base64,xyz",
          updated_at: "2026-10-22T10:00:00Z" },
    ]);
    _mount("property", "prop-1");
    const thumb = await screen.findByTestId("site-plans-thumb-d-1");
    expect(thumb.getAttribute("src")).toBe("data:image/png;base64,xyz");
  });

  // §5
  it("renders thumbnail placeholder when design.thumbnail is null", async () => {
    apiGet.mockResolvedValue([
      { id: "d-2", name: "Plan 2", thumbnail: null,
          updated_at: "2026-10-22T10:00:00Z" },
    ]);
    _mount("quote", "q-1");
    expect(await screen.findByTestId("site-plans-thumb-placeholder-d-2"))
      .toBeTruthy();
  });

  // §6
  it("'+ New site plan' href carries property_id in property mode", async () => {
    _mount("property", "prop-1");
    const link = await screen.findByTestId("site-plans-new-property");
    expect(link.getAttribute("href")).toContain("property_id=prop-1");
  });

  // §7
  it("'+ New site plan' href carries quote_id in quote mode", async () => {
    _mount("quote", "quote-1");
    const link = await screen.findByTestId("site-plans-new-quote");
    expect(link.getAttribute("href")).toContain("quote_id=quote-1");
  });

  // §8
  it("customer_id forwarded in new-plan href when provided", async () => {
    _mount("property", "prop-1", "cust-abc");
    const link = await screen.findByTestId("site-plans-new-property");
    expect(link.getAttribute("href")).toContain("customer_id=cust-abc");
  });

  // §9
  it("Editor source contains cad-download-json testid (GAP-F)", () => {
    expect(EDITOR_SRC).toContain(`data-testid="cad-download-json"`);
  });

  // §10
  it("Editor Download JSON filename pattern lock", () => {
    expect(EDITOR_SRC).toMatch(
      /a\.download\s*=\s*`cad_design_\$\{design\.id\s*\|\|\s*id\}_\$\{ts\}\.json`/
    );
    expect(EDITOR_SRC).toMatch(
      /new Blob\(\[payload\],\s*\{\s*type:\s*"application\/json"\s*\}\)/
    );
  });

  // §11
  it("Editor regression — pre-existing testids all preserved byte-identical", () => {
    const must = [
      "cad-editor-page",     // page container
      "cad-name",            // design name input
      "cad-save",            // Save button
      "cad-undo-btn",        // undo stack
      "cad-paver-finish",    // paver tool finish
      "cad-wall-finish",     // wall tool finish
      "cad-curve-finish",    // curve tool finish
      "cad-line-status",     // line tool status
      "cad-tape-persist-checkbox",  // tape measure persist
      "cad-mobile-guard",    // mobile guard
    ];
    for (const id of must) {
      expect(EDITOR_SRC).toContain(`data-testid="${id}"`);
    }
  });
});
