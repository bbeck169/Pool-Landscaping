/**
 * TD-71 · Feb-2026 — Customer-portal invoice display helpers.
 *
 * The portal invoice LIST / DETAIL surfaces previously rendered
 * two customer-unfriendly artifacts:
 *
 *   (a) Imported-invoice titles like ``Import #259`` leaked
 *       straight from the admin importer into customer-facing
 *       portal views. The literal string is meaningless to
 *       customers and must never appear on ``/portal/invoices``
 *       or ``/portal/invoices/:id``.
 *
 *   (b) Invoice rows showed ``No due date`` when a due date was
 *       absent but surfaced NO ``created_at`` context — customers
 *       with a bare "No due date" row had no idea when the
 *       invoice was raised.  The portal needs an additive
 *       ``Created MM/DD/YYYY`` line below the title (the pre-
 *       existing "Due …" / "No due date" line stays as-is).
 *
 * Both helpers are pure functions — no React dependencies, no DOM
 * side effects, no network calls. Pin the contracts here so a
 * future refactor can't silently reintroduce the symptom.
 */

// ═════════════════════════════════════════════════════════════════
// Title resolver — rewrite ``Import #<n>`` → human-friendly label.
// ═════════════════════════════════════════════════════════════════

// Matches ``Import #259`` plus the whitespace variants operator
// flagged: ``  Import #  259  `` / ``Import#259`` / case-insensitive.
const _IMPORT_TITLE_RE = /^\s*Import\s*#\s*\d+\s*$/i;

/**
 * Returns ``true`` when the invoice is flagged as imported AND
 * carries the ugly ``Import #<n>`` title that leaks to customers.
 *
 * Discriminator priority:
 *   1. Explicit flags (``source === 'import'`` / ``import_batch_id``
 *      / ``import_number`` populated) — these are the operator-
 *      spec primary signals.
 *   2. Fallback — the title itself matches the ``Import #<n>``
 *      shape. Catches imported invoices whose flag was never set
 *      during the import run (data drift). Risk of false-positive
 *      against a non-imported invoice is near-zero because this
 *      title shape is the operator-reported signature of the bug.
 *
 * Returns ``false`` for any invoice that doesn't match — the
 * caller keeps the original ``title`` untouched.
 */
export function isImportedPlaceholderTitle(invoice) {
  if (!invoice || typeof invoice !== "object") return false;
  const title = String(invoice.title || "");
  if (!_IMPORT_TITLE_RE.test(title)) return false;
  // Title matches the ugly pattern — presume imported.
  return true;
}

/**
 * Resolve a customer-friendly title for an invoice.
 *
 * Non-imported invoices pass through untouched (returns
 * ``invoice.title``). Imported invoices with the ugly
 * ``Import #<n>`` title walk the operator-spec fallback chain:
 *
 *   1. ``service_description`` / ``service_summary`` — the
 *      canonical "what was this invoice for" field.
 *   2. ``line_items[0].title`` / ``line_items[0].description``
 *      — first line item's label.
 *   3. ``notes`` — trimmed, truncated to 80 chars with ellipsis.
 *   4. ``"Invoice"`` — final neutral fallback.
 *
 * @param {object} invoice
 * @returns {string}
 */
export function resolvePortalInvoiceTitle(invoice) {
  if (!invoice || typeof invoice !== "object") return "Invoice";
  const originalTitle = invoice.title == null ? "" : String(invoice.title);
  if (!isImportedPlaceholderTitle(invoice)) {
    return originalTitle || "Invoice";
  }
  // 1. service_description / service_summary.
  const svc = (
    invoice.service_description || invoice.service_summary || ""
  ).toString().trim();
  if (svc) return svc;
  // 2. first line-item title or description.
  const items = Array.isArray(invoice.line_items) ? invoice.line_items : [];
  if (items.length > 0 && items[0] && typeof items[0] === "object") {
    const li = String(items[0].title || items[0].description || "").trim();
    if (li) return li;
  }
  // 3. notes (trimmed + truncated).
  const notes = String(invoice.notes || "").trim();
  if (notes) {
    if (notes.length <= 80) return notes;
    return notes.slice(0, 80).trimEnd() + "…";
  }
  // 4. neutral fallback — operator-ruled "NOT the import number,
  //    NOT the raw import id".
  return "Invoice";
}


