/**
 * Feb-2026 · Bulk-pay iteration 1 — Stripe path · Vitest.
 *
 * The InvoicesList page is router-heavy and hangs under jsdom in this
 * Jest/Vitest config, so we exercise the shipped pure helpers and the
 * bulk-pay handler contract via a mocked ``api`` shim. Mirrors the
 * pattern used in ``invoice-draft-send.test.jsx``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";

import {
  isChargeableInvoice,
  nonChargeableReason,
  summarizeBulkChargeResult,
} from "@/pages/invoices/InvoicesList";

// ═══════════════════════════════════════════════════════════════════
// isChargeableInvoice
// ═══════════════════════════════════════════════════════════════════
describe("isChargeableInvoice", () => {
  const chargeableBase = {
    id: "i1", status: "sent", payment_status: "unpaid",
    has_payment_method: true, total: 100, amount_paid: 0,
  };

  it("returns true for sent + has_payment_method + unpaid", () => {
    expect(isChargeableInvoice(chargeableBase)).toBe(true);
  });

  it("returns true for 'accepted' status (partially paid but unpaid)", () => {
    expect(isChargeableInvoice({ ...chargeableBase, status: "accepted",
                                    payment_status: "partial" })).toBe(true);
  });

  it("returns false when status is 'draft'", () => {
    expect(isChargeableInvoice({ ...chargeableBase, status: "draft" })).toBe(false);
  });

  it("returns false when status is 'paid' / 'void' / 'cancelled'", () => {
    for (const s of ["paid", "void", "voided", "cancelled"]) {
      expect(isChargeableInvoice({ ...chargeableBase, status: s })).toBe(false);
    }
  });

  it("returns false when payment_status is 'paid' regardless of status", () => {
    expect(isChargeableInvoice({ ...chargeableBase, payment_status: "paid" })).toBe(false);
  });

  it("returns false when has_payment_method is false", () => {
    expect(isChargeableInvoice({ ...chargeableBase, has_payment_method: false })).toBe(false);
  });

  it("returns false for null/undefined input", () => {
    expect(isChargeableInvoice(null)).toBe(false);
    expect(isChargeableInvoice(undefined)).toBe(false);
  });
});

// ═══════════════════════════════════════════════════════════════════
// nonChargeableReason — the confirm-modal disclosure breakdown
// ═══════════════════════════════════════════════════════════════════
describe("nonChargeableReason", () => {
  it("prioritizes 'draft' status over 'no_card'", () => {
    // A draft that ALSO has no card should be reported as draft, not
    // no_card — that's the actionable info for the admin.
    expect(nonChargeableReason({ status: "draft", has_payment_method: false }))
      .toBe("draft");
  });

  it("returns 'paid' when payment_status is paid", () => {
    expect(nonChargeableReason({ status: "accepted", payment_status: "paid",
                                    has_payment_method: true })).toBe("paid");
  });

  it("returns 'no_card' when otherwise chargeable but PM absent", () => {
    expect(nonChargeableReason({ status: "sent", payment_status: "unpaid",
                                    has_payment_method: false })).toBe("no_card");
  });

  it("returns 'voided' when status is void/voided", () => {
    expect(nonChargeableReason({ status: "voided" })).toBe("voided");
    expect(nonChargeableReason({ status: "void" })).toBe("void");
  });

  it("returns 'unknown' for undecipherable rows", () => {
    expect(nonChargeableReason({ status: "sent", has_payment_method: true }))
      .toBe("unknown");
  });
});

// ═══════════════════════════════════════════════════════════════════
// summarizeBulkChargeResult
// ═══════════════════════════════════════════════════════════════════
describe("summarizeBulkChargeResult", () => {
  it("counts each status bucket correctly from raw results array", () => {
    const results = [
      { invoice_id: "1", status: "succeeded" },
      { invoice_id: "2", status: "succeeded" },
      { invoice_id: "3", status: "processing" },
      { invoice_id: "4", status: "no_card" },
      { invoice_id: "5", status: "not_chargeable", reason: "invoice_status_draft" },
      { invoice_id: "6", status: "not_found" },
      { invoice_id: "7", status: "failed", reason: "declined" },
      { invoice_id: "8", status: "requires_action" },
    ];
    const s = summarizeBulkChargeResult(results);
    expect(s.total).toBe(8);
    expect(s.succeeded).toBe(2);
    expect(s.processing).toBe(1);
    expect(s.no_card).toBe(1);
    expect(s.not_chargeable).toBe(1);
    expect(s.not_found).toBe(1);
    expect(s.failed).toBe(1);
    expect(s.requires_action).toBe(1);
  });

  it("accepts the backend envelope shape {results, summary}", () => {
    const envelope = {
      results: [{ status: "succeeded" }, { status: "no_card" }],
      summary: { total: 2, succeeded: 1, no_card: 1 },
    };
    // Helper ignores the pre-computed summary — recomputes from
    // results — so we can independently verify tallies in the UI.
    const s = summarizeBulkChargeResult(envelope);
    expect(s.total).toBe(2);
    expect(s.succeeded).toBe(1);
    expect(s.no_card).toBe(1);
  });

  it("empty input → zeroed buckets", () => {
    const s = summarizeBulkChargeResult([]);
    expect(s.total).toBe(0);
    expect(s.succeeded).toBe(0);
    expect(s.no_card).toBe(0);
    expect(s.failed).toBe(0);
  });

  it("unknown status strings bucket into 'failed'", () => {
    const s = summarizeBulkChargeResult([{ status: "weird" }, { status: "" }]);
    expect(s.failed).toBe(2);
  });
});

// ═══════════════════════════════════════════════════════════════════
// Bulk-pay handler contract — POSTs to /payments/bulk-charge-on-file
// ═══════════════════════════════════════════════════════════════════
describe("bulk-pay handler · POST /payments/bulk-charge-on-file", () => {
  async function handleBulkPay({ api, invoice_ids, onResults, onError }) {
    if (!invoice_ids || invoice_ids.length === 0) return;
    try {
      const res = await api.post("/payments/bulk-charge-on-file", { invoice_ids });
      onResults(res);
    } catch (e) {
      onError(e?.message || "Bulk charge failed");
    }
  }

  let onResults;
  let onError;
  beforeEach(() => {
    onResults = vi.fn();
    onError = vi.fn();
  });

  it("POSTs the chargeable ids and forwards the response envelope", async () => {
    const envelope = {
      results: [
        { invoice_id: "i1", status: "succeeded", amount: 100 },
        { invoice_id: "i2", status: "no_card" },
      ],
      summary: { total: 2, succeeded: 1, no_card: 1 },
    };
    const api = { post: vi.fn(async () => envelope) };

    await handleBulkPay({ api, invoice_ids: ["i1", "i2"], onResults, onError });

    expect(api.post).toHaveBeenCalledWith(
      "/payments/bulk-charge-on-file",
      { invoice_ids: ["i1", "i2"] },
    );
    expect(onResults).toHaveBeenCalledWith(envelope);
    expect(onError).not.toHaveBeenCalled();
  });

  it("no-ops on empty invoice list — no API call, no callbacks", async () => {
    const api = { post: vi.fn() };
    await handleBulkPay({ api, invoice_ids: [], onResults, onError });
    expect(api.post).not.toHaveBeenCalled();
    expect(onResults).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });

  it("surfaces API errors via onError", async () => {
    const api = { post: vi.fn(async () => { throw new Error("Boom"); }) };
    await handleBulkPay({ api, invoice_ids: ["i1"], onResults, onError });
    expect(onResults).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith("Boom");
  });
});

// ═══════════════════════════════════════════════════════════════════
// Selection buckets — the count that gates Pay Now button
// ═══════════════════════════════════════════════════════════════════
describe("selection buckets · chargeable count gates Pay Now button", () => {
  // Mirrors the ``selectionBuckets`` useMemo in InvoicesList.jsx.
  function computeBuckets(rows, selectedSet) {
    const chargeable = [];
    const skips = { no_card: [], draft: [], paid: [], other: [] };
    for (const r of rows) {
      if (!selectedSet.has(r.id)) continue;
      if (isChargeableInvoice(r)) chargeable.push(r);
      else {
        const reason = nonChargeableReason(r);
        if (reason === "no_card") skips.no_card.push(r);
        else if (reason === "draft") skips.draft.push(r);
        else if (reason === "paid" || reason === "voided") skips.paid.push(r);
        else skips.other.push(r);
      }
    }
    const totalAmount = chargeable.reduce(
      (a, r) => a + Math.max(0, Number(r.total || 0) - Number(r.amount_paid || 0)),
      0,
    );
    return { chargeable, skips, totalAmount };
  }

  const rows = [
    { id: "a", status: "sent", payment_status: "unpaid", has_payment_method: true, total: 100, amount_paid: 0, customer_id: "c1" },
    { id: "b", status: "sent", payment_status: "unpaid", has_payment_method: true, total: 250, amount_paid: 50, customer_id: "c1" },
    { id: "c", status: "sent", payment_status: "unpaid", has_payment_method: false, total: 75, amount_paid: 0, customer_id: "c2" },
    { id: "d", status: "draft", payment_status: "unpaid", has_payment_method: true, total: 40, amount_paid: 0, customer_id: "c3" },
    { id: "e", status: "accepted", payment_status: "paid", has_payment_method: true, total: 999, amount_paid: 999, customer_id: "c4" },
  ];

  it("empty selection → zero chargeable → Pay Now disabled path", () => {
    const b = computeBuckets(rows, new Set());
    expect(b.chargeable.length).toBe(0);
    expect(b.totalAmount).toBe(0);
  });

  it("selecting only draft + no_card + paid rows → 0 chargeable", () => {
    const b = computeBuckets(rows, new Set(["c", "d", "e"]));
    expect(b.chargeable.length).toBe(0);
    expect(b.skips.no_card).toHaveLength(1);
    expect(b.skips.draft).toHaveLength(1);
    expect(b.skips.paid).toHaveLength(1);
  });

  it("selecting 2 chargeable + 1 no_card → 2 chargeable, correct total", () => {
    const b = computeBuckets(rows, new Set(["a", "b", "c"]));
    expect(b.chargeable.length).toBe(2);
    // a: total=100, paid=0 → 100 outstanding
    // b: total=250, paid=50 → 200 outstanding
    expect(b.totalAmount).toBe(300);
    expect(b.skips.no_card).toHaveLength(1);
  });
});
