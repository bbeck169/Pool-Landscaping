/**
 * TD-71 (web 5baf91f86) + TD-72b (web 106153aa2) — customer-portal
 * invoice/estimate display helpers. Mobile-owned port of web
 * `lib/portalInvoiceTitle.js` — pure functions, same contracts.
 *
 *   resolvePortalInvoiceTitle — rewrites the leaked `Import #<n>`
 *     importer placeholder: service_description / service_summary →
 *     line_items[0].title / .description → notes (trimmed, ≤80 chars +
 *     "…") → neutral "Invoice". Non-placeholder titles pass through.
 *   formatInvoiceCreatedDate — `Created MM/DD/YYYY` from created_at
 *     (fallback invoice_date), device-local tz; "" when unparseable.
 */
const IMPORT_TITLE_RE = /^\s*Import\s*#\s*\d+\s*$/i;

export function isImportedPlaceholderTitle(invoice: any): boolean {
  if (!invoice || typeof invoice !== "object") return false;
  return IMPORT_TITLE_RE.test(String(invoice.title || ""));
}

export function resolvePortalInvoiceTitle(invoice: any): string {
  if (!invoice || typeof invoice !== "object") return "Invoice";
  const originalTitle = invoice.title == null ? "" : String(invoice.title);
  if (!isImportedPlaceholderTitle(invoice)) return originalTitle || "Invoice";
  const svc = String(invoice.service_description || invoice.service_summary || "").trim();
  if (svc) return svc;
  const items = Array.isArray(invoice.line_items) ? invoice.line_items : [];
  if (items.length > 0 && items[0] && typeof items[0] === "object") {
    const li = String(items[0].title || items[0].description || "").trim();
    if (li) return li;
  }
  const notes = String(invoice.notes || "").trim();
  if (notes) return notes.length <= 80 ? notes : notes.slice(0, 80).trimEnd() + "…";
  return "Invoice";
}

export function formatInvoiceCreatedDate(invoice: any): string {
  if (!invoice || typeof invoice !== "object") return "";
  const raw = invoice.created_at || invoice.invoice_date || null;
  if (!raw) return "";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return "";
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `Created ${mm}/${dd}/${d.getFullYear()}`;
}
