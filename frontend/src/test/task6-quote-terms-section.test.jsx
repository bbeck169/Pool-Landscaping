/**
 * Feb-2026 · Task 6 — Quote/Estimate Terms & Conditions section.
 *
 * Vitest coverage:
 *   1. `DocTermsSection` — renders heading + body sub-testids when
 *      terms populated; renders nothing when empty.
 *   2. `TermsSettings` (settings page) exposes the new
 *      `tenant-default-quote-terms-editor` +
 *      `tenant-default-quote-terms-save-btn` testids and enforces
 *      the 5000-char cap via ``maxLength``.
 *   3. Character-count indicator on the tenant settings editor
 *      reflects the current input length.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { getSpy, putSpy, postSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(), putSpy: vi.fn(), postSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get:  (...a) => getSpy(...a),
    put:  (...a) => putSpy(...a),
    post: (...a) => postSpy(...a),
  },
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  };
});

vi.mock("@/components/ui/confirm-dialog", () => ({
  mustConfirm: vi.fn(() => Promise.resolve(true)),
}));

import DocTermsSection from "@/components/documents/DocTermsSection";
import TermsSettings from "@/pages/settings/Terms";


afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});


// ─── 1. DocTermsSection heading + body sub-testids ─────────────
describe("DocTermsSection · heading/body sub-testids", () => {
  it("renders heading + body wrappers when terms populated", () => {
    render(
      <DocTermsSection
        terms={"Line 1\n\nLine 2 body"}
        testidPrefix="estimate"
      />,
    );
    expect(screen.getByTestId("estimate-terms-section")).toBeTruthy();
    expect(screen.getByTestId("estimate-terms-heading")).toBeTruthy();
    expect(screen.getByTestId("estimate-terms-body").textContent)
      .toMatch(/Line 1/);
    expect(screen.getByTestId("estimate-terms-body").textContent)
      .toMatch(/Line 2 body/);
  });

  it("renders nothing when terms is empty", () => {
    const { container } = render(<DocTermsSection terms="" testidPrefix="estimate" />);
    expect(container.textContent).toBe("");
  });

  it("renders nothing when terms is whitespace-only", () => {
    const { container } = render(<DocTermsSection terms={"   \n\n  "} testidPrefix="estimate" />);
    expect(container.textContent).toBe("");
  });
});


// ─── 2. Tenant Settings — new testids + char count ─────────────
describe("TermsSettings · tenant-default-quote-terms-editor testids", () => {
  beforeEach(() => {
    getSpy.mockResolvedValue({
      default_quote_terms: "Existing quote defaults.",
      default_invoice_terms: "Existing invoice defaults.",
    });
    putSpy.mockResolvedValue({
      default_quote_terms: "Updated quote defaults.",
      default_invoice_terms: "Existing invoice defaults.",
    });
  });

  it("mounts with new testids and reflects loaded value", async () => {
    render(<MemoryRouter><TermsSettings /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-default-quote-terms-editor")).toBeTruthy(),
    );
    const editor = screen.getByTestId("tenant-default-quote-terms-editor");
    expect(editor.value).toBe("Existing quote defaults.");
    // The save button uses the new testid.
    expect(screen.getByTestId("tenant-default-quote-terms-save-btn")).toBeTruthy();
    // Character count reflects the initial value.
    const cc = screen.getByTestId("tenant-default-quote-terms-character-count");
    expect(cc.textContent).toMatch(/24 \/ 5000/);
  });

  it("enforces 5000-char cap via maxLength attribute", async () => {
    render(<MemoryRouter><TermsSettings /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-default-quote-terms-editor")).toBeTruthy(),
    );
    const editor = screen.getByTestId("tenant-default-quote-terms-editor");
    expect(editor.getAttribute("maxLength")).toBe("5000");
  });

  it("save button invokes PUT /settings/terms with edited payload", async () => {
    render(<MemoryRouter><TermsSettings /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-default-quote-terms-editor")).toBeTruthy(),
    );
    const editor = screen.getByTestId("tenant-default-quote-terms-editor");
    fireEvent.change(editor, { target: { value: "New tenant terms." } });
    // Char count updates live.
    expect(
      screen.getByTestId("tenant-default-quote-terms-character-count").textContent,
    ).toMatch(/17 \/ 5000/);
    fireEvent.click(screen.getByTestId("tenant-default-quote-terms-save-btn"));
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const [path, body] = putSpy.mock.calls[0];
    expect(path).toBe("/settings/terms");
    expect(body.default_quote_terms).toBe("New tenant terms.");
  });

  it("save empty-string PUT payload survives frontend (Defect 1)", async () => {
    // Regression guard: clearing the tenant default must reach the
    // backend as an EXPLICIT empty string, not stripped by the
    // component. Prior bug filtered out ``""`` before the PUT.
    render(<MemoryRouter><TermsSettings /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-default-quote-terms-editor")).toBeTruthy(),
    );
    const editor = screen.getByTestId("tenant-default-quote-terms-editor");
    fireEvent.change(editor, { target: { value: "" } });
    fireEvent.click(screen.getByTestId("tenant-default-quote-terms-save-btn"));
    await waitFor(() => expect(putSpy).toHaveBeenCalled());
    const [path, body] = putSpy.mock.calls[0];
    expect(path).toBe("/settings/terms");
    // Empty string reaches the API — NOT dropped, not null.
    expect(body).toHaveProperty("default_quote_terms");
    expect(body.default_quote_terms).toBe("");
  });
});
