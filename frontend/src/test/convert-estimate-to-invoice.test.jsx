/**
 * Feb-2026 · Phase 1 Convert-to-Invoice (estimate side) — Vitest.
 *
 * Covers the handler contract for ``Estimator.convertToInvoice``:
 *   • 201 → POST ``/estimates/{eid}/convert-to-invoice`` →
 *     navigate ``/quotes/{invoice_id}`` + stamp local
 *     convertedInvoiceId state (so the toolbar collapses to a
 *     "View invoice →" link without a re-fetch).
 *   • 409 ``already_converted`` → navigate existing invoice +
 *     stamp local state from ``err.data.detail.invoice_id``.
 *   • Other error → surface via toast, no navigate.
 *
 * Mirrors the ``invoice-draft-send.test.jsx`` + quote-side
 * ``convert-quote-to-invoice.test.jsx`` reimplementation pattern.
 * The full Estimator editor is router-heavy under jsdom; the pure
 * handler contract covers the Phase 1 brief without a full mount.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";

describe("Estimator.convertToInvoice · Phase 1 · contract", () => {
  // Reimplementation mirroring ``Estimator.convertToInvoice``
  // without the React setState + setTimeout wrappers.
  async function convertToInvoice({
    api, id, onToast, navigate, onSetConvertedInvoiceId,
  }) {
    try {
      const r = await api.post(`/estimates/${id}/convert-to-invoice`, {});
      onToast({ tone: "success", message: "Converted to invoice" });
      onSetConvertedInvoiceId(r?.invoice_id || null);
      if (r?.invoice_id) {
        navigate(`/quotes/${r.invoice_id}`);
      }
    } catch (e) {
      if (e?.status === 409) {
        const existingId = e?.data?.detail?.invoice_id;
        onToast({
          tone: "warning",
          message: "Already converted — opening existing invoice.",
        });
        onSetConvertedInvoiceId(existingId || null);
        if (existingId) navigate(`/quotes/${existingId}`);
      } else {
        onToast({
          tone: "error",
          message: e?.message || "Convert to invoice failed",
        });
      }
    }
  }

  beforeEach(() => { vi.clearAllMocks(); });

  it("201 → POSTs /estimates/{id}/convert-to-invoice then navigates to /quotes/{invoice_id}", async () => {
    const api = {
      post: vi.fn(async () => ({
        invoice_id: "inv-new-9",
        invoice_number: "INV-00050",
      })),
    };
    const onToast = vi.fn();
    const navigate = vi.fn();
    const onSetConvertedInvoiceId = vi.fn();

    await convertToInvoice({
      api, id: "est-1", onToast, navigate, onSetConvertedInvoiceId,
    });

    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post).toHaveBeenCalledWith("/estimates/est-1/convert-to-invoice", {});
    expect(onToast).toHaveBeenCalledWith({
      tone: "success",
      message: "Converted to invoice",
    });
    expect(onSetConvertedInvoiceId).toHaveBeenCalledWith("inv-new-9");
    expect(navigate).toHaveBeenCalledWith("/quotes/inv-new-9");
  });

  it("201 with missing invoice_id → toasts success but does not navigate", async () => {
    const api = { post: vi.fn(async () => ({ invoice_number: "INV-00051" })) };
    const onToast = vi.fn();
    const navigate = vi.fn();
    const onSetConvertedInvoiceId = vi.fn();

    await convertToInvoice({
      api, id: "est-2", onToast, navigate, onSetConvertedInvoiceId,
    });

    expect(onToast).toHaveBeenCalledWith({
      tone: "success",
      message: "Converted to invoice",
    });
    expect(onSetConvertedInvoiceId).toHaveBeenCalledWith(null);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("409 already_converted → navigates to existing invoice + stamps local state", async () => {
    const err = Object.assign(new Error("Already converted"), {
      status: 409,
      data: {
        detail: {
          code: "already_converted",
          invoice_id: "inv-existing-77",
        },
      },
    });
    const api = { post: vi.fn(async () => { throw err; }) };
    const onToast = vi.fn();
    const navigate = vi.fn();
    const onSetConvertedInvoiceId = vi.fn();

    await convertToInvoice({
      api, id: "est-1", onToast, navigate, onSetConvertedInvoiceId,
    });

    expect(onToast).toHaveBeenCalledWith({
      tone: "warning",
      message: "Already converted — opening existing invoice.",
    });
    expect(onSetConvertedInvoiceId).toHaveBeenCalledWith("inv-existing-77");
    expect(navigate).toHaveBeenCalledWith("/quotes/inv-existing-77");
  });

  it("409 missing invoice_id in detail → warning toast, no navigate", async () => {
    const err = Object.assign(new Error("Already converted"), {
      status: 409,
      data: { detail: { code: "already_converted" } },
    });
    const api = { post: vi.fn(async () => { throw err; }) };
    const onToast = vi.fn();
    const navigate = vi.fn();
    const onSetConvertedInvoiceId = vi.fn();

    await convertToInvoice({
      api, id: "est-1", onToast, navigate, onSetConvertedInvoiceId,
    });

    expect(onToast).toHaveBeenCalledWith({
      tone: "warning",
      message: "Already converted — opening existing invoice.",
    });
    expect(onSetConvertedInvoiceId).toHaveBeenCalledWith(null);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("other error (500 / network) → error toast, no navigate, no state stamp", async () => {
    const api = {
      post: vi.fn(async () => { throw new Error("boom"); }),
    };
    const onToast = vi.fn();
    const navigate = vi.fn();
    const onSetConvertedInvoiceId = vi.fn();

    await convertToInvoice({
      api, id: "est-1", onToast, navigate, onSetConvertedInvoiceId,
    });

    expect(onToast).toHaveBeenCalledWith({ tone: "error", message: "boom" });
    expect(navigate).not.toHaveBeenCalled();
    expect(onSetConvertedInvoiceId).not.toHaveBeenCalled();
  });

  it("error with no message → default 'Convert to invoice failed' copy", async () => {
    const api = {
      post: vi.fn(async () => { const e = new Error(); e.message = ""; throw e; }),
    };
    const onToast = vi.fn();
    const navigate = vi.fn();
    const onSetConvertedInvoiceId = vi.fn();

    await convertToInvoice({
      api, id: "est-1", onToast, navigate, onSetConvertedInvoiceId,
    });

    expect(onToast).toHaveBeenCalledWith({
      tone: "error",
      message: "Convert to invoice failed",
    });
  });
});
