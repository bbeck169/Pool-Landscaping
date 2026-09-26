/**
 * QV-ui · Feb-2026 — Shared relative-time formatter.
 *
 * Extracted verbatim from the inline copies previously lived at
 *   • ``frontend/src/components/invoices/InvoiceViewHistory.jsx``
 *   • ``frontend/src/pages/invoices/InvoicesList.jsx``
 *
 * All three call sites (invoice list, invoice view-history card,
 * quote list, quote view-history card) MUST render byte-identical
 * strings so ops has a single mental model — "5s ago", "12m ago",
 * "3h ago", "2d ago", "4mo ago". Any wording change here is a
 * separate commit, per QV-ui dispatch discipline.
 *
 * Contract:
 *   formatRelativeFromIso(iso)                → "Nu ago" | ""
 *   formatRelativeFromIso(null | undefined)   → ""
 *   formatRelativeFromIso(<bad ISO string>)   → ""
 *
 * Second arg (``now``) is an injection point for tests — accepts a
 * ``Date`` or a numeric epoch-millis. In production, callers omit
 * it and the helper reads ``Date.now()``.
 *
 * Bucket boundaries (unchanged from sibling):
 *   • <60s  → "{s}s ago"
 *   • <60m  → "{m}m ago"
 *   • <24h  → "{h}h ago"
 *   • <30d  → "{d}d ago"
 *   • else  → "{mo}mo ago" (30-day months, matches sibling)
 */
export function formatRelativeFromIso(iso, now) {
  if (!iso) return "";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "";
  const nowMs = _coerceNowMs(now);
  const diffSec = Math.max(0, Math.floor((nowMs - ts) / 1000));
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  if (diffD < 30) return `${diffD}d ago`;
  const diffMo = Math.floor(diffD / 30);
  return `${diffMo}mo ago`;
}

/**
 * Local-formatted absolute timestamp — used for ``title=`` hover
 * tooltips next to the relative string. Byte-identical to the
 * ``_fmtLocal`` copy previously living in InvoiceViewHistory.jsx.
 */
export function formatLocalFromIso(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function _coerceNowMs(now) {
  if (now == null) return Date.now();
  if (typeof now === "number") return now;
  if (typeof now.getTime === "function") return now.getTime();
  // Defensive — a mis-typed ``now`` never blanks the render; fall
  // through to real time.
  return Date.now();
}
