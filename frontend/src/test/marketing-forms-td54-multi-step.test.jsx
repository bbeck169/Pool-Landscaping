/**
 * TD-54 · Feb-2026 — Multi-step forms. Phase 4 Commit 2.
 *
 * Covers (14 cases):
 *
 * Admin canvas (6):
 *   1. ``page_break`` palette button exists with its FIELD_TYPE_LABELS
 *      operator-facing label.
 *   2. Adding ``page_break`` via the palette button appends a row of
 *      type=page_break.
 *   3. The ``page_break`` row renders a dashed-divider style (not the
 *      solid border used by every other row).
 *   4. The ``page_break`` row shows a Page title (optional) input
 *      instead of the Label text input / the Rich-text section
 *      heading editor.
 *   5. The ``page_break`` row does NOT show the Required toggle
 *      (layout-exempt — same contract as ``section``).
 *   6. ``LAYOUT_TYPES`` set includes BOTH ``section`` and
 *      ``page_break``.
 *
 * Widget bundle (8) — source-parse the vanilla JS, same strategy as
 * marketing-forms-td52-palette-expansion.test.jsx. Full DOM mounting
 * for the paginator is covered by the phase4-widget-parity suite.
 *   7. Widget renders a zero-footprint marker for ``page_break``
 *      rows (``display:none`` + ``data-page-break-index`` attr).
 *   8. Widget computes ``pageOfField`` + ``pageTitles`` by walking
 *      the fields list once up front.
 *   9. Widget's ``applyVisibility`` combines ``show_if`` AND
 *      ``pageOfField === currentPage`` for the per-row display
 *      decision.
 *  10. Paginator chrome is ONLY appended when ``pageCount > 1`` —
 *      legacy single-page forms remain byte-identical.
 *  11. Prev button + Next button + Progress label all carry
 *      Playwright-friendly data-testids.
 *  12. ``validateCurrentPage`` checks ``input.required`` +
 *      ``checkValidity()`` on inputs within the current page's rows
 *      before advancing (and short-circuits to true when every input
 *      on the current page is non-required / valid).
 *  13. ``applyPaginatorChrome`` shows Submit only on the last page
 *      (``onLastPage`` branch) and shows Next otherwise.
 *  14. show_if evaluator still runs on EVERY input event, not just
 *      on page change — the ``form.addEventListener("input" /
 *      "change", applyVisibility)`` hooks are unchanged.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import fs from "fs";
import path from "path";


const _mocks = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => _mocks.get(...a),
    post: (...a) => _mocks.post(...a),
    patch: (...a) => _mocks.patch(...a),
    del: (...a) => _mocks.del(...a),
  },
}));

vi.mock("@/components/ui/confirm-dialog", () => ({
  mustConfirm: vi.fn(async () => true),
}));
vi.mock("@/components/formBuilder/ThemePanel", () => ({
  __esModule: true, default: () => <div data-testid="stub-theme-panel" />,
}));
vi.mock("@/components/formBuilder/HeroEditor", () => ({
  __esModule: true, default: () => <div data-testid="stub-hero" />,
}));
vi.mock("@/components/formBuilder/RichTextField", () => ({
  __esModule: true,
  default: ({ value, onChange, testid }) => (
    <input data-testid={testid} value={value || ""}
             onChange={(e) => onChange(e.target.value)} />
  ),
}));
vi.mock("@/components/common/AddressAutocomplete", () => ({
  __esModule: true, default: () => <div data-testid="stub-address" />,
}));

import MarketingFormsPage from "@/pages/marketing/MarketingFormsPage";


const _SAVED_FORM = {
  id: "frm_td54",
  tenant_id: "t1",
  slug: "frm-td54",
  name: "TD-54 multi-step form",
  version: 1,
  submission_count: 0,
  active: true,
  fields: [
    { id: "f1", name: "existing", type: "text", label: "Existing", required: false },
  ],
  submit_button_label: "Send",
  success_message: "Thanks!",
  submit_config: {
    creates: "lead", admin_bell: true,
    confirmation_email_template_id: null,
    drip_sequence_id: null,
  },
  theme: {}, hero: {},
};


function _resetMocks() {
  _mocks.get.mockReset(); _mocks.post.mockReset();
  _mocks.patch.mockReset(); _mocks.del.mockReset();
  _mocks.get.mockImplementation((p) => {
    if (p === "/admin/forms") return Promise.resolve([_SAVED_FORM]);
    if (p === "/marketing/templates") return Promise.resolve([]);
    if (p === "/marketing/sequences") return Promise.resolve([]);
    if (p && p.startsWith("/admin/forms/frm_td54")) return Promise.resolve(_SAVED_FORM);
    return Promise.resolve([]);
  });
  _mocks.patch.mockResolvedValue({ ..._SAVED_FORM });
}


async function _openEditor() {
  render(<MarketingFormsPage />);
  await screen.findByText("TD-54 multi-step form");
  fireEvent.click(screen.getByText("TD-54 multi-step form"));
  return await screen.findByTestId("form-save-btn");
}


// ──────────────────────────────────────────────────────────────────
// Admin canvas
// ──────────────────────────────────────────────────────────────────
describe("MarketingFormsPage · TD-54 page_break admin canvas", () => {
  beforeEach(_resetMocks);
  afterEach(() => cleanup());

  it("palette button for page_break exists with operator-facing label", async () => {
    await _openEditor();
    const btn = screen.getByTestId("form-field-palette-page_break");
    expect(btn).toBeTruthy();
    expect(btn.textContent).toMatch(/Page break/i);
  });

  it("clicking the palette button appends a page_break row", async () => {
    await _openEditor();
    fireEvent.click(screen.getByTestId("form-field-palette-page_break"));
    await waitFor(() => {
      const row = document.querySelector(
        '[data-testid^="form-field-"][data-field-type="page_break"]',
      );
      expect(row).toBeTruthy();
    });
  });

  it("page_break row renders a dashed divider style (visual boundary indicator)", async () => {
    await _openEditor();
    fireEvent.click(screen.getByTestId("form-field-palette-page_break"));
    await waitFor(() => {
      const row = document.querySelector(
        '[data-field-type="page_break"]',
      );
      expect(row).toBeTruthy();
      // Dashed border — distinct from the solid ``1px solid`` on
      // non-layout rows.
      expect(row.getAttribute("style") || "").toMatch(/dashed/i);
    });
  });

  it("page_break row exposes a Page title input (not RichTextField, not Label)", async () => {
    await _openEditor();
    fireEvent.click(screen.getByTestId("form-field-palette-page_break"));
    await waitFor(() => {
      const inputs = document.querySelectorAll(
        '[data-testid^="form-field-page-title-"]',
      );
      expect(inputs.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("page_break row does NOT render the Required toggle (layout-exempt)", async () => {
    await _openEditor();
    fireEvent.click(screen.getByTestId("form-field-palette-page_break"));
    await waitFor(() => {
      // The newly-added page_break row is the last form-field-* row.
      const rows = document.querySelectorAll('[data-field-type="page_break"]');
      expect(rows.length).toBeGreaterThan(0);
      // Grab the LAST (newest) page_break row.
      const row = rows[rows.length - 1];
      // Required toggle testid uses the row index; the required
      // checkbox is a child of the row only when non-layout.
      const requiredToggle = row.querySelector(
        'input[data-testid^="form-field-required-"]',
      );
      expect(requiredToggle).toBeNull();
    });
  });

  it("LAYOUT_TYPES source-parse includes section + page_break", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/marketing/MarketingFormsPage.jsx"),
      "utf8",
    );
    // Single-line Set declaration; two literal strings.
    const match = src.match(
      /const LAYOUT_TYPES = new Set\(\[([^\]]+)\]\)/,
    );
    expect(match).toBeTruthy();
    expect(match[1]).toContain('"section"');
    expect(match[1]).toContain('"page_break"');
  });
});


// ──────────────────────────────────────────────────────────────────
// Widget bundle — vanilla JS source parse
// ──────────────────────────────────────────────────────────────────
describe("widget bundle · TD-54 paginator", () => {
  const WIDGET = fs.readFileSync(
    path.resolve(__dirname, "../../public/widget/form.js"),
    "utf8",
  );

  it("renders a zero-footprint marker for page_break rows", () => {
    expect(WIDGET).toMatch(/f\.type === "page_break"/);
    // The page_break branch returns a hidden ``<div>`` with the
    // data-page-break-index attribute. Rather than regex-slicing
    // the function (which is sensitive to brace matching), just
    // locate the branch and assert both markers appear in the
    // surrounding ~400 characters of source.
    const start = WIDGET.indexOf('f.type === "page_break"');
    expect(start).toBeGreaterThan(0);
    const slice = WIDGET.slice(start, start + 500);
    expect(slice.includes('display: "none"')).toBe(true);
    expect(slice.includes("page-break-index")).toBe(true);
  });

  it("computes pageOfField + pageTitles via a one-pass walk", () => {
    // Must declare both maps + walk fields once.
    expect(WIDGET.includes("var pageOfField = {}")).toBe(true);
    expect(WIDGET.includes("var pageTitles = ")).toBe(true);
    expect(WIDGET).toMatch(/fields\.forEach\(function \(f\) \{[\s\S]*?page_break[\s\S]*?pageOfField\[f\.id\] = _curPage/);
  });

  it("applyVisibility combines show_if AND currentPage for each row", () => {
    expect(WIDGET.includes("showIfVisible && onCurrentPage")).toBe(true);
    expect(WIDGET.includes("pageOfField[f.id] === currentPage")).toBe(true);
  });

  it("paginator chrome only renders when pageCount > 1", () => {
    expect(WIDGET).toMatch(/if \(pageCount > 1\) \{\s*paginatorBar/);
    // And the appendChild of the paginator bar is gated by the
    // same condition at the end of renderForm.
    expect(WIDGET).toMatch(/if \(pageCount > 1\) \{[\s\S]*?prevBtn\.addEventListener/);
  });

  it("Prev / Next / Progress testids are stable for Playwright", () => {
    expect(WIDGET.includes('"form-widget-paginator-prev"')).toBe(true);
    expect(WIDGET.includes('"form-widget-paginator-next"')).toBe(true);
    expect(WIDGET.includes('"form-widget-paginator-progress"')).toBe(true);
    expect(WIDGET.includes('"form-widget-paginator"')).toBe(true);
  });

  it("validateCurrentPage blocks Next on invalid required inputs", () => {
    expect(WIDGET.includes("function validateCurrentPage()")).toBe(true);
    expect(WIDGET.includes("input.required && !input.checkValidity()")).toBe(true);
    // Only scans rows on the current page.
    expect(WIDGET.includes("pageOfField[fid] !== currentPage")).toBe(true);
  });

  it("applyPaginatorChrome shows Submit only on the last page", () => {
    expect(WIDGET.includes("onLastPage")).toBe(true);
    expect(WIDGET).toMatch(
      /submitBtn\.style\.display = onLastPage \? "" : "none"/,
    );
    expect(WIDGET).toMatch(
      /nextBtn\.style\.display = onLastPage \? "none" : ""/,
    );
    // Progress label includes "Page N of M" semantics.
    expect(WIDGET.includes('"Page " + (currentPage + 1) + " of " + pageCount')).toBe(true);
  });

  it("show_if evaluator still runs on EVERY input / change event (unchanged by TD-54)", () => {
    expect(WIDGET.includes('form.addEventListener("input", applyVisibility)')).toBe(true);
    expect(WIDGET.includes('form.addEventListener("change", applyVisibility)')).toBe(true);
  });
});
