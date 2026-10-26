/**
 * Ticket FF · Feb-2026 — Invoice status badge tone mapper.
 *
 * Pure function.  Reads from BOTH ``status`` (document lifecycle:
 * draft / issued / sent / past_due / accepted / declined / paid /
 * partial) AND ``payment_status`` (money flow: unpaid / paid /
 * partial / failed / pending_reconciliation / null) because the
 * operator spec collapses them into one visual badge:
 *
 *   * green  — payment_status === "paid"
 *   * red    — status === "draft"  OR  payment_status === "unpaid"
 *   * neutral — everything else
 *
 * Precedence (operator-locked): ``status === "draft"`` ALWAYS wins
 * red, even if payment_status happens to be "paid" on a draft
 * (shouldn't happen in practice, but defensive).  Then paid-green,
 * then unpaid-red, then neutral.
 *
 * Returns a ``{ tone, label }`` tuple where ``tone`` maps directly
 * onto the shared ``<Chip tone={...}>`` component tokens
 * (``"success"`` / ``"danger"`` / ``"neutral"``).
 */

/**
 * @param {{status?: string|null, payment_status?: string|null}} invoice
 * @returns {{tone: "success"|"danger"|"neutral", label: string}}
 */
export function getInvoiceStatusTone(invoice) {
  const inv = invoice && typeof invoice === "object" ? invoice : {};
  const docStatus = String(inv.status || "").toLowerCase();
  const payStatus = String(inv.payment_status || "").toLowerCase();

  // Draft override — operator spec "red for unpaid AND draft".
  if (docStatus === "draft") {
    return { tone: "danger", label: payStatus || "draft" };
  }
  if (payStatus === "paid") {
    return { tone: "success", label: "paid" };
  }
  if (payStatus === "unpaid") {
    return { tone: "danger", label: "unpaid" };
  }
  // Everything else — partial / failed / pending_reconciliation /
  // null / unknown lifecycle statuses — reads as neutral.
  return { tone: "neutral", label: payStatus || docStatus || "—" };
}
