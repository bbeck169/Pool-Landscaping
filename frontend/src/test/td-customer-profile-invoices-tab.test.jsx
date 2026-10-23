/**
 * TD-customer-profile-invoices-tab · Feb-2026
 * ============================================================
 *
 * Vitest coverage for the pre-wire of
 * ``TD-invoice-title-display-fallback`` (``getInvoiceDisplayTitle``
 * helper) + the Customer-profile Invoices tab that replaces the
 * ``"Invoices come in Phase 3"`` placeholder.
 *
 * Covered:
 *   1. Helper — 4 fallback branches, non-object input, truncation.
 *   2. Tab — loading / populated / empty / error states.
 *   3. Tab — sorts newest-first by created_at.
 *   4. Tab — row click navigates to /invoices/${id}.
 *   5. Static source contract — CustomerDetail.jsx now mounts
 *      ``CustomerInvoicesTab`` on the invoices tab (not the
 *      "Phase 3" placeholder).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import path from "node:path";
import {
  render, screen, cleanup, waitFor, fireEvent,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { getInvoiceDisplayTitle } from "@/utils/invoiceTitle";


const { apiGetSpy, navigateSpy } = vi.hoisted(() => ({
  apiGetSpy: vi.fn(),
  navigateSpy: vi.fn(),
}));


vi.mock("@/api", () => ({
  api: { get: (...a) => apiGetSpy(...a), post: vi.fn() },
}));


vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateSpy };
});


vi.mock("@/theme", () => ({
  colors: {
    surface: "#FFFFFF", surfaceSecondary: "#F4F4F5",
    border: "#E4E4E7", divider: "#E4E4E7", muted: "#71717A",
    brand: "#0284C7", onSurface: "#09090B",
    onSurfaceSecondary: "#52525B", danger: "#B91C1C",
  },
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
}));


vi.mock("@/components/ui-kit", () => ({
  Chip: ({ label, tone }) => (
    <span data-testid={`chip-${tone}`}>{label}</span>
  ),
  EmptyState: ({ title, hint, ...rest }) => (
    <div {...rest}>
      <h4>{title}</h4>
      <p>{hint}</p>
    </div>
  ),
  Skeleton: (props) => <div {...props} />,
}));


import CustomerInvoicesTab from
  "@/components/customers/CustomerInvoicesTab";


function _mountTab(cid = "cust-1") {
  return render(
    <MemoryRouter>
      <CustomerInvoicesTab customerId={cid} />
    </MemoryRouter>,
  );
}


// ═════════════════════════════════════════════════════════════
// 1. Helper — getInvoiceDisplayTitle
// ═════════════════════════════════════════════════════════════
describe("getInvoiceDisplayTitle", () => {
  it("returns invoice.title verbatim when set", () => {
    expect(getInvoiceDisplayTitle({
      title: "Monthly maintenance plan",
    })).toBe("Monthly maintenance plan");
  });

  it("falls back to first line item description when title empty", () => {
    expect(getInvoiceDisplayTitle({
      title: "",
      line_items: [
        { description: "Pool opening — spring" },
        { description: "ignored second item" },
      ],
    })).toBe("Pool opening — spring");
  });

  it("accepts line_items[0].title when description absent", () => {
    expect(getInvoiceDisplayTitle({
      title: null,
      line_items: [{ title: "Chlorine shock treatment" }],
    })).toBe("Chlorine shock treatment");
  });

  it("truncates long line-item fallback to 80 chars with ellipsis", () => {
    const long = "a".repeat(120);
    const out = getInvoiceDisplayTitle({
      title: "", line_items: [{ description: long }],
    });
    expect(out.length).toBe(81);  // 80 chars + ellipsis
    expect(out.endsWith("…")).toBe(true);
  });

  it("falls back to date-stamped literal when no title + no line items", () => {
    const out = getInvoiceDisplayTitle({
      title: "", line_items: [],
      invoice_date: "2026-03-14T10:00:00+00:00",
    });
    expect(out).toBe("Invoice — March 14, 2026");
  });

  it("prefers invoice_date over issued_at over created_at", () => {
    const out = getInvoiceDisplayTitle({
      title: "", line_items: [],
      invoice_date: "2026-03-14",
      issued_at: "2025-01-01",
      created_at: "2024-01-01",
    });
    expect(out).toBe("Invoice — March 14, 2026");
  });

  it("falls back to created_at when invoice_date + issued_at missing", () => {
    const out = getInvoiceDisplayTitle({
      title: "", line_items: [],
      created_at: "2026-07-04T09:00:00Z",
    });
    expect(out).toContain("Invoice — ");
    expect(out).toContain("2026");
  });

  it("defensive: returns 'Invoice' when nothing is parseable", () => {
    expect(getInvoiceDisplayTitle({
      title: "", line_items: [],
    })).toBe("Invoice");
    expect(getInvoiceDisplayTitle({
      title: "", line_items: [], invoice_date: "not-a-date",
    })).toBe("Invoice");
  });

  it("defensive: returns 'Invoice' for null / non-object input", () => {
    expect(getInvoiceDisplayTitle(null)).toBe("Invoice");
    expect(getInvoiceDisplayTitle(undefined)).toBe("Invoice");
    expect(getInvoiceDisplayTitle("string")).toBe("Invoice");
    expect(getInvoiceDisplayTitle(42)).toBe("Invoice");
  });

  it("whitespace-only title is treated as empty", () => {
    const out = getInvoiceDisplayTitle({
      title: "   ", line_items: [{ description: "Second-chance label" }],
    });
    expect(out).toBe("Second-chance label");
  });
});


// ═════════════════════════════════════════════════════════════
// 2. Tab — loading / populated / empty / error
// ═════════════════════════════════════════════════════════════
describe("CustomerInvoicesTab — states", () => {
  beforeEach(() => {
    apiGetSpy.mockReset();
    navigateSpy.mockReset();
  });
  afterEach(() => cleanup());

  it("renders the loading skeleton before data arrives", () => {
    // Promise that never resolves — stays in loading state.
    apiGetSpy.mockReturnValue(new Promise(() => {}));
    _mountTab("cust-loading");
    expect(screen.getByTestId("cd-invoices-tab-loading"))
      .toBeTruthy();
  });

  it("renders rows + total count when data arrives", async () => {
    apiGetSpy.mockResolvedValue({
      rows: [
        {
          id: "inv-1",
          invoice_number: "INV-100",
          title: "Monthly maintenance",
          total: 250.00,
          payment_status: "unpaid",
          created_at: "2026-10-20T10:00:00Z",
          invoice_date: "2026-10-20",
        },
        {
          id: "inv-2",
          invoice_number: "INV-099",
          title: "",
          line_items: [{ description: "Opening service" }],
          total: 500.00,
          payment_status: "paid",
          created_at: "2026-10-10T10:00:00Z",
        },
      ],
      total_count: 2, has_more: false, limit: 200, offset: 0,
    });
    _mountTab("cust-populated");
    await waitFor(() => expect(
      screen.getByTestId("cd-invoices-tab-count")).toBeTruthy());
    expect(screen.getByTestId("cd-invoices-tab-count").textContent)
      .toContain("2");
    // Title column uses the helper — second row falls back to
    // line_items[0].description.
    expect(screen.getByTestId("cd-invoices-tab-row-title-inv-1")
      .textContent).toBe("Monthly maintenance");
    expect(screen.getByTestId("cd-invoices-tab-row-title-inv-2")
      .textContent).toBe("Opening service");
    // Amount column uses money() formatter.
    expect(screen.getByTestId("cd-invoices-tab-row-amount-inv-1")
      .textContent).toBe("$250.00");
    // Status chips wire the correct tone.
    expect(screen.getByTestId("cd-invoices-tab-row-status-inv-2")
      .textContent).toContain("paid");
  });

  it("renders the empty state when the customer has zero invoices", async () => {
    apiGetSpy.mockResolvedValue({
      rows: [], total_count: 0, has_more: false,
      limit: 200, offset: 0,
    });
    _mountTab("cust-empty");
    await waitFor(() => expect(
      screen.getByTestId("cd-invoices-tab-empty")).toBeTruthy());
    expect(screen.getByTestId("cd-invoices-tab-empty").textContent)
      .toContain("No invoices yet");
  });

  it("renders the error state when the API rejects", async () => {
    apiGetSpy.mockRejectedValue(new Error("network boom"));
    _mountTab("cust-err");
    await waitFor(() => expect(
      screen.getByTestId("cd-invoices-tab-error")).toBeTruthy());
    expect(screen.getByTestId("cd-invoices-tab-error").textContent)
      .toContain("network boom");
  });
});


// ═════════════════════════════════════════════════════════════
// 3. Tab — sort DESC by created_at
// ═════════════════════════════════════════════════════════════
describe("CustomerInvoicesTab — sort order", () => {
  beforeEach(() => {
    apiGetSpy.mockReset();
    navigateSpy.mockReset();
  });
  afterEach(() => cleanup());

  it("newest invoice renders first regardless of API order", async () => {
    apiGetSpy.mockResolvedValue({
      rows: [
        { id: "old", invoice_number: "INV-A",
          title: "Older", total: 1,
          created_at: "2024-01-01T00:00:00Z" },
        { id: "new", invoice_number: "INV-B",
          title: "Newer", total: 2,
          created_at: "2026-01-01T00:00:00Z" },
      ],
      total_count: 2,
    });
    _mountTab("cust-sort");
    await waitFor(() => expect(
      screen.getByTestId("cd-invoices-tab-row-new")).toBeTruthy());
    const rows = screen.getAllByTestId(/cd-invoices-tab-row-(?!number-|title-|date-|amount-|status-)/);
    expect(rows[0].getAttribute("data-testid"))
      .toBe("cd-invoices-tab-row-new");
    expect(rows[1].getAttribute("data-testid"))
      .toBe("cd-invoices-tab-row-old");
  });
});


// ═════════════════════════════════════════════════════════════
// 4. Row click navigates to /invoices/${id}
// ═════════════════════════════════════════════════════════════
describe("CustomerInvoicesTab — row click", () => {
  beforeEach(() => {
    apiGetSpy.mockReset();
    navigateSpy.mockReset();
  });
  afterEach(() => cleanup());

  it("clicking a row navigates to the invoice detail route", async () => {
    apiGetSpy.mockResolvedValue({
      rows: [
        { id: "inv-click-me", invoice_number: "INV-CLK",
          title: "x", total: 10,
          created_at: "2026-01-01T00:00:00Z" },
      ],
      total_count: 1,
    });
    _mountTab("cust-click");
    await waitFor(() => expect(
      screen.getByTestId("cd-invoices-tab-row-inv-click-me"))
      .toBeTruthy());
    fireEvent.click(
      screen.getByTestId("cd-invoices-tab-row-inv-click-me"));
    expect(navigateSpy).toHaveBeenCalledWith("/invoices/inv-click-me");
  });
});


// ═════════════════════════════════════════════════════════════
// 5. Static-source contract — placeholder removed
// ═════════════════════════════════════════════════════════════
describe("CustomerDetail · invoices tab wiring", () => {
  const CD_SRC = fs.readFileSync(
    path.resolve(process.cwd(),
      "src/pages/customers/CustomerDetail.jsx"),
    "utf-8",
  );

  it("renders CustomerInvoicesTab on the invoices tab", () => {
    expect(CD_SRC).toMatch(
      /tab === "invoices"[\s\S]{0,200}CustomerInvoicesTab/);
  });

  it("no longer shows the 'Invoices come in Phase 3' placeholder", () => {
    expect(CD_SRC.includes("Invoices come in Phase 3")).toBe(false);
  });

  it("imports CustomerInvoicesTab from the customers components dir", () => {
    expect(CD_SRC).toMatch(
      /import\s+CustomerInvoicesTab\s+from\s+"@\/components\/customers\/CustomerInvoicesTab"/);
  });
});


// ═════════════════════════════════════════════════════════════
// 6. CustomerInvoicesTab wires the shared helper (NOT a hardcode)
// ═════════════════════════════════════════════════════════════
describe("CustomerInvoicesTab · uses shared title helper", () => {
  const SRC = fs.readFileSync(
    path.resolve(process.cwd(),
      "src/components/customers/CustomerInvoicesTab.jsx"),
    "utf-8",
  );

  it("imports getInvoiceDisplayTitle from @/utils/invoiceTitle", () => {
    expect(SRC).toMatch(
      /import\s+\{\s*getInvoiceDisplayTitle\s*\}\s+from\s+"@\/utils\/invoiceTitle"/);
  });

  it("does NOT use the invoice.title || 'Invoice' hardcode anti-pattern", () => {
    // Operator-ruled anti-pattern — the whole point of the
    // helper + Ticket E sweep.  Guards against a refactor that
    // reintroduces the hardcode and keeps Ticket E's scope
    // honest (nothing to sweep in THIS file).
    expect(SRC).not.toMatch(/invoice\.title\s*\|\|\s*["']Invoice["']/);
    expect(SRC).not.toMatch(/r\.title\s*\|\|\s*["']Invoice["']/);
  });
});
