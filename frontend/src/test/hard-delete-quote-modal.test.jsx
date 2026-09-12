/**
 * HardDeleteQuoteModal · Feb-2026 · contract tests.
 *
 * Locks the modal + API-call behaviour per the Feb-2026
 * dispatch (FEATURE_QUOTE_HARD_DELETE.md):
 *
 *   1. Modal renders quote number + customer + total + warning line.
 *   2. Cancel closes the modal, no DELETE fired.
 *   3. Confirm fires DELETE /api/quotes/{qid}?hard=true and calls
 *      onDeleted with the response body on success.
 *   4. On 409 (invoice-conversion) the backend detail message is
 *      surfaced verbatim to onError, and the modal stays open.
 *   5. Warning copy calls out the zero-audit-trail trade-off.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

const { delSpy } = vi.hoisted(() => ({ delSpy: vi.fn() }));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: { del: (...a) => delSpy(...a) },
}));

vi.mock("@/theme", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    money: (n) => `$${Number(n).toFixed(2)}`,
  };
});

beforeEach(() => { delSpy.mockReset(); });
afterEach(() => { cleanup(); });

import HardDeleteQuoteModal from "@/components/quotes/HardDeleteQuoteModal";


function _render(overrides = {}) {
  const onClose = vi.fn();
  const onDeleted = vi.fn();
  const onError = vi.fn();
  render(
    <HardDeleteQuoteModal
      open={true}
      quoteId="q-99"
      quoteNumber="F92AE3AF"
      customerName="Jane Doe"
      totalAmount={37758}
      onClose={onClose}
      onDeleted={onDeleted}
      onError={onError}
      {...overrides}
    />,
  );
  return { onClose, onDeleted, onError };
}


describe("HardDeleteQuoteModal", () => {
  it("renders quote number + customer + total + warning line", () => {
    _render();
    expect(screen.getByTestId("hard-delete-quote-number").textContent)
      .toBe("F92AE3AF");
    expect(screen.getByTestId("hard-delete-quote-customer").textContent)
      .toBe("Jane Doe");
    expect(screen.getByTestId("hard-delete-quote-total").textContent)
      .toContain("37758");
    expect(screen.getByTestId("hard-delete-quote-warning").textContent)
      .toContain("permanently delete");
    expect(screen.getByTestId("hard-delete-quote-warning").textContent)
      .toContain("leaves no record");
  });

  it("Cancel button closes the modal without firing DELETE", () => {
    const { onClose, onDeleted, onError } = _render();
    fireEvent.click(screen.getByTestId("hard-delete-quote-cancel"));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(delSpy).not.toHaveBeenCalled();
    expect(onDeleted).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });

  it("Confirm fires DELETE /quotes/{qid}?hard=true and navigates on 200",
    async () => {
    delSpy.mockResolvedValue({
      ok: true, hard_deleted: true, quote_id: "q-99",
    });
    const { onDeleted, onError } = _render();
    fireEvent.click(screen.getByTestId("hard-delete-quote-confirm"));
    await waitFor(() => expect(onDeleted).toHaveBeenCalled());
    expect(delSpy).toHaveBeenCalledWith("/quotes/q-99?hard=true");
    expect(onDeleted).toHaveBeenCalledWith(
      expect.objectContaining({
        ok: true, hard_deleted: true, quote_id: "q-99",
      }),
    );
    expect(onError).not.toHaveBeenCalled();
  });

  it("On 409 (invoice conversion) surfaces backend detail verbatim "
        + "and keeps the modal open", async () => {
    const detail = "Quote has been converted to an invoice and cannot "
      + "be hard-deleted. Delete the invoice first or void the quote.";
    delSpy.mockRejectedValue({ status: 409, detail });
    const { onDeleted, onError, onClose } = _render();
    fireEvent.click(screen.getByTestId("hard-delete-quote-confirm"));
    await waitFor(() => expect(onError).toHaveBeenCalled());
    expect(onError).toHaveBeenCalledWith(detail);
    expect(onDeleted).not.toHaveBeenCalled();
    // Modal stays open — onClose was NOT called.
    expect(onClose).not.toHaveBeenCalled();
  });

  it("Confirm button is disabled while the DELETE is in flight",
    async () => {
    // Keep the promise pending so we can observe the busy state.
    let resolve;
    delSpy.mockImplementation(() => new Promise((r) => { resolve = r; }));
    _render();
    const btn = screen.getByTestId("hard-delete-quote-confirm");
    fireEvent.click(btn);
    await waitFor(() => expect(btn).toBeDisabled());
    expect(btn.textContent).toContain("Deleting");
    resolve({ ok: true, hard_deleted: true });
  });
});
