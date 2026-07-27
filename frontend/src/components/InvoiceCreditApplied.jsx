/**
 * Task SS Phase 2 · Feb 2026 — Invoice credit-applied annotation.
 *
 * Small component reused on both portal + admin invoice views. If
 * ``credits_applied_cents > 0``, renders one of two lines:
 *
 *   "Credit applied: $XX.XX · Balance due: $YY.YY"        (partial)
 *   "Paid with service credit — $XX.XX applied"           (fully covered)
 *
 * Otherwise renders nothing (backward-compatible).
 */
import React from "react";

function fmt(cents) {
  const n = Number(cents || 0) / 100;
  return `$${n.toFixed(2)}`;
}

/**
 * @param invoice          — invoice doc with ``credits_applied_cents``,
 *                             ``total`` (dollars), ``amount_paid`` (dollars),
 *                             ``payment_status``, ``paid_method``.
 * @param testidPrefix     — testid prefix (defaults to "invoice-credit").
 */
export default function InvoiceCreditApplied({ invoice, testidPrefix = "invoice-credit" }) {
  if (!invoice) return null;
  const cents = Number(invoice.credits_applied_cents || 0);
  if (cents <= 0) return null;

  const paidViaCredit =
    (invoice.paid_method === "service_credit")
    || (String(invoice.payment_status || "").toLowerCase() === "paid"
          && Number(invoice.amount_paid || 0) === 0);

  if (paidViaCredit) {
    return (
      <div className="mt-2 rounded-lg px-3 py-2 text-sm"
            style={{ backgroundColor: "#f0fdf4",
                      border: "1px solid #bbf7d0",
                      color: "#166534" }}
            data-testid={`${testidPrefix}-fully-covered`}>
        ✓ Paid with service credit — {fmt(cents)} applied
      </div>
    );
  }

  const totalCents = Math.round(Number(invoice.total || 0) * 100);
  const paidCents = Math.round(Number(invoice.amount_paid || 0) * 100);
  // Balance due = original total MINUS credit applied MINUS anything
  // paid by card. Task SS spec: "Credit applied: $15 · Balance due:
  // $35" on a $50 invoice with $15 credit.
  const dueCents = Math.max(0, totalCents - cents - paidCents);
  return (
    <div className="mt-2 text-sm"
          style={{ color: "#525252" }}
          data-testid={`${testidPrefix}-partial`}>
      <strong data-testid={`${testidPrefix}-amount`}>
        Credit applied: {fmt(cents)}
      </strong>
      {" · "}
      <span data-testid={`${testidPrefix}-balance-due`}>
        Balance due: {fmt(dueCents)}
      </span>
    </div>
  );
}
