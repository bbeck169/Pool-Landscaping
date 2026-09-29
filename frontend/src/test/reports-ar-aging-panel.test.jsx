/**
 * Phase R1.b · Feb-2026 — ArAgingPanel renders the bucket chart,
 * customer drill-down table, and fires onCustomerFocus when a
 * row's "See invoices" action is clicked.
 *
 * Feb-2026 · Test Hygiene Phase 3 — the ``customer_id`` column
 * renders a ``<CustomerLink>`` which imports ``<Link>`` from
 * ``react-router-dom``.  Without a Router context in scope,
 * ``LinkWithRef`` throws ``TypeError: Cannot destructure property
 * 'basename' of 'React.useContext(...)' as it is null`` — an
 * uncaught exception that surfaces during full-suite ``yarn vitest
 * run``.  Every render call is wrapped in a ``<MemoryRouter>`` so
 * the panel's internal ``<CustomerLink>`` resolves the router
 * context cleanly.  Mirrors the same wrap already used by
 * ``time-to-get-paid-report.test.jsx``.
 */
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));
vi.mock("react-apexcharts", () => ({
  __esModule: true,
  default: () => <div data-testid="apex-stub" />,
}));

import { api } from "@/api";
import ArAgingPanel from "@/components/reports/ArAgingPanel";

/** Renders the panel inside a MemoryRouter so ``<CustomerLink>``'s
 * ``<Link>`` child can resolve the router context.  Kept private
 * to this test file — the wrap is a test-setup concern, not an
 * application concern. */
const renderPanel = (props) =>
  render(
    <MemoryRouter initialEntries={["/reports/ar-aging"]}>
      <ArAgingPanel {...props} />
    </MemoryRouter>,
  );

describe("ArAgingPanel (R1.b)", () => {
  beforeEach(() => { api.get.mockReset(); });

  it("renders four buckets and customer drill-down rows", async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("ar_aging_by_customer")) {
        return Promise.resolve({
          rows: [
            { customer_id: "c1", customer_name: "Chesebrough",
              total_outstanding: 1200, invoice_count: 2, oldest_days_overdue: 45,
              buckets: {} },
            { customer_id: "c2", customer_name: "Rodriguez",
              total_outstanding: 500, invoice_count: 1, oldest_days_overdue: 12,
              buckets: {} },
          ],
        });
      }
      // Plain ar_aging (must be checked AFTER by_customer to avoid substring collision).
      return Promise.resolve({
        total: 1700, net_terms_days: 30,
        rows: [
          { bucket: "0-30", amount: 500, invoice_count: 1 },
          { bucket: "31-60", amount: 1200, invoice_count: 2 },
          { bucket: "61-90", amount: 0, invoice_count: 0 },
          { bucket: "90+", amount: 0, invoice_count: 0 },
        ],
      });
    });

    renderPanel({ filters: { period: "mtd" }, onCustomerFocus: () => {} });
    await waitFor(() => {
      expect(screen.getByTestId("ar-aging-panel-row-c1")).toBeInTheDocument();
      expect(screen.getByTestId("ar-aging-panel-row-c2")).toBeInTheDocument();
    });
    expect(screen.getByText(/Net 30/)).toBeInTheDocument();
  });

  it("clicking 'See invoices' invokes onCustomerFocus", async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("ar_aging_by_customer")) {
        return Promise.resolve({
          rows: [{ customer_id: "abc", customer_name: "X",
                    total_outstanding: 100, invoice_count: 1, oldest_days_overdue: 5,
                    buckets: {} }],
        });
      }
      return Promise.resolve({ rows: [], total: 0, net_terms_days: 30 });
    });
    const onFocus = vi.fn();
    renderPanel({ filters: { period: "mtd" }, onCustomerFocus: onFocus });
    await waitFor(() => screen.getByTestId("ar-aging-panel-drill-abc"));
    fireEvent.click(screen.getByTestId("ar-aging-panel-drill-abc"));
    expect(onFocus).toHaveBeenCalledWith("abc");
  });

  it("empty state renders when no outstanding balances", async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("ar_aging_by_customer")) return Promise.resolve({ rows: [] });
      return Promise.resolve({ rows: [], total: 0, net_terms_days: 30 });
    });
    renderPanel({ filters: { period: "mtd" }, onCustomerFocus: () => {} });
    await waitFor(() =>
      expect(screen.getByTestId("ar-aging-panel-empty")).toBeInTheDocument()
    );
  });
});
