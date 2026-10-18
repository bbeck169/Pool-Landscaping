/**
 * TD-79 · Feb-2026 — Customer profile Overview tab invoice list.
 *
 * Coverage:
 *   1. Placement — the ``<CustomerInvoiceList>`` component is
 *      wired into ``CustomerDetail.jsx`` BETWEEN the
 *      ``cd-customer-name-secondary`` heading and the
 *      ``<PaymentMethodTiles>`` section (operator placement
 *      anchor: below the tab-nav red divider, above the
 *      payment/card section).
 *   2. Pure helper — ``_sortByCreatedDesc`` sorts newest first
 *      by ``created_at`` with ``id`` lex DESC as the
 *      deterministic tiebreak.
 *   3. Render matrix — fetches ``/quotes?doc_type=invoice`` with
 *      ``customer_id`` + ``limit=10``, renders the row table,
 *      shows "View all" only when ``total_count > 10``.
 *   4. Empty state — zero rows → no table, EmptyState visible.
 *   5. Row click → navigate to invoice detail.
 *   6. "View all" click → navigate to the main InvoicesList
 *      prefiltered by ``?customer_id=``.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";

import { _sortByCreatedDesc } from "../components/customers/CustomerInvoiceList";

const DETAIL_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/customers/CustomerDetail.jsx"),
  "utf-8",
);


// ────────────────────────────────────────────────────────────────
// 1. Placement — structural lock in CustomerDetail.jsx.
// ────────────────────────────────────────────────────────────────
describe("TD-79 · placement — CustomerInvoiceList between name heading + PaymentMethodTiles", () => {
  it("import of CustomerInvoiceList present", () => {
    expect(DETAIL_SRC).toMatch(
      /import\s+CustomerInvoiceList\s+from\s+["']@\/components\/customers\/CustomerInvoiceList["']/,
    );
  });

  it("CustomerInvoiceList render lands AFTER cd-customer-name-secondary and BEFORE PaymentMethodTiles", () => {
    const nameIdx = DETAIL_SRC.indexOf('data-testid="cd-customer-name-secondary"');
    const listIdx = DETAIL_SRC.indexOf("<CustomerInvoiceList");
    const paymentIdx = DETAIL_SRC.indexOf("<PaymentMethodTiles");
    expect(nameIdx).toBeGreaterThan(-1);
    expect(listIdx).toBeGreaterThan(nameIdx);
    expect(paymentIdx).toBeGreaterThan(listIdx);
  });

  it("CustomerInvoiceList is passed the customer's id", () => {
    expect(DETAIL_SRC).toMatch(
      /<CustomerInvoiceList\s+customerId=\{customer\.id\}\s*\/>/,
    );
  });
});


// ────────────────────────────────────────────────────────────────
// 2. Pure helper — sort order lock.
// ────────────────────────────────────────────────────────────────
describe("TD-79 · _sortByCreatedDesc", () => {
  it("sorts newest created_at first", () => {
    const out = _sortByCreatedDesc([
      { id: "a", created_at: "2026-01-01T10:00:00Z" },
      { id: "b", created_at: "2026-03-01T10:00:00Z" },
      { id: "c", created_at: "2026-02-01T10:00:00Z" },
    ]);
    expect(out.map((r) => r.id)).toEqual(["b", "c", "a"]);
  });

  it("ties on created_at break by id lex DESC", () => {
    const out = _sortByCreatedDesc([
      { id: "apple", created_at: "2026-01-01T10:00:00Z" },
      { id: "zebra", created_at: "2026-01-01T10:00:00Z" },
    ]);
    expect(out.map((r) => r.id)).toEqual(["zebra", "apple"]);
  });

  it("empty / null / undefined input returns an empty array", () => {
    expect(_sortByCreatedDesc(null)).toEqual([]);
    expect(_sortByCreatedDesc(undefined)).toEqual([]);
    expect(_sortByCreatedDesc([])).toEqual([]);
  });
});


// ────────────────────────────────────────────────────────────────
// 3-6. Rendered-DOM matrix.
// ────────────────────────────────────────────────────────────────
const { getSpy, navSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  navSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: { get: (...a) => getSpy(...a), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => navSpy,
}));

vi.mock("@/theme", () => {
  const base = {
    brand: "#0B4A6F", onBrand: "#FFFFFF", onSurface: "#111827",
    onSurfaceSecondary: "#6B7280", muted: "#6B7280", border: "#E5E7EB",
    divider: "#E5E7EB", surface: "#FFFFFF", surfaceSecondary: "#F8FAFC",
    success: "#059669", danger: "#B91C1C",
  };
  return { colors: base, money: (n) => `$${Number(n || 0).toFixed(2)}` };
});

vi.mock("@/components/ui-kit", async () => {
  const React = await import("react");
  return {
    Chip: ({ label }) => React.createElement(
      "span", { "data-testid": `chip-${label}` }, label,
    ),
    EmptyState: ({ title, hint }) => React.createElement(
      "div", { "data-testid": "empty-state" },
      React.createElement("div", null, title),
      React.createElement("div", null, hint),
    ),
    Skeleton: ({ style }) => React.createElement(
      "div", { "data-testid": "skeleton", style },
    ),
  };
});

vi.mock("@/lib/portalInvoiceTitle", () => ({
  resolvePortalInvoiceTitle: (r) => r?.title || "(untitled)",
}));

import CustomerInvoiceList from "@/components/customers/CustomerInvoiceList";


function _makeRows(n, overrides = {}) {
  const rows = [];
  for (let i = 0; i < n; i++) {
    rows.push({
      id: `inv-${String(i).padStart(3, "0")}`,
      invoice_number: `INV-${1000 + i}`,
      title: `Service ${i}`,
      total: 100 + i,
      due_date: "2026-03-01",
      payment_status: (i % 2 === 0) ? "paid" : "unpaid",
      created_at: `2026-02-${String(28 - i).padStart(2, "0")}T10:00:00Z`,
      ...overrides,
    });
  }
  return rows;
}


describe("TD-79 · CustomerInvoiceList render matrix", () => {
  beforeEach(() => { getSpy.mockReset(); navSpy.mockReset(); });
  afterEach(() => { cleanup(); });

  it("fetches /quotes with doc_type=invoice + customer_id + limit=10", async () => {
    getSpy.mockResolvedValue({ rows: [], total_count: 0, has_more: false });
    render(<CustomerInvoiceList customerId="cust-A" />);
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    const path = getSpy.mock.calls[0][0];
    expect(path).toContain("/quotes?");
    expect(path).toContain("doc_type=invoice");
    expect(path).toContain("customer_id=cust-A");
    expect(path).toContain("limit=10");
    expect(path).toContain("offset=0");
  });

  it("renders exactly 10 rows + 'View all' when total_count > 10", async () => {
    const rows = _makeRows(10);
    getSpy.mockResolvedValue({ rows, total_count: 25, has_more: true });
    render(<CustomerInvoiceList customerId="cust-A" />);
    await waitFor(() =>
      expect(screen.queryByTestId("cd-overview-invoices-table-wrap")).toBeTruthy()
    );
    for (let i = 0; i < 10; i++) {
      const id = `inv-${String(i).padStart(3, "0")}`;
      expect(screen.queryByTestId(`cd-overview-invoice-row-${id}`)).toBeTruthy();
    }
    expect(screen.queryByTestId("cd-overview-invoices-view-all")).toBeTruthy();
    expect(screen.queryByTestId("cd-overview-invoices-count").textContent).toBe("(25)");
  });

  it("renders all rows + NO 'View all' when total_count ≤ 10", async () => {
    const rows = _makeRows(7);
    getSpy.mockResolvedValue({ rows, total_count: 7, has_more: false });
    render(<CustomerInvoiceList customerId="cust-A" />);
    await waitFor(() =>
      expect(screen.queryByTestId("cd-overview-invoices-table-wrap")).toBeTruthy()
    );
    for (let i = 0; i < 7; i++) {
      const id = `inv-${String(i).padStart(3, "0")}`;
      expect(screen.queryByTestId(`cd-overview-invoice-row-${id}`)).toBeTruthy();
    }
    expect(screen.queryByTestId("cd-overview-invoices-view-all")).toBeNull();
    expect(screen.queryByTestId("cd-overview-invoices-count").textContent).toBe("(7)");
  });

  it("renders all 10 rows + NO 'View all' when total_count === 10 (bounded exact)", async () => {
    const rows = _makeRows(10);
    getSpy.mockResolvedValue({ rows, total_count: 10, has_more: false });
    render(<CustomerInvoiceList customerId="cust-A" />);
    await waitFor(() =>
      expect(screen.queryByTestId("cd-overview-invoices-table-wrap")).toBeTruthy()
    );
    // At the boundary everything is already visible — "View all" is
    // hidden per operator-approved default (recommended).
    expect(screen.queryByTestId("cd-overview-invoices-view-all")).toBeNull();
  });

  it("renders the empty state when the fetch returns zero rows", async () => {
    getSpy.mockResolvedValue({ rows: [], total_count: 0, has_more: false });
    render(<CustomerInvoiceList customerId="cust-A" />);
    await waitFor(() => expect(screen.queryByTestId("empty-state")).toBeTruthy());
    expect(screen.queryByTestId("cd-overview-invoices-table-wrap")).toBeNull();
    expect(screen.queryByTestId("cd-overview-invoices-view-all")).toBeNull();
  });

  it("clicking a row navigates to /invoices/<id>", async () => {
    const rows = _makeRows(3);
    getSpy.mockResolvedValue({ rows, total_count: 3, has_more: false });
    render(<CustomerInvoiceList customerId="cust-A" />);
    await waitFor(() =>
      expect(screen.queryByTestId("cd-overview-invoice-row-inv-000")).toBeTruthy()
    );
    fireEvent.click(screen.getByTestId("cd-overview-invoice-row-inv-001"));
    expect(navSpy).toHaveBeenCalledWith("/invoices/inv-001");
  });

  it("clicking 'View all' navigates to /invoices?customer_id=<cid>", async () => {
    const rows = _makeRows(10);
    getSpy.mockResolvedValue({ rows, total_count: 42, has_more: true });
    render(<CustomerInvoiceList customerId="cust-xyz" />);
    await waitFor(() =>
      expect(screen.queryByTestId("cd-overview-invoices-view-all")).toBeTruthy()
    );
    fireEvent.click(screen.getByTestId("cd-overview-invoices-view-all"));
    expect(navSpy).toHaveBeenCalledWith("/invoices?customer_id=cust-xyz");
  });

  it("defensively handles the bare-array legacy response shape", async () => {
    // Pre-``limit=`` the endpoint returned a bare array. The
    // component tolerates that shape so a historical staging DB
    // or a future refactor swap doesn't break the Overview.
    const rows = _makeRows(5);
    getSpy.mockResolvedValue(rows);
    render(<CustomerInvoiceList customerId="cust-A" />);
    await waitFor(() =>
      expect(screen.queryByTestId("cd-overview-invoices-table-wrap")).toBeTruthy()
    );
    for (let i = 0; i < 5; i++) {
      const id = `inv-${String(i).padStart(3, "0")}`;
      expect(screen.queryByTestId(`cd-overview-invoice-row-${id}`)).toBeTruthy();
    }
    expect(screen.queryByTestId("cd-overview-invoices-count").textContent).toBe("(5)");
  });

  it("renders an error pill if the fetch rejects", async () => {
    getSpy.mockRejectedValue(new Error("boom"));
    render(<CustomerInvoiceList customerId="cust-A" />);
    await waitFor(() =>
      expect(screen.queryByTestId("cd-overview-invoices-error")).toBeTruthy()
    );
    expect(screen.queryByTestId("cd-overview-invoices-error").textContent).toContain("boom");
  });
});
