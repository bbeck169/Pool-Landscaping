/**
 * Ticket JJ · Feb-2026 — strip-on-render regression lock for the
 * shared <InvoiceTable /> + its driver helper getInvoiceDisplayTitle.
 *
 * Covers: feeding the primitive a row whose line_items[0] has HTML
 * tags + entities in item_name / name / description + whose
 * invoice.title has HTML.  No tag or entity may surface in the
 * rendered title cell for any case.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import InvoiceTable from "@/components/invoices/InvoiceTable";

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}));

function mount(rows) {
  return render(
    <MemoryRouter>
      <InvoiceTable rows={rows} viewHref={(r) => `/invoices/${r.id}`} />
    </MemoryRouter>,
  );
}

const _row = (overrides = {}) => ({
  id: "inv-jj-1",
  invoice_number: "INV-001",
  invoice_date: "2026-02-20",
  total: 100,
  payment_status: "paid",
  status: "issued",
  ...overrides,
});

describe("Ticket JJ · <InvoiceTable /> strip-on-render", () => {
  it("item_name wrapped in <p> renders as plain text", () => {
    mount([_row({
      line_items: [{ item_name: "<p>Weekly Service</p>" }],
    })]);
    const cell = screen.getByTestId("inv-table-cell-title-inv-jj-1");
    expect(cell.textContent).toBe("Weekly Service");
    expect(cell.innerHTML).not.toContain("<p>");
  });

  it("name wrapped in <b> renders as plain text + entity decode", () => {
    mount([_row({
      line_items: [{ name: "<b>Rock &amp; Roll</b>" }],
    })]);
    const cell = screen.getByTestId("inv-table-cell-title-inv-jj-1");
    // textContent is the user-visible string — the entity was
    // decoded by stripHtmlToPlainText so the ``&`` is literal.
    expect(cell.textContent).toBe("Rock & Roll");
    // innerHTML carries the TAG-stripped form; React re-escapes the
    // literal ``&`` to ``&amp;`` on serialisation (safe — prevents
    // the cleaned text from being re-interpreted as HTML).  The
    // important lock is that the ``<b>`` TAG does NOT survive.
    expect(cell.innerHTML).not.toContain("<b>");
    expect(cell.innerHTML).not.toContain("</b>");
  });

  it("invoice.title with HTML (used when line_items has no item_name/name) is stripped too", () => {
    mount([_row({
      title: "<p>Monthly maintenance &amp; chem</p>",
      line_items: [{ description: "will be ignored at helper case 4" }],
    })]);
    const cell = screen.getByTestId("inv-table-cell-title-inv-jj-1");
    expect(cell.textContent).toBe("Monthly maintenance & chem");
    expect(cell.innerHTML).not.toContain("<p>");
  });

  it("description fallback (case 4) stripped + truncated", () => {
    mount([_row({
      line_items: [{
        description: "<p>A <b>very long</b> description that goes on and on and on and on and on and on past the 60-char threshold</p>",
      }],
    })]);
    const cell = screen.getByTestId("inv-table-cell-title-inv-jj-1");
    const text = cell.textContent;
    // No tags.
    expect(text).not.toContain("<");
    // Truncation ellipsis present (helper's 60-char trunc).
    expect(text).toMatch(/\u2026$/);
  });

  it("already-plain input unchanged (idempotent)", () => {
    mount([_row({
      line_items: [{ item_name: "Clean Service" }],
    })]);
    expect(
      screen.getByTestId("inv-table-cell-title-inv-jj-1").textContent,
    ).toBe("Clean Service");
  });

  it("empty line_items + plain invoice.title still works", () => {
    mount([_row({ title: "Plain Title", line_items: [] })]);
    expect(
      screen.getByTestId("inv-table-cell-title-inv-jj-1").textContent,
    ).toBe("Plain Title");
  });
});
