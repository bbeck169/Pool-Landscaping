/**
 * Phase K38 · Feb-2026 — BulkChargeModal ACH parity tests.
 *
 * Covers:
 *  1. paymentMethod="ach" renders the verbatim 3–5 business day warning.
 *  2. paymentMethod="ach" targets the ACH endpoint (dry-run + confirm)
 *     and surfaces bank last-4 in the eligibility table.
 *  3. paymentMethod="card" (default) renders the classic card flow —
 *     no ACH warning, targets the card endpoint.
 *  4. Failure path renders the shared error surface.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

import BulkChargeModal, { ACH_SETTLEMENT_WARNING } from "@/components/invoices/BulkChargeModal";

const _makeFetchStub = () => {
  const fn = vi.fn();
  return fn;
};

let fetchSpy;

beforeEach(() => {
  fetchSpy = _makeFetchStub();
  globalThis.fetch = fetchSpy;
  // Silence toasts.
  vi.mock("sonner", () => ({
    toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  }));
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const _achDryOk = (invoiceIds) => ({
  ok: true,
  json: async () => ({
    dry_run: true,
    payment_method_type: "ach",
    run_id: null,
    results: invoiceIds.map((id, i) => ({
      invoice_id: id,
      status: "would_charge",
      amount_cents: 5000 + i * 100,
      payment_method_id: `pm_ach_${i}`,
      bank_last4: "6789",
      bank_name: "Bank of Test",
    })),
    summary: { total: invoiceIds.length, would_charge: invoiceIds.length,
                skipped: 0, initiated: 0, failed: 0,
                total_amount_initiated_cents: 0 },
  }),
});

const _achConfirmOk = (invoiceIds) => ({
  ok: true,
  json: async () => ({
    dry_run: false,
    payment_method_type: "ach",
    run_id: "run-ach-42",
    results: invoiceIds.map((id, i) => ({
      invoice_id: id,
      status: "initiated",
      charge_id: `pi_ach_${i}`,
      amount_charged_cents: 5000 + i * 100,
      provider_status: "processing",
      bank_last4: "6789",
      bank_name: "Bank of Test",
    })),
    summary: { total: invoiceIds.length, initiated: invoiceIds.length,
                would_charge: 0, skipped: 0, failed: 0,
                total_amount_initiated_cents: invoiceIds.length * 5000 },
  }),
});

const _cardDryOk = (invoiceIds) => ({
  ok: true,
  json: async () => ({
    dry_run: true,
    run_id: null,
    results: invoiceIds.map((id, i) => ({
      invoice_id: id,
      status: "would_charge",
      amount_cents: 3000 + i * 50,
      payment_method_id: `pm_card_${i}`,
    })),
    summary: { total: invoiceIds.length, would_charge: invoiceIds.length,
                skipped: 0, charged: 0, failed: 0,
                total_amount_charged_cents: 0 },
  }),
});

describe("BulkChargeModal · ACH parity (K38)", () => {
  it("renders the verbatim 3-5 business day settlement warning when paymentMethod='ach'", async () => {
    const ids = ["inv-1"];
    fetchSpy.mockResolvedValueOnce(_achDryOk(ids));
    render(<BulkChargeModal invoiceIds={ids} paymentMethod="ach" onClose={() => {}} />);
    // Warning renders synchronously (does not depend on the async fetch).
    const warn = await screen.findByTestId("bulk-charge-ach-warning");
    expect(warn).toBeTruthy();
    expect(warn.textContent).toContain(ACH_SETTLEMENT_WARNING);
    // Sanity: the exact spec string, character for character.
    expect(ACH_SETTLEMENT_WARNING).toBe(
      "ACH payments take 3\u20135 business days to settle. " +
      "Charges may still fail after submission (NSF, closed account, or incorrect routing). " +
      "Failed charges will revert the invoice to Unpaid."
    );
  });

  it("hits the ACH endpoint (dry + confirm) and surfaces bank last-4 rows", async () => {
    const ids = ["inv-1", "inv-2"];
    fetchSpy
      .mockResolvedValueOnce(_achDryOk(ids))
      .mockResolvedValueOnce(_achConfirmOk(ids));
    render(<BulkChargeModal invoiceIds={ids} paymentMethod="ach" onClose={() => {}} />);
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    const dryUrl = fetchSpy.mock.calls[0][0];
    expect(dryUrl).toMatch(/\/api\/invoices\/bulk-charge-ach-on-file$/);
    // Bank last-4 renders in the eligibility rows.
    expect((await screen.findByTestId("bulk-charge-ach-bank-inv-1")).textContent).toMatch(/6789/);
    // Confirm button copy is ACH-specific.
    const confirm = screen.getByTestId("bulk-charge-ach-confirm");
    expect(confirm.textContent).toMatch(/Submit ACH/);
    fireEvent.click(confirm);
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    const confirmUrl = fetchSpy.mock.calls[1][0];
    expect(confirmUrl).toMatch(/\/api\/invoices\/bulk-charge-ach-on-file$/);
    // Confirm body: dry_run must be false, key reused from dry run.
    const dryBody = JSON.parse(fetchSpy.mock.calls[0][1].body);
    const confirmBody = JSON.parse(fetchSpy.mock.calls[1][1].body);
    expect(dryBody.dry_run).toBe(true);
    expect(confirmBody.dry_run).toBe(false);
    expect(confirmBody.idempotency_key).toBe(dryBody.idempotency_key);
    // Result surface shows "initiated" outcome.
    await waitFor(() => expect(screen.getByTestId("bulk-charge-ach-result")).toBeTruthy());
    expect(screen.getByText(/ACH submissions sent/i)).toBeTruthy();
  });

  it("card path (default) renders WITHOUT the ACH warning and targets the card endpoint", async () => {
    const ids = ["inv-x"];
    fetchSpy.mockResolvedValueOnce(_cardDryOk(ids));
    render(<BulkChargeModal invoiceIds={ids} onClose={() => {}} />);
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    expect(fetchSpy.mock.calls[0][0]).toMatch(/\/api\/invoices\/bulk-charge-card-on-file$/);
    // No ACH warning banner rendered.
    expect(screen.queryByTestId("bulk-charge-ach-warning")).toBeNull();
    // Card confirm copy.
    const confirm = await screen.findByTestId("bulk-charge-confirm");
    expect(confirm.textContent).toMatch(/Confirm charge/i);
  });

  it("renders the ACH error surface when the endpoint returns a 500", async () => {
    const ids = ["inv-fail"];
    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ detail: "stripe not configured" }),
    });
    render(<BulkChargeModal invoiceIds={ids} paymentMethod="ach" onClose={() => {}} />);
    const err = await screen.findByTestId("bulk-charge-ach-error");
    expect(err).toBeTruthy();
    expect(err.textContent).toMatch(/stripe not configured/);
  });
});
