/**
 * Feb-2026 · BulkApplyCreditModal vitest coverage.
 *
 * Exercises:
 *   1. Confirm stage renders with correct N selected.
 *   2. Clicking Confirm POSTs ``/invoices/bulk-apply-credit`` with
 *      the selected invoice_ids and transitions to the Results
 *      stage.
 *   3. Results stage renders the summary line + per-invoice table.
 *   4. Status chips render for every row.
 *   5. Closing the Results modal calls onClose(truthy) so the
 *      parent refreshes the list.
 *   6. Closing the Confirm modal (Cancel) calls onClose(null).
 *   7. Error response surfaces as a toast + stays in confirm stage.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render, screen, fireEvent, waitFor,
} from "@testing-library/react";

const { postSpy } = vi.hoisted(() => ({ postSpy: vi.fn() }));
vi.mock("@/api", () => ({
  api: { post: (...a) => postSpy(...a) },
}));

const { toastError } = vi.hoisted(() => ({ toastError: vi.fn() }));
vi.mock("sonner", () => ({
  toast: { error: (...a) => toastError(...a), success: vi.fn() },
}));

beforeEach(() => {
  postSpy.mockReset();
  toastError.mockReset();
});


import BulkApplyCreditModal
  from "@/components/invoices/BulkApplyCreditModal";


function _buildResp({
  credited = 1,
  totalApplied = 50,
  rows = null,
} = {}) {
  return {
    request_id: "req-123",
    summary: {
      total_selected: credited + (rows?.length || 1) - credited,
      credited,
      skipped_no_credit: 0,
      skipped_already_paid: 0,
      skipped_blocked_status: 0,
      skipped_not_found: 0,
      errors: 0,
      total_amount_applied: totalApplied,
    },
    results: rows || [
      {
        invoice_id: "inv-A",
        invoice_number: "INV-A",
        customer_id: "cust-A",
        customer_name: "Alpha Customer",
        status: "credited",
        amount_applied: totalApplied,
        balance_remaining: 0,
        payment_status_after: "paid",
      },
    ],
  };
}


describe("BulkApplyCreditModal", () => {
  it("confirm stage renders with correct N selected", () => {
    render(
      <BulkApplyCreditModal
        invoiceIds={["a", "b", "c"]}
        onClose={() => {}}
      />,
    );
    expect(
      screen.getByTestId("bulk-apply-credit-confirm-stage"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("bulk-apply-credit-confirm-stage").textContent,
    ).toContain("3 selected invoices");
  });

  it("confirming POSTs with invoice_ids + transitions to results stage", async () => {
    postSpy.mockResolvedValueOnce(_buildResp());
    render(
      <BulkApplyCreditModal
        invoiceIds={["inv-A"]}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("bulk-apply-credit-confirm-btn"));
    await waitFor(() =>
      expect(
        screen.queryByTestId("bulk-apply-credit-results-stage"),
      ).toBeInTheDocument(),
    );
    expect(postSpy).toHaveBeenCalledWith(
      "/invoices/bulk-apply-credit",
      { invoice_ids: ["inv-A"] },
    );
  });

  it("results stage renders summary line + per-invoice table", async () => {
    postSpy.mockResolvedValueOnce(_buildResp({
      credited: 2, totalApplied: 150,
      rows: [
        {
          invoice_id: "inv-A", invoice_number: "INV-A",
          customer_name: "Alpha", status: "credited",
          amount_applied: 100, balance_remaining: 0,
          payment_status_after: "paid",
        },
        {
          invoice_id: "inv-B", invoice_number: "INV-B",
          customer_name: "Bravo", status: "credited",
          amount_applied: 50, balance_remaining: 25,
          payment_status_after: "partial",
        },
      ],
    }));
    render(
      <BulkApplyCreditModal
        invoiceIds={["inv-A", "inv-B"]}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("bulk-apply-credit-confirm-btn"));
    await waitFor(() =>
      screen.getByTestId("bulk-apply-credit-summary"),
    );
    const summary = screen.getByTestId("bulk-apply-credit-summary");
    expect(summary.textContent).toContain("2 invoices credited");
    expect(summary.textContent).toContain("$150.00");
    const table = screen.getByTestId("bulk-apply-credit-results-table");
    expect(table.textContent).toContain("INV-A");
    expect(table.textContent).toContain("INV-B");
    expect(table.textContent).toContain("Alpha");
    expect(table.textContent).toContain("Bravo");
  });

  it("renders a status chip for every row", async () => {
    postSpy.mockResolvedValueOnce(_buildResp({
      rows: [
        {
          invoice_id: "a", invoice_number: "A", status: "credited",
          amount_applied: 10, balance_remaining: 0,
        },
        {
          invoice_id: "b", invoice_number: "B",
          status: "skipped_no_credit",
          amount_applied: 0, balance_remaining: 20,
        },
        {
          invoice_id: "c", invoice_number: "C",
          status: "skipped_not_found",
          amount_applied: 0, balance_remaining: 0,
        },
      ],
    }));
    render(
      <BulkApplyCreditModal
        invoiceIds={["a", "b", "c"]}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("bulk-apply-credit-confirm-btn"));
    await waitFor(() =>
      screen.getByTestId("bulk-apply-credit-status-credited"),
    );
    expect(
      screen.getByTestId("bulk-apply-credit-status-skipped_no_credit"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("bulk-apply-credit-status-skipped_not_found"),
    ).toBeInTheDocument();
  });

  it("closing the results modal fires onClose with a truthy value", async () => {
    postSpy.mockResolvedValueOnce(_buildResp());
    const onClose = vi.fn();
    render(
      <BulkApplyCreditModal
        invoiceIds={["a"]}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByTestId("bulk-apply-credit-confirm-btn"));
    await waitFor(() =>
      screen.getByTestId("bulk-apply-credit-close-btn"),
    );
    fireEvent.click(screen.getByTestId("bulk-apply-credit-close-btn"));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(Boolean(onClose.mock.calls[0][0])).toBe(true);
  });

  it("Cancel on confirm stage fires onClose(null)", () => {
    const onClose = vi.fn();
    render(
      <BulkApplyCreditModal
        invoiceIds={["a"]}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByTestId("bulk-apply-credit-cancel-btn"));
    expect(onClose).toHaveBeenCalledWith(null);
  });

  it("error response surfaces as a toast + stays on confirm stage", async () => {
    const err = new Error("Server exploded");
    err.data = { detail: { message: "Server exploded" } };
    postSpy.mockRejectedValueOnce(err);
    render(
      <BulkApplyCreditModal
        invoiceIds={["a"]}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("bulk-apply-credit-confirm-btn"));
    await waitFor(() => expect(toastError).toHaveBeenCalledTimes(1));
    expect(toastError.mock.calls[0][0]).toContain("Server exploded");
    // Still on confirm stage — the user can retry.
    expect(
      screen.queryByTestId("bulk-apply-credit-results-stage"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("bulk-apply-credit-confirm-stage"),
    ).toBeInTheDocument();
  });
});
