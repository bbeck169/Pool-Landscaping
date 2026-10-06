/**
 * InvoiceStatusStamp — Feb-2026 · INVOICE-STATUS-STAMP ticket.
 *
 * CSS-only grunge rubber-stamp overlay for the invoice header
 * (``.iv-header``). Renders PAID when the invoice is paid, PAST
 * DUE when the invoice is unpaid AND its due date has passed, or
 * nothing when neither applies. Payment is terminal — PAID always
 * wins over PAST DUE at the caller.
 *
 * Shared across every surface that mounts ``<InvoiceView>``:
 *
 *   * Admin console  → ``/invoices/:id``
 *   * Portal         → ``/portal/invoices/:id`` (via ``PortalInvoiceDetail``)
 *   * Magic pay      → ``/pay/invoice/:id?token=...``  (``PublicInvoicePay``)
 *   * Magic shortlink → ``/i/:token``                  (``PublicInvoiceMagic``)
 *
 * The caller derives ``status`` from the invoice payload and passes
 * it in; the stamp is purely presentational.
 *
 * Grunge technique: SVG filter (``feTurbulence`` + ``feDisplacementMap``)
 * applied via ``filter: url(#invoice-stamp-grunge)`` in
 * ``invoice-status-stamp.css``. The filter is mounted inline inside
 * this component so no asset lives in ``index.css`` and no PNG/JPG
 * is required. SVG filters are honoured by Chrome / WebKit / Gecko
 * print output since 2017.
 *
 * Click-safety: ``pointer-events: none`` on the stamp div so the
 * Pay Now / Print / Download PDF buttons sitting underneath remain
 * clickable.
 *
 * Accessibility: ``aria-hidden="true"`` because the stamp duplicates
 * the ``payment_status`` + ``outstanding_balance`` the invoice
 * already surfaces in text; screen-reader users don't need the
 * decorative stamp read aloud.
 */
import React from "react";
import "./invoice-status-stamp.css";


/** Shared ``filter: url(#...)`` target. Mounting the same filter
 * id multiple times (e.g. two stamps on one page) is harmless —
 * ``url(#...)`` resolution picks the first match. */
export const INVOICE_STAMP_FILTER_ID = "invoice-stamp-grunge";


function GrungeFilterDefs() {
  return (
    <svg
      className="invoice-stamp-filter-defs"
      aria-hidden="true"
      data-testid="invoice-stamp-filter-defs"
    >
      <defs>
        <filter id={INVOICE_STAMP_FILTER_ID}>
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.9"
            numOctaves="2"
            seed="7"
          />
          <feDisplacementMap in="SourceGraphic" scale="4" />
        </filter>
      </defs>
    </svg>
  );
}


export default function InvoiceStatusStamp({ status }) {
  if (status !== "paid" && status !== "past-due") return null;
  if (status === "paid") {
    return (
      <>
        <GrungeFilterDefs />
        <div
          className="invoice-stamp invoice-stamp--paid"
          data-testid="invoice-stamp-paid"
          aria-hidden="true"
        >
          <span className="invoice-stamp__title">Paid</span>
          <span className="invoice-stamp__sub">Invoice</span>
        </div>
      </>
    );
  }
  // past-due
  return (
    <>
      <GrungeFilterDefs />
      <div
        className="invoice-stamp invoice-stamp--past-due"
        data-testid="invoice-stamp-past-due"
        aria-hidden="true"
      >
        <span className="invoice-stamp__title">Past Due</span>
        <span className="invoice-stamp__sub">Please Remit Payment</span>
      </div>
    </>
  );
}


/** Derive the stamp status from the ``/invoices/{id}/full`` /
 * ``/invoices/{id}/full-magic`` payload the invoice surfaces fetch.
 *
 *   * ``payment_status`` lowercased to ``"paid"`` → ``"paid"``
 *   * else ``header.due_date`` parses + is strictly before today
 *     (local midnight) → ``"past-due"``
 *   * else → ``null`` (no stamp)
 *
 * Field names match the shape InvoiceView.jsx already reads from
 * (``payment_status`` on the root, ``header.due_date`` on the
 * header sub-object), so this is a drop-in derive with no new
 * backend contract.
 */
export function deriveInvoiceStampStatus(data) {
  if (!data || typeof data !== "object") return null;
  const paid = String(data.payment_status || "").toLowerCase() === "paid";
  if (paid) return "paid";
  const due = data && data.header && data.header.due_date;
  if (!due) return null;
  const dueDate = new Date(due);
  if (Number.isNaN(dueDate.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const dueDay = new Date(dueDate);
  dueDay.setHours(0, 0, 0, 0);
  return dueDay.getTime() < today.getTime() ? "past-due" : null;
}
