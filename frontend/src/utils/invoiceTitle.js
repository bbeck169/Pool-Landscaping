/**
 * TD-customer-profile-invoices-tab · Feb-2026 — Pre-wire for
 * ``TD-invoice-title-display-fallback`` (Ticket E).
 *
 * Shared "what title do I show for this invoice?" helper used by
 * the customer-profile Invoices tab (this ticket's call site) and
 * — in Ticket E — every other invoice-title display surface
 * across the admin + email + PDF stack.
 *
 * Fallback chain (operator-spec, exact):
 *
 *   1. ``invoice.title`` is a non-empty trimmed string → return
 *      it verbatim.  NO rewriting (that's the ``Import #<N>``
 *      concern owned by ``resolvePortalInvoiceTitle`` in
 *      ``lib/portalInvoiceTitle.js``; this helper is on a
 *      DIFFERENT axis — "no title" vs "title is ugly").
 *
 *   2. Title missing/empty AND ``line_items[0].description`` or
 *      ``line_items[0].title`` is a non-empty trimmed string →
 *      return the first line item's description/title, truncated
 *      to 80 chars with ``…`` (same cap used by
 *      ``resolvePortalInvoiceTitle``'s notes-fallback branch so
 *      the two helpers' truncation stays coherent).
 *
 *   3. Title missing AND no usable line items AND the invoice
 *      carries ANY parseable date (``invoice_date`` ||
 *      ``issued_at`` || ``created_at``, in that priority order
 *      — recon confirmed all three keys appear in different
 *      serializer branches) → return
 *      ``"Invoice — <Month DD, YYYY>"`` formatted via the host
 *      locale.  Uses ``toLocaleDateString("en-US", {month:
 *      "long", day: "numeric", year: "numeric"})`` to match the
 *      ``EstimateFlipbook.jsx:57`` "en-US long month" convention
 *      that's the closest sibling to this surface.
 *
 *   4. Title missing AND no line items AND no parseable date →
 *      return the literal ``"Invoice"``.  Defensive last resort
 *      — the UI must never render an empty string / undefined
 *      where a title belongs.
 *
 * Pure function.  No React / network / DOM dependencies.
 */

const _TRUNCATE_AT = 80;
const _TRUNCATE_SUFFIX = "…";


function _truncateDisplay(text) {
  const s = String(text || "").trim();
  if (s.length <= _TRUNCATE_AT) return s;
  // Trim trailing whitespace before appending the ellipsis so the
  // visible gap stays tight even when the cut lands mid-word.
  return s.slice(0, _TRUNCATE_AT).trimEnd() + _TRUNCATE_SUFFIX;
}


function _formatInvoiceDateLong(raw) {
  if (!raw) return "";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}


/**
 * Return a user-facing title string for the given invoice.
 *
 * @param {object} invoice
 * @returns {string}
 */
export function getInvoiceDisplayTitle(invoice) {
  if (!invoice || typeof invoice !== "object") return "Invoice";

  // 1. Title set → use as-is.
  const title = String(invoice.title == null ? "" : invoice.title).trim();
  if (title) return invoice.title;

  // 2. First usable line-item description / title.
  const items = Array.isArray(invoice.line_items) ? invoice.line_items : [];
  if (items.length > 0 && items[0] && typeof items[0] === "object") {
    const first = items[0];
    const liLabel = String(
      first.description || first.title || "",
    ).trim();
    if (liLabel) return _truncateDisplay(liLabel);
  }

  // 3. Date-stamped fallback — prefer invoice_date, then
  //    issued_at, then created_at (serializer-branch priority
  //    confirmed by recon on the live docs).
  const dateStr = _formatInvoiceDateLong(
    invoice.invoice_date || invoice.issued_at || invoice.created_at || null,
  );
  if (dateStr) return `Invoice — ${dateStr}`;

  // 4. Last-resort literal.
  return "Invoice";
}
