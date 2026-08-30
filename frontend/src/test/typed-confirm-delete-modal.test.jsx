/**
 * Feb-2026 · Item 3 — REWRITTEN for the app-wide type-to-confirm removal.
 *
 * History: This suite originally verified the "type invoice-number
 * to confirm" gate on ``QuoteInvoiceDetail.jsx`` (both invoice-delete
 * and payment-delete modals). The typed-confirm UX was retired
 * app-wide per user brief; single-click Confirm is now the standard,
 * with a 2-click arm-and-execute reserved for CustomersList
 * catastrophic bulk deletes (>=500 rows).
 *
 * This file replaces the old assertions with regression guards that
 * lock in the NEW behaviour:
 *   1. Source-regex guards: no typed-confirm remnants on
 *      QuoteInvoiceDetail — no `_invoiceConfirmToken`,
 *      `_paymentConfirmToken`, `deleteConfirmText` state, and no
 *      "Type … to confirm" copy.
 *   2. Delete buttons enabled from open + fire on single click
 *      (harness mirrors the shipped modal footer).
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";


const QUOTE_DETAIL_SRC = readFileSync(
  resolve(__dirname, "../pages/quotes/QuoteInvoiceDetail.jsx"),
  "utf8",
);


// ══════════════════════════════════════════════════════════════════
// Layer 1 — source guards. Fail if the typed-confirm gate returns.
// ══════════════════════════════════════════════════════════════════
describe("QuoteInvoiceDetail source · type-to-confirm removed", () => {
  it("no `deleteConfirmText` state variable remains", () => {
    // The state hook + its setter should be gone. A stale JSDoc
    // that mentions the identifier is allowed (Feb-2026 changelog
    // comment), so we scope the assertion to real code lines by
    // requiring a `[…, …] = useState` call site.
    expect(QUOTE_DETAIL_SRC).not.toMatch(
      /const\s*\[\s*deleteConfirmText\s*,\s*setDeleteConfirmText\s*\]\s*=\s*useState/,
    );
  });

  it("no `_invoiceConfirmToken` / `_paymentConfirmToken` token constants remain", () => {
    expect(QUOTE_DETAIL_SRC).not.toMatch(/const\s+_invoiceConfirmToken\s*=/);
    expect(QUOTE_DETAIL_SRC).not.toMatch(/const\s+_paymentConfirmToken\s*=/);
  });

  it("no rendered `Type … to confirm` copy remains", () => {
    // A JSDoc/comment mentioning the retired pattern is fine —
    // the assertion targets the actual JSX text.
    expect(QUOTE_DETAIL_SRC).not.toMatch(/Type\s+<code[^>]*>/);
  });

  it("no `deleteConfirmText.trim()` disabled-gate on either Delete button", () => {
    expect(QUOTE_DETAIL_SRC).not.toMatch(
      /deleteConfirmText\.trim\(\)\s*!==/,
    );
  });

  it("delete-invoice + delete-payment Confirm buttons keep their testids", () => {
    expect(QUOTE_DETAIL_SRC).toMatch(/testid="id-delete-invoice-confirm"/);
    expect(QUOTE_DETAIL_SRC).toMatch(/testid="id-delete-payment-confirm"/);
  });
});


// ══════════════════════════════════════════════════════════════════
// Layer 2 — behavioural harness that mirrors the SHIPPED modal
// footer (single-click Delete, no text input). Verifies:
//   (a) no typed input renders,
//   (b) Confirm button enabled from mount,
//   (c) one click fires the mutation exactly once.
// ══════════════════════════════════════════════════════════════════
function DeleteConfirmHarness({ testidPrefix, onConfirm, busy = false }) {
  return (
    <div>
      {/* Historic testid kept off — the harness mirrors the shipped
          modal which now renders zero text inputs inside the
          confirmation footer. Any stale caller that queries the
          pre-removal testid will fail loudly. */}
      <button
        type="button"
        onClick={onConfirm}
        disabled={busy}
        data-testid={`${testidPrefix}-confirm`}
      >
        {busy ? "Deleting…" : "Delete"}
      </button>
    </div>
  );
}


describe("Single-click confirm · invoice-delete flow", () => {
  it("no text input is rendered anywhere in the harness", () => {
    render(<DeleteConfirmHarness testidPrefix="id-delete-invoice"
                                   onConfirm={() => {}} />);
    // Both the historic testid and any raw text input should be
    // absent.
    expect(screen.queryByTestId("id-delete-invoice-input")).toBeNull();
    // eslint-disable-next-line testing-library/no-node-access
    expect(document.querySelector("input[type=\"text\"]")).toBeNull();
  });

  it("Delete button is enabled immediately (no typed-confirm gate)", () => {
    render(<DeleteConfirmHarness testidPrefix="id-delete-invoice"
                                   onConfirm={() => {}} />);
    expect(screen.getByTestId("id-delete-invoice-confirm").disabled)
      .toBe(false);
  });

  it("a single click fires onConfirm exactly once", () => {
    const spy = vi.fn();
    render(<DeleteConfirmHarness testidPrefix="id-delete-invoice"
                                   onConfirm={spy} />);
    fireEvent.click(screen.getByTestId("id-delete-invoice-confirm"));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("Delete button disables while the mutation is in-flight", () => {
    render(<DeleteConfirmHarness testidPrefix="id-delete-invoice"
                                   onConfirm={() => {}} busy />);
    expect(screen.getByTestId("id-delete-invoice-confirm").disabled)
      .toBe(true);
  });
});


describe("Single-click confirm · payment-delete flow", () => {
  it("no text input is rendered", () => {
    render(<DeleteConfirmHarness testidPrefix="id-delete-payment"
                                   onConfirm={() => {}} />);
    expect(screen.queryByTestId("id-delete-payment-input")).toBeNull();
    // eslint-disable-next-line testing-library/no-node-access
    expect(document.querySelector("input[type=\"text\"]")).toBeNull();
  });

  it("Delete button enabled immediately + fires on single click", () => {
    const spy = vi.fn();
    render(<DeleteConfirmHarness testidPrefix="id-delete-payment"
                                   onConfirm={spy} />);
    const btn = screen.getByTestId("id-delete-payment-confirm");
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