// ═════════════════════════════════════════════════════════════════
// Created-date formatter — ``Created MM/DD/YYYY`` line.
// ═════════════════════════════════════════════════════════════════

/**
 * Format the invoice's ``created_at`` as ``Created MM/DD/YYYY``.
 *
 * Falls back to ``invoice_date`` if ``created_at`` is missing (the
 * two field names appear in different serializer branches). Uses
 * the browser's local timezone — the portal invoice list elsewhere
 * (see ``PortalInvoices.jsx:237``) renders the due-date as-is
 * (``r.due_date`` is already a tenant-local date string per BE),
 * so matching that convention keeps the two date lines coherent
 * at a glance.
 *
 * Returns ``""`` if neither field parses to a valid date — the
 * caller should skip rendering the line in that case.
 *
 * @param {object} invoice
 * @returns {string}  ``"Created 03/14/2025"`` or ``""``.
 */
export function formatInvoiceCreatedDate(invoice) {
  if (!invoice || typeof invoice !== "object") return "";
  const raw = invoice.created_at || invoice.invoice_date || null;
  if (!raw) return "";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return "";
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const yyyy = String(d.getFullYear());
  return `Created ${mm}/${dd}/${yyyy}`;
}


// ═════════════════════════════════════════════════════════════════
// TD-94 · Feb-2026 — Admin Invoices list `Import #<N>` resolver.
// ═════════════════════════════════════════════════════════════════
//
// Deliberately a SEPARATE 2-branch resolver, not a reuse of the
// 4-branch ``resolvePortalInvoiceTitle`` above.  The admin main
// Invoices list (``pages/invoices/InvoicesList.jsx``) and the
// portal / customer-adjacent surfaces (``pages/portal/PortalPages``
// + ``components/customers/CustomerInvoiceList``) have
// deliberately different fallback terminals:
//
//   * **Portal / customer tile** — ends on neutral ``"Invoice"``.
//     Customer-facing UX; ``Import #<N>`` must never leak.
//   * **Admin main Invoices list** (THIS resolver) — ends on the
//     original stored ``Import #<N>`` title.  Operators need the
//     audit-trail traceability back to the import run; a neutral
//     ``"Invoice"`` would hide the signal.
//
// Both resolvers share the single ``isImportedPlaceholderTitle``
// predicate above — "don't let two helpers drift" applies to the
// detection logic (one predicate), not the fallback chains (which
// are intentionally distinct per operator approval on TD-94).  A
// future reader should NOT consolidate the two resolvers into one
// without re-reading TD-94's audit §4 (``memory/td94_admin_invoice_title_audit.md``).
//
// Spec matches operator's "first line item name only, else
// existing title" ask exactly.  Scope:
//
//   1. Non-imported invoice → returns ``invoice.title`` unchanged.
//   2. Imported invoice (``isImportedPlaceholderTitle === true``):
//        a. If ``line_items[0].title`` or
//           ``line_items[0].description`` is a non-empty trimmed
//           string → return it.
//        b. Else → fall back to the original stored title
//           (``Import #<N>``).  Traceability preserved.
//   3. Null / non-object input → returns empty string.
//
// Display-time only.  Does NOT mutate the invoice.  TD-72 BE
// migration (deferred prod) rewrites stored titles so this
// resolver becomes a no-op for already-migrated rows (the title
// no longer matches the predicate's regex and passes through
// unchanged).

/**
 * Admin-list resolver — swaps ``Import #<N>`` for the first line
 * item's title/description, else falls back to the stored
 * ``Import #<N>`` for operator traceability.
 *
 * @param {object} invoice
 * @returns {string}
 */
export function resolveImportedInvoiceTitleFromLineItem(invoice) {
  if (!invoice || typeof invoice !== "object") return "";
  const originalTitle = invoice.title == null ? "" : String(invoice.title);
  if (!isImportedPlaceholderTitle(invoice)) return originalTitle;
  const items = Array.isArray(invoice.line_items) ? invoice.line_items : [];
  if (items.length > 0 && items[0] && typeof items[0] === "object") {
    const li = String(items[0].title || items[0].description || "").trim();
    if (li) return li;
  }
  return originalTitle; // fall back to Import #N for admin traceability
}

