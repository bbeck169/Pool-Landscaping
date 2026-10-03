/**
 * Feb-2026 · Phase 1 Convert-to-Invoice (quote side) — Vitest.
 *
 * Covers:
 *   • shouldShowConvertToInvoiceButton visibility predicate
 *     (quote-only · hidden when converted · role-gated).
 *   • convertToInvoiceRoute helper (invoice-id → /quotes/:id).
 *   • canUserConvertToInvoice role gate — mirrors
 *     ``backend/utils.require_admin_or_manager``.
 *   • handleConvertToInvoice handler contract — 201 success /
 *     409 already_converted / network error. Reimplementation
 *     mirrors ``QuoteInvoiceDetail.handleConvertToInvoice``
 *     against a mocked ``api`` + spies for navigate / toast.
 *
 * Follows the ``invoice-draft-send.test.jsx`` pattern — the
 * full QuoteInvoiceDetail component is router-heavy and hangs
 * under jsdom, so we cover the handler contract via a local
 * reimplementation keyed on the same pure helpers.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";

import {
  shouldShowConvertToInvoiceButton,
  convertToInvoiceRoute,
  canUserConvertToInvoice,
} from "@/pages/quotes/QuoteInvoiceDetail";

// ═══════════════════════════════════════════════════════════════════
// Button visibility predicate
// ═══════════════════════════════════════════════════════════════════
describe("shouldShowConvertToInvoiceButton · Phase 1", () => {
  it("returns true on a quote with no converted invoice + user can convert", () => {
    expect(shouldShowConvertToInvoiceButton({
      isInvoice: false, convertedInvoiceId: null, canConvert: true,
    })).toBe(true);
  });

  it("returns false on an invoice (button is quote-only)", () => {
    expect(shouldShowConvertToInvoiceButton({
      isInvoice: true, convertedInvoiceId: null, canConvert: true,
    })).toBe(false);
  });

  it("returns false when converted_invoice_id is already set (collapses to View invoice)", () => {
    expect(shouldShowConvertToInvoiceButton({
      isInvoice: false, convertedInvoiceId: "inv-xyz", canConvert: true,
    })).toBe(false);
  });

  it("returns false when the user is below admin/manager (role gate)", () => {
    expect(shouldShowConvertToInvoiceButton({
      isInvoice: false, convertedInvoiceId: null, canConvert: false,
    })).toBe(false);
  });

  it("returns false when BOTH converted + canConvert=false (defense in depth)", () => {
    expect(shouldShowConvertToInvoiceButton({
      isInvoice: false, convertedInvoiceId: "inv-xyz", canConvert: false,
    })).toBe(false);
  });
});

// ═══════════════════════════════════════════════════════════════════
// Route helper — invoices share /quotes/:id (Phase 11 invariant)
// ═══════════════════════════════════════════════════════════════════
describe("convertToInvoiceRoute · Phase 1", () => {
  it("returns /quotes/:id for a non-empty id", () => {
    expect(convertToInvoiceRoute("inv-123")).toBe("/quotes/inv-123");
  });

  it("returns null for null / undefined / empty id (no-op safe)", () => {
    expect(convertToInvoiceRoute(null)).toBe(null);
    expect(convertToInvoiceRoute(undefined)).toBe(null);
    expect(convertToInvoiceRoute("")).toBe(null);
  });
});

// ═══════════════════════════════════════════════════════════════════
// Role gate — mirrors require_admin_or_manager
// ═══════════════════════════════════════════════════════════════════
describe("canUserConvertToInvoice · Phase 1", () => {
  it.each([
    ["admin", true],
    ["super_admin", true],
    ["owner", true],
    ["manager", true],
    ["technician", false],
    ["customer", false],
    ["dispatcher", false],
    [null, false],
    [undefined, false],
    ["", false],
  ])("role=%s → %s", (role, expected) => {
    expect(canUserConvertToInvoice(role)).toBe(expected);
  });

  it("is case-insensitive on the role token", () => {
    expect(canUserConvertToInvoice("ADMIN")).toBe(true);
    expect(canUserConvertToInvoice("Super_Admin")).toBe(true);
    expect(canUserConvertToInvoice("Owner")).toBe(true);
    expect(canUserConvertToInvoice("MANAGER")).toBe(true);
  });
});

// ═══════════════════════════════════════════════════════════════════
// Handler contract — POST /quotes/{qid}/convert-to-invoice
// ═══════════════════════════════════════════════════════════════════
describe("handleConvertToInvoice · Phase 1 · contract", () => {
  // Reimplementation mirroring
  // ``QuoteInvoiceDetail.handleConvertToInvoice`` without the React
  // setState + setTimeout wrappers so the contract test runs
  // synchronously under jsdom.
  async function handleConvertToInvoice({
    api, id, onToast, navigate, onReload,
  }) {
    try {
      const r = await api.post(`/quotes/${id}/convert-to-invoice`, {});
      onToast({ tone: "success", message: "Converted to invoice" });
      const route = convertToInvoiceRoute(r?.invoice_id);
      if (route) navigate(route);
      else await onReload();
    } catch (e) {
      if (e?.status === 409) {
        const existingId = e?.data?.detail?.invoice_id;
        const route = convertToInvoiceRoute(existingId);
        onToast({
          tone: "warning",
          message: "Already converted — opening existing invoice.",
        });
        if (route) navigate(route);
      } else {
        onToast({
          tone: "error",
          message: e?.message || "Convert to invoice failed",
        });
      }
    }
  }

  beforeEach(() => { vi.clearAllMocks(); });

  it("201 → POSTs /quotes/{id}/convert-to-invoice then navigates to /quotes/{invoice_id}", async () => {
    const api = {
      post: vi.fn(async () => ({
        invoice_id: "inv-new-1",
        invoice_number: "INV-00042",
      })),
    };
    const onToast = vi.fn();
    const navigate = vi.fn();
    const onReload = vi.fn();

    await handleConvertToInvoice({
      api, id: "q-1", onToast, navigate, onReload,
    });

    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post).toHaveBeenCalledWith("/quotes/q-1/convert-to-invoice", {});
    expect(onToast).toHaveBeenCalledWith({
      tone: "success",
      message: "Converted to invoice",
    });
    expect(navigate).toHaveBeenCalledWith("/quotes/inv-new-1");
    expect(onReload).not.toHaveBeenCalled();
  });

  it("201 with missing invoice_id → reloads detail without navigating", async () => {
    const api = { post: vi.fn(async () => ({ invoice_number: "INV-00099" })) };
    const onToast = vi.fn();
    const navigate = vi.fn();
    const onReload = vi.fn();

    await handleConvertToInvoice({
      api, id: "q-x", onToast, navigate, onReload,
    });

    expect(onToast).toHaveBeenCalledWith({
      tone: "success",
      message: "Converted to invoice",
    });
    expect(navigate).not.toHaveBeenCalled();
    expect(onReload).toHaveBeenCalledTimes(1);
  });

  it("409 already_converted → navigates to invoice carried by err.data.detail.invoice_id", async () => {
    const err = Object.assign(new Error("Already converted"), {
      status: 409,
      data: {
        detail: {
          code: "already_converted",
          invoice_id: "inv-existing-9",
        },
      },
    });
    const api = { post: vi.fn(async () => { throw err; }) };
    const onToast = vi.fn();
    const navigate = vi.fn();
    const onReload = vi.fn();

    await handleConvertToInvoice({
      api, id: "q-1", onToast, navigate, onReload,
    });

    expect(onToast).toHaveBeenCalledWith({
      tone: "warning",
      message: "Already converted — opening existing invoice.",
    });
    expect(navigate).toHaveBeenCalledWith("/quotes/inv-existing-9");
    expect(onReload).not.toHaveBeenCalled();
  });

  it("409 without invoice_id in detail → warning toast, no navigate (defensive)", async () => {
    const err = Object.assign(new Error("Already converted"), {
      status: 409,
      data: { detail: { code: "already_converted" } },
    });
    const api = { post: vi.fn(async () => { throw err; }) };
    const onToast = vi.fn();
    const navigate = vi.fn();
    const onReload = vi.fn();

    await handleConvertToInvoice({
      api, id: "q-1", onToast, navigate, onReload,
    });

    expect(onToast).toHaveBeenCalledWith({
      tone: "warning",
      message: "Already converted — opening existing invoice.",
    });
    expect(navigate).not.toHaveBeenCalled();
  });

  it("other error (500 / network) → error toast, no navigate", async () => {
    const api = {
      post: vi.fn(async () => { throw new Error("boom"); }),
    };
    const onToast = vi.fn();
    const navigate = vi.fn();
    const onReload = vi.fn();

    await handleConvertToInvoice({
      api, id: "q-1", onToast, navigate, onReload,
    });

    expect(onToast).toHaveBeenCalledWith({ tone: "error", message: "boom" });
    expect(navigate).not.toHaveBeenCalled();
  });

  it("error with no message → default 'Convert to invoice failed' copy", async () => {
    const api = {
      post: vi.fn(async () => { const e = new Error(); e.message = ""; throw e; }),
    };
    const onToast = vi.fn();
    const navigate = vi.fn();
    const onReload = vi.fn();

    await handleConvertToInvoice({
      api, id: "q-1", onToast, navigate, onReload,
    });

    expect(onToast).toHaveBeenCalledWith({
      tone: "error",
      message: "Convert to invoice failed",
    });
  });
});
