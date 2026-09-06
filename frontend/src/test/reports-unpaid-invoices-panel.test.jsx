/**
 * Phase R1.b · Feb-2026 — UnpaidInvoicesPanel renders rows,
 * threads the customer-focus filter into the API query, and
 * hosts the Send-reminder button.
 */
import React from "react";
import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/api", () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock("react-apexcharts", () => ({ __esModule: true, default: () => <div /> }));
vi.mock("@/components/ui/confirm-dialog", () => ({
  useConfirm: () => async () => true,
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { api } from "@/api";
import UnpaidInvoicesPanel from "@/components/reports/UnpaidInvoicesPanel";

const wrap = (ui) => <MemoryRouter>{ui}</MemoryRouter>;

describe("UnpaidInvoicesPanel (R1.b)", () => {
  beforeEach(() => { api.get.mockReset(); api.post.mockReset(); });

  it("renders unpaid rows with View + Send reminder actions", async () => {
    api.get.mockResolvedValue({
      total: 700,
      rows: [
        { id: "inv-1", invoice_number: "1001", customer_id: "c1",
          customer_name: "Alice", total: 500, amount_paid: 0, balance: 500,
          days_overdue: 12, partial: false, status: "issued",
          effective_due_date: "2026-01-20", reminder_count: 0 },
        { id: "inv-2", invoice_number: "1002", customer_id: "c2",
          customer_name: "Bob", total: 300, amount_paid: 100, balance: 200,
          days_overdue: 65, partial: true, status: "issued",
          effective_due_date: "2025-12-14", reminder_count: 2 },
      ],
    });

    render(wrap(<UnpaidInvoicesPanel filters={{ period: "mtd" }} />));
    await waitFor(() => {
      expect(screen.getByTestId("unpaid-invoices-panel-row-inv-1")).toBeInTheDocument();
      expect(screen.getByTestId("unpaid-invoices-panel-row-inv-2")).toBeInTheDocument();
    });
    expect(screen.getByTestId("unpaid-invoices-panel-view-inv-1")).toBeInTheDocument();
    expect(screen.getByTestId("unpaid-invoices-panel-remind-inv-1")).toBeInTheDocument();
    // Reminder counter chip surfaces on inv-2 (2 reminders sent).
    expect(screen.getByTestId("unpaid-invoices-panel-reminders-inv-2").textContent)
      .toMatch(/2 reminders/);
  });

  it("threads customer_id into the API when customerFocusId is set", async () => {
    api.get.mockResolvedValue({ rows: [] });
    render(wrap(
      <UnpaidInvoicesPanel filters={{ period: "mtd" }} customerFocusId="cust-99" />,
    ));
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    const called = api.get.mock.calls[0][0];
    expect(called).toMatch(/customer_id=cust-99/);
  });

  it("empty state renders when no invoices", async () => {
    api.get.mockResolvedValue({ rows: [] });
    render(wrap(<UnpaidInvoicesPanel filters={{ period: "mtd" }} />));
    await waitFor(() =>
      expect(screen.getByTestId("unpaid-invoices-panel-empty")).toBeInTheDocument()
    );
  });
});
