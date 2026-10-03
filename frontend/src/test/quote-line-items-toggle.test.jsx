/**
 * Feb-2026 · A2 — K79 toggle also drives admin K71 line-items view.
 *
 * Contract:
 *   • Default admin view-mode "individual" on every mount (regardless
 *     of server customer_group_display).
 *   • K79 toggle flip syncs BOTH server-persisted
 *     customer_group_display AND client adminViewMode.
 *   • K71 editor stays mounted via CSS display:none when
 *     adminViewMode === "grouped" so unsaved edit state persists.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
  TOKEN_KEY: "token",
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin", id: "u-1" }, token: "t" }),
}));

import { api } from "@/api";
import QuoteInvoiceDetail from "@/pages/quotes/QuoteInvoiceDetail";

const CATS = [
  { id: "cat-pool",      name: "Pool Service" },
  { id: "cat-landscape", name: "Landscape" },
];

function makeDoc(overrides = {}) {
  return {
    id: "q-toggle-1",
    doc_type: "quote",
    status: "sent",
    decision: null,
    title: "Test Quote",
    customer_id: "c-1",
    customer_name: "Jane Customer",
    total: 370,
    amount_paid: 0,
    payment_status: "unpaid",
    tax_rate: 0,
    customer_group_display: true,   // server says grouped
    customer_group_descriptions: {},
    recipient_type: "customer",
    recipient_id: null,
    line_items: [
      { description: "Weekly service", quantity: 2, unit_price: 100,
        category: "service", service_category_id: "cat-pool" },
      { description: "Chlorine refill", quantity: 1, unit_price: 50,
        category: "service", service_category_id: "cat-pool" },
      { description: "Lawn mow", quantity: 3, unit_price: 40,
        category: "service", service_category_id: "cat-landscape" },
    ],
    converted_invoice_id: null,
    tenant_id: "t-1",
    ...overrides,
  };
}

function mountDetail(doc) {
  api.get.mockReset(); api.put.mockReset();
  api.put.mockResolvedValue({});
  api.get.mockImplementation(async (path) => {
    if (path.startsWith(`/quotes/${doc.id}`)
        && !path.includes("/signature")
        && !path.includes("/versions")
        && !path.includes("/edit-history")) {
      return doc;
    }
    if (path.startsWith("/service-categories")) return { items: CATS };
    if (path.startsWith("/settings/terms")) {
      return { default_invoice_terms: "", default_quote_terms: "" };
    }
    if (path.includes("/signature")) return { signed: false };
    if (path.includes("/versions")) return { total: 0 };
    return {};
  });
  return render(
    <MemoryRouter initialEntries={[`/quotes/${doc.id}`]}>
      <Routes>
        <Route path="/quotes/:id"
          element={<QuoteInvoiceDetail _docType="quote" />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("A2 · K79 toggle drives admin K71 view-mode", () => {
  it("default view-mode = 'individual' on mount (even if server says grouped=true)", async () => {
    mountDetail(makeDoc({ customer_group_display: true }));
    const wrap = await waitFor(
      () => screen.getByTestId("quote-line-items-view-mode"),
    );
    expect(wrap).toHaveAttribute("data-view-mode", "individual");
    expect(screen.queryByTestId("quote-line-items-grouped-table"))
      .toBeNull();
  });

  it("new testid 'quote-line-items-view-toggle' is present on the toggle control", async () => {
    mountDetail(makeDoc());
    await waitFor(
      () => screen.getByTestId("quote-line-items-view-toggle"),
    );
  });

  it("legacy 'k79-grouped-toggle' testid is preserved", async () => {
    mountDetail(makeDoc());
    await waitFor(() => screen.getByTestId("k79-grouped-toggle"));
  });

  it("flipping toggle twice (off→on) renders grouped rollup with ≥2 category rows", async () => {
    mountDetail(makeDoc());
    const toggle = await waitFor(
      () => screen.getByTestId("k79-grouped-toggle"),
    );
    const wrap = screen.getByTestId("quote-line-items-view-mode");
    expect(wrap).toHaveAttribute("data-view-mode", "individual");

    // Server starts grouped=true. First click → nextValue=false
    // (admin stays individual). Second click → nextValue=true
    // (admin flips to grouped).
    await act(async () => { fireEvent.click(toggle); });
    await act(async () => { fireEvent.click(toggle); });

    await waitFor(() => {
      expect(wrap).toHaveAttribute("data-view-mode", "grouped");
    });
    expect(screen.getByTestId("quote-line-items-grouped-table"))
      .toBeInTheDocument();
    const groupRows = screen.getAllByTestId(/^quote-line-items-group-/);
    expect(groupRows.length).toBeGreaterThanOrEqual(2);
  });

  it("flipping back lands on 'individual' with K71 wrapper visible and rollup gone", async () => {
    mountDetail(makeDoc());
    const toggle = await waitFor(
      () => screen.getByTestId("k79-grouped-toggle"),
    );
    const wrap = screen.getByTestId("quote-line-items-view-mode");

    await act(async () => { fireEvent.click(toggle); });  // → false
    await act(async () => { fireEvent.click(toggle); });  // → true (grouped)
    await waitFor(() => {
      expect(wrap).toHaveAttribute("data-view-mode", "grouped");
    });
    await act(async () => { fireEvent.click(toggle); });  // → false (individual)
    await waitFor(() => {
      expect(wrap).toHaveAttribute("data-view-mode", "individual");
    });
    expect(screen.queryByTestId("quote-line-items-grouped-table"))
      .toBeNull();
    // K71 individual wrapper must be mounted (display block).
    const indivWrap = screen.getByTestId(
      "quote-line-items-individual-wrapper",
    );
    expect(indivWrap).toBeInTheDocument();
    // display: block (or empty — not display:none)
    expect(indivWrap.style.display).not.toBe("none");
  });

  it("edit-dirty preservation — K71 row-edit state survives a flip to grouped and back", async () => {
    mountDetail(makeDoc());
    // Wait for K71 to render row 0, then click its edit button.
    const editBtn = await waitFor(
      () => screen.getByTestId("k71-edit-btn-0"),
      { timeout: 3000 },
    );
    await act(async () => { fireEvent.click(editBtn); });
    // Row 0 is now in edit mode — ``k71-row-edit-0`` is in the DOM.
    const editRow = await waitFor(
      () => screen.getByTestId("k71-row-edit-0"),
    );
    expect(editRow).toBeInTheDocument();

    // Flip to grouped (2 clicks per sync pattern).
    const toggle = screen.getByTestId("k79-grouped-toggle");
    await act(async () => { fireEvent.click(toggle); });
    await act(async () => { fireEvent.click(toggle); });
    const wrap = screen.getByTestId("quote-line-items-view-mode");
    await waitFor(() => {
      expect(wrap).toHaveAttribute("data-view-mode", "grouped");
    });

    // K71 individual wrapper is hidden but STILL MOUNTED. The edit
    // form inside should still exist in the DOM.
    const indivWrap = screen.getByTestId(
      "quote-line-items-individual-wrapper",
    );
    expect(indivWrap.style.display).toBe("none");
    // Edit row must still be in the DOM (not unmounted).
    expect(screen.getByTestId("k71-row-edit-0")).toBeInTheDocument();

    // Flip back to individual.
    await act(async () => { fireEvent.click(toggle); });
    await waitFor(() => {
      expect(wrap).toHaveAttribute("data-view-mode", "individual");
    });

    // Edit row still here = K71 state preserved across the flip.
    expect(screen.getByTestId("k71-row-edit-0")).toBeInTheDocument();
  });
});
