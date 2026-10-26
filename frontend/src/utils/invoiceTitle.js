/**
 * TD-invoice-title-display-fallback · Feb-2026 (Ticket E final).
 *
 * Shared "what title do I show for this invoice?" helper used by
 * the three operator-approved surfaces:
 *   1. ``components/customers/CustomerInvoicesTab`` — admin
 *      profile → Invoices tab (Ticket B, already consumes helper)
 *   2. ``components/customers/CustomerInvoiceList`` — admin
 *      profile → Overview tab recent-invoices section
 *   3. ``pages/portal/PortalPages`` — customer portal invoices list
 *
 * Other invoice-title display surfaces across the app
 * (dashboard, dunning, email, SMS, invoice PDF) remain DESCOPED
 * for this ticket per operator instruction.
 *
 * Fallback rule (operator-approved, Ticket FF revised order):
 *
 *   1. ``line_items[0].item_name`` is a non-empty trimmed string
 *      → return it.  This is the canonical "Item" column source
 *      confirmed by both the admin invoice-detail renderer
 *      (``components/invoices/pdfPreviewTiles/LineItemsTile.jsx:68``
 *      reads ``li.item_name``) AND the operator screenshot.
 *   2. ``line_items[0].name`` is a non-empty trimmed string →
 *      return it.  Shorter-schema docs (6% of preview invoices
 *      with line items) use ``name`` instead of ``item_name``.
 *   3. ``invoice.title`` is a non-empty trimmed string → return
 *      it verbatim.  Ticket FF reorder (Feb-2026) pushed this
 *      from case 1 to case 3 so first-line-item-name wins
 *      retroactively, including on imported invoices whose stored
 *      ``title`` is an ``Import #<N>`` artefact.  For invoices
 *      with EMPTY line_items[0].item_name AND .name (the 96%
 *      preview reality), behavior is unchanged — this case
 *      returns ``invoice.title`` just like before.
 *   4. ``line_items[0].description`` is a non-empty trimmed
 *      string → return it TRUNCATED to 60 chars with a trailing
 *      ``"…"``.  This is the primary legacy path — 94% of
 *      preview invoices with line items fill ``description`` but
 *      leave ``item_name`` empty.  Aggressive truncation keeps
 *      row heights consistent AND the ellipsis clearly signals
 *      "this is a description-derived title" to operators
 *      scanning the column.
 *   5. Return ``""`` (blank).  Terminal — no further literal
 *      fallback (no "Invoice", no date-stamped synthesis) per
 *      operator spec.
 *
 * Note on relationship to ``resolvePortalInvoiceTitle``:
 * ``lib/portalInvoiceTitle.js`` handles a DIFFERENT axis — the
 * ``Import #<N>`` rewrite case where ``invoice.title`` IS set
 * but is an ugly import-batch artefact.  This helper handles
 * the "title is missing / empty" axis.  Call sites that use
 * BOTH axes (e.g. ``Import #42`` with no useful line items)
 * should wire the composition explicitly — not consolidated in
 * either helper per TD-94 audit §4.
 *
 * Pure function.  No React / network / DOM dependencies.
 */

const _TRUNCATE_AT = 60;
const _TRUNCATE_SUFFIX = "…";


function _truncate(text) {
  const s = String(text || "").trim();
  if (s.length <= _TRUNCATE_AT) return s;
  // Trim trailing whitespace before the ellipsis so a cut landing
  // mid-word doesn't leave a visible gap.
  return s.slice(0, _TRUNCATE_AT).trimEnd() + _TRUNCATE_SUFFIX;
}


function _nonEmpty(raw) {
  if (raw == null) return "";
  const s = String(raw).trim();
  return s;
}


/**
 * Return a user-facing title string for the given invoice.
 *
 * @param {object} invoice
 * @returns {string}  "" when every fallback is exhausted.
 */
export function getInvoiceDisplayTitle(invoice) {
  if (!invoice || typeof invoice !== "object") return "";

  const items = Array.isArray(invoice.line_items) ? invoice.line_items : [];
  const first = (items.length > 0 && items[0] && typeof items[0] === "object")
    ? items[0] : null;

  if (first) {
    // 1. line_items[0].item_name — canonical "Item" column.
    const itemName = _nonEmpty(first.item_name);
    if (itemName) return itemName;

    // 2. line_items[0].name — shorter-schema fallback (6%).
    const name = _nonEmpty(first.name);
    if (name) return name;
  }

  // 3. invoice.title set → verbatim.
  const title = _nonEmpty(invoice.title);
  if (title) return invoice.title;

  if (first) {
    // 4. line_items[0].description truncated — legacy path (94%).
    const desc = _nonEmpty(first.description);
    if (desc) return _truncate(desc);
  }

  // 5. Terminal — blank.
  return "";
}
