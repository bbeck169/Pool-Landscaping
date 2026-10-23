/**
 * TD-customer-profile-invoices-tab · Feb-2026 (Ticket B)
 *   + TD-invoice-title-display-fallback updates (Ticket E).
 * ============================================================
 *
 * Vitest coverage for the Customer-profile Invoices tab + the
 * ``getInvoiceDisplayTitle`` helper that drives title display
 * across the 3 operator-approved surfaces (CustomerInvoicesTab ·
 * CustomerInvoiceList · PortalPages).
 *
 * Covered:
 *   1. Helper — 5-case rule (title / item_name / name /
 *      truncated-description / blank) + non-object input +
 *      whitespace-only skip + tier priority.
 *   2. CustomerInvoicesTab — loading / populated / empty /
 *      error states; sort DESC; row click.
 *   3. Surface wire-up (static source) — all 3 surfaces import
 *      the helper, CustomerInvoiceList + PortalPages compose it
 *      with resolvePortalInvoiceTitle (Import-#<N> axis
 *      preserved).
 *   4. CustomerDetail — invoices tab now mounts
 *      CustomerInvoicesTab (Ticket B wire-up).
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
  apiGetSpy: vi.fn(), navigateSpy: vi.fn(),
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
// 1. Helper — 5-case rule (Ticket E)
// ═════════════════════════════════════════════════════════════
describe("getInvoiceDisplayTitle · 5-case rule", () => {
  it("rule 1: returns invoice.title verbatim when set", () => {
    expect(getInvoiceDisplayTitle({ title: "Monthly plan" }))
      .toBe("Monthly plan");
  });

  it("rule 2: line_items[0].item_name — the operator Item column", () => {
    expect(getInvoiceDisplayTitle({
      title: "",
      line_items: [
        { item_name: "Every Other Week Landscaping Maintenance",
          description: "ignored paragraph" },
      ],
    })).toBe("Every Other Week Landscaping Maintenance");
  });

  it("rule 3: line_items[0].name — shorter-schema fallback", () => {
    expect(getInvoiceDisplayTitle({
      title: null,
      line_items: [{ name: "Pool opening", description: "ignored" }],
    })).toBe("Pool opening");
  });

  it("rule 4: description truncated at 60 chars + ellipsis", () => {
    const long = "Basic Bi-Weekly Landscape maintenance including mowing, edging, trimming bushes, blowing property";
    const out = getInvoiceDisplayTitle({
      title: "", line_items: [{ description: long }],
    });
    expect(out.length).toBe(61);  // 60 chars + ellipsis
    expect(out.endsWith("…")).toBe(true);
    expect(out.startsWith("Basic Bi-Weekly")).toBe(true);
  });

  it("rule 4: short description (<=60 chars) is NOT truncated", () => {
    expect(getInvoiceDisplayTitle({
      title: "", line_items: [{ description: "Weekly service" }],
    })).toBe("Weekly service");
  });

  it("rule 5: blank when every tier is empty", () => {
    expect(getInvoiceDisplayTitle({ title: "", line_items: [] }))
      .toBe("");
    expect(getInvoiceDisplayTitle({ title: null, line_items: [{}] }))
      .toBe("");
  });

  it("rule 5: blank for null / non-object input", () => {
    expect(getInvoiceDisplayTitle(null)).toBe("");
    expect(getInvoiceDisplayTitle(undefined)).toBe("");
    expect(getInvoiceDisplayTitle("")).toBe("");
    expect(getInvoiceDisplayTitle(42)).toBe("");
  });

  it("whitespace-only values at any tier skip to next", () => {
    expect(getInvoiceDisplayTitle({
      title: "   ",
      line_items: [{ item_name: "  ", name: "  ",
                      description: "  " }],
    })).toBe("");
    expect(getInvoiceDisplayTitle({
      title: "  ",
      line_items: [{ item_name: " ",
                      description: "Weekly service" }],
    })).toBe("Weekly service");
  });

  it("tier priority: item_name > name > description", () => {
    expect(getInvoiceDisplayTitle({
      title: "",
      line_items: [{
        item_name: "A", name: "B", description: "C" }],
    })).toBe("A");
    expect(getInvoiceDisplayTitle({
      title: "",
      line_items: [{ name: "B", description: "C" }],
    })).toBe("B");
  });
});


// ═════════════════════════════════════════════════════════════
// 2. CustomerInvoicesTab — states (Ticket B regression)
// ═════════════════════════════════════════════════════════════
describe("CustomerInvoicesTab — states", () => {
  beforeEach(() => {
    apiGetSpy.mockReset();
    navigateSpy.mockReset();
  });
  afterEach(() => cleanup());

  it("renders the loading skeleton before data arrives", () => {
    apiGetSpy.mockReturnValue(new Promise(() => {}));
    _mountTab("cust-loading");
    expect(screen.getByTestId("cd-invoices-tab-loading")).toBeTruthy();
  });

  it("renders rows + helper-driven titles", async () => {
    apiGetSpy.mockResolvedValue({
      rows: [
        {
          id: "inv-1", invoice_number: "INV-100",
          title: "Monthly maintenance", total: 250.00,
          payment_status: "unpaid",
          created_at: "2026-10-20T10:00:00Z",
        },
        {
          id: "inv-2", invoice_number: "INV-099",
          title: "",
          line_items: [{ item_name: "Opening service" }],
          total: 500.00, payment_status: "paid",
          created_at: "2026-10-10T10:00:00Z",
        },
        {
          id: "inv-3", invoice_number: "INV-098",
          title: "",
          line_items: [{ description: "Weekly recurring landscape service" }],
          total: 100.00, payment_status: "unpaid",
          created_at: "2026-10-05T10:00:00Z",
        },
      ],
      total_count: 3, has_more: false, limit: 200, offset: 0,
    });
    _mountTab("cust-populated");
    await waitFor(() => expect(
      screen.getByTestId("cd-invoices-tab-count")).toBeTruthy());
    // rule 1 — verbatim title
    expect(screen.getByTestId("cd-invoices-tab-row-title-inv-1")
      .textContent).toBe("Monthly maintenance");
    // rule 2 — item_name fallback
    expect(screen.getByTestId("cd-invoices-tab-row-title-inv-2")
      .textContent).toBe("Opening service");
    // rule 4 — description fallback (short — not truncated)
    expect(screen.getByTestId("cd-invoices-tab-row-title-inv-3")
      .textContent).toBe("Weekly recurring landscape service");
  });

  it("renders the empty state when zero invoices", async () => {
    apiGetSpy.mockResolvedValue({
      rows: [], total_count: 0, has_more: false,
      limit: 200, offset: 0,
    });
    _mountTab("cust-empty");
    await waitFor(() => expect(
      screen.getByTestId("cd-invoices-tab-empty")).toBeTruthy());
  });

  it("renders the error state when API rejects", async () => {
    apiGetSpy.mockRejectedValue(new Error("network boom"));
    _mountTab("cust-err");
    await waitFor(() => expect(
      screen.getByTestId("cd-invoices-tab-error")).toBeTruthy());
    expect(screen.getByTestId("cd-invoices-tab-error").textContent)
      .toContain("network boom");
  });

  it("newest invoice renders first regardless of API order", async () => {
    apiGetSpy.mockResolvedValue({
      rows: [
        { id: "old", invoice_number: "INV-A", title: "Older",
          total: 1, created_at: "2024-01-01T00:00:00Z" },
        { id: "new", invoice_number: "INV-B", title: "Newer",
          total: 2, created_at: "2026-01-01T00:00:00Z" },
      ],
      total_count: 2,
    });
    _mountTab("cust-sort");
    await waitFor(() => expect(
      screen.getByTestId("cd-invoices-tab-row-new")).toBeTruthy());
    const rows = screen.getAllByTestId(
      /cd-invoices-tab-row-(?!number-|title-|date-|amount-|status-)/);
    expect(rows[0].getAttribute("data-testid"))
      .toBe("cd-invoices-tab-row-new");
    expect(rows[1].getAttribute("data-testid"))
      .toBe("cd-invoices-tab-row-old");
  });

  it("row click navigates to /invoices/<id>", async () => {
    apiGetSpy.mockResolvedValue({
      rows: [{ id: "inv-click", invoice_number: "INV-C",
                title: "x", total: 10,
                created_at: "2026-01-01T00:00:00Z" }],
      total_count: 1,
    });
    _mountTab("cust-click");
    await waitFor(() => expect(
      screen.getByTestId("cd-invoices-tab-row-inv-click")).toBeTruthy());
    fireEvent.click(
      screen.getByTestId("cd-invoices-tab-row-inv-click"));
    expect(navigateSpy).toHaveBeenCalledWith("/invoices/inv-click");
  });
});


// ═════════════════════════════════════════════════════════════
// 3. Surface wire-up — static source
// ═════════════════════════════════════════════════════════════
describe("Surface wire-up · all 3 consume the helper", () => {
  const tab = fs.readFileSync(
    path.resolve(process.cwd(),
      "src/components/customers/CustomerInvoicesTab.jsx"),
    "utf-8");
  const list = fs.readFileSync(
    path.resolve(process.cwd(),
      "src/components/customers/CustomerInvoiceList.jsx"),
    "utf-8");
  const portal = fs.readFileSync(
    path.resolve(process.cwd(),
      "src/pages/portal/PortalPages.jsx"),
    "utf-8");

  it("CustomerInvoicesTab imports + uses the helper", () => {
    expect(tab).toMatch(
      /import\s+\{\s*getInvoiceDisplayTitle\s*\}\s+from\s+"@\/utils\/invoiceTitle"/);
    expect(tab).toMatch(/getInvoiceDisplayTitle\(/);
  });

  it("CustomerInvoiceList imports + uses the helper", () => {
    expect(list).toMatch(
      /import\s+\{\s*getInvoiceDisplayTitle\s*\}\s+from\s+"@\/utils\/invoiceTitle"/);
    expect(list).toMatch(/getInvoiceDisplayTitle\(/);
  });

  it("CustomerInvoiceList composes helper + resolvePortalInvoiceTitle", () => {
    expect(list).toMatch(
      /resolvePortalInvoiceTitle\(\s*\{[\s\S]{0,200}title:\s*getInvoiceDisplayTitle\(r\)/);
  });

  it("PortalPages imports + uses the helper on BOTH call sites", () => {
    expect(portal).toMatch(
      /import\s+\{\s*getInvoiceDisplayTitle\s*\}\s+from\s+"@\/utils\/invoiceTitle"/);
    const matches = portal.match(
      /resolvePortalInvoiceTitle\(\s*\{[\s\S]{0,200}title:\s*getInvoiceDisplayTitle\(r\)/g);
    expect(matches).toBeTruthy();
    expect(matches.length).toBe(2);
  });

  it("no 'invoice.title || \"Invoice\"' hardcode in any surface", () => {
    for (const [n, src] of [
      ["tab", tab], ["list", list], ["portal", portal],
    ]) {
      expect(src, `${n}: anti-pattern present`).not.toMatch(
        /\binvoice\.title\s*\|\|\s*["']Invoice["']/);
    }
  });
});


// ═════════════════════════════════════════════════════════════
// 4. CustomerDetail — invoices tab mounts CustomerInvoicesTab
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

  it("no longer shows 'Invoices come in Phase 3' placeholder", () => {
    expect(CD_SRC.includes("Invoices come in Phase 3")).toBe(false);
  });

  it("imports CustomerInvoicesTab", () => {
    expect(CD_SRC).toMatch(
      /import\s+CustomerInvoicesTab\s+from\s+"@\/components\/customers\/CustomerInvoicesTab"/);
  });
});
