/**
 * HARD-DELETE · HD-B · Feb-2026 — InvoiceDetail "Move to Trash" tests.
 *
 * Invoices live in the ``quotes`` collection with
 * ``doc_type='invoice'``; the FE distinguishes them from estimates
 * only via the URL path (``/invoices/:id``). HD-A treats both as
 * ``entity_type='quote'`` — the tombstone captures the doc_type.
 *
 * Additional invoice-specific behaviour verified here: the modal
 * SHOULD surface an external-ref warning banner when the invoice
 * carries a Stripe ``payment_intent_id`` (the block-only reference
 * per user brief §5).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";

const postMock = vi.fn();
const navigateMock = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(() => Promise.resolve({})),
    post: (...a) => postMock(...a),
    put: () => Promise.resolve({}),
    patch: () => Promise.resolve({}),
    del: () => Promise.resolve({}),
    delete: () => Promise.resolve({}),
    request: () => Promise.resolve({}),
  },
  TOKEN_KEY: "token",
  api_base: () => "/api",
}));

vi.mock("sonner", () => ({
  toast: {
    success: (m) => toastSuccess(m),
    error: (m) => toastError(m),
  },
}));

import HardDeleteModal from "@/components/hard_delete/HardDeleteModal";

function InvoiceHarness({ role = "admin" }) {
  const [open, setOpen] = React.useState(false);
  const isStaff = role === "admin" || role === "super_admin";
  return (
    <div>
      {isStaff ? (
        <button data-testid="qid-hard-delete-btn" onClick={() => setOpen(true)}>
          Move to Trash
        </button>
      ) : null}
      <HardDeleteModal
        open={open}
        entityType="quote"
        entityId="inv-99"
        entityLabel="Invoice INV-2077"
        testidPrefix="qid-hard-delete"
        onClose={() => setOpen(false)}
        onSuccess={() => {
          setOpen(false);
          setTimeout(() => navigateMock("/invoices"), 400);
        }}
        onBlocked={() => setOpen(false)}
      />
    </div>
  );
}

beforeEach(() => {
  postMock.mockReset();
  navigateMock.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
});
afterEach(cleanup);

describe("InvoiceDetail · Move to Trash (HD-B)", () => {
  it("shows the button for admin/super", () => {
    render(<InvoiceHarness role="super_admin" />);
    expect(screen.getByTestId("qid-hard-delete-btn")).toBeInTheDocument();
  });

  it("hides the button for technician", () => {
    render(<InvoiceHarness role="technician" />);
    expect(
      screen.queryByTestId("qid-hard-delete-btn")
    ).not.toBeInTheDocument();
  });

  it("surfaces the Stripe payment_intent_id warning on preview", async () => {
    postMock.mockResolvedValue({
      ok: true,
      child_counts: {},
      external_refs: [{ payment_intent_id: "pi_1AbCd", id: "inv-99" }],
      would_block_purge: true,
    });
    render(<InvoiceHarness role="admin" />);
    fireEvent.click(screen.getByTestId("qid-hard-delete-btn"));
    await waitFor(() =>
      expect(
        screen.getByTestId("qid-hard-delete-external-ref-warning")
      ).toBeInTheDocument()
    );
    expect(
      screen.getByTestId("qid-hard-delete-external-ref-warning")
    ).toHaveTextContent(/payment_intent_id/i);
  });

  it("blocked-at-soft — 409 → error toast + no nav", async () => {
    postMock.mockImplementationOnce(() =>
      Promise.resolve({
        ok: true, child_counts: {}, external_refs: [{
          payment_intent_id: "pi_2", id: "inv-99",
        }],
        would_block_purge: true,
      })
    );
    render(<InvoiceHarness role="admin" />);
    fireEvent.click(screen.getByTestId("qid-hard-delete-btn"));
    await screen.findByTestId("qid-hard-delete-confirm");
    fireEvent.change(screen.getByTestId("qid-hard-delete-reason"), {
      target: { value: "duplicate invoice found" },
    });
    postMock.mockImplementationOnce(() => {
      const err = new Error("blocked_external_reference");
      err.status = 409;
      err.data = { detail: {
        error_code: "blocked_external_reference",
        refs: [{ payment_intent_id: "pi_2" }],
      } };
      return Promise.reject(err);
    });
    fireEvent.click(screen.getByTestId("qid-hard-delete-confirm"));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(navigateMock).not.toHaveBeenCalled();
  });
});
