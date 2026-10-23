/**
 * TD-79 · Feb-2026 — Customer profile Overview tab invoice list.
 *
 * Minimal, admin-only invoice list rendered inside the customer
 * profile Overview tab, between the ``cd-customer-name-secondary``
 * heading and the ``PaymentMethodTiles`` ("payment/card") section.
 *
 * Scope decisions:
 *   * The main ``/invoices`` ``InvoicesList.jsx`` row renderer is
 *     tightly coupled to its bulk-select state + filter chrome
 *     (``selected.has(id)``, bulk checkbox cells, view-count
 *     columns, card-on-file column, action menu).  Extracting
 *     those cells would mean dragging all the shared state
 *     through props — not worth the churn for an inline
 *     Overview-tab section.
 *   * This component mirrors the SAME cell shape (invoice #,
 *     title, due, amount, status badge) using the SAME shared
 *     ``money`` formatter + ``Chip`` status badge so the two
 *     surfaces stay visually locked.
 *   * Title resolution reuses the pure helper
 *     ``resolvePortalInvoiceTitle`` from
 *     ``@/lib/portalInvoiceTitle``. Admin side has no equivalent
 *     resolver and the portal helper is pure (no portal
 *     dependencies) — it rewrites the ``Import #<n>`` artifact
 *     consistently for both customer-facing and admin surfaces.
 *   * TD-79 amendment · Feb-2026 — caps at 10 most recent rows
 *     (newest first by ``created_at``, with ``id`` lex DESC as
 *     the deterministic tiebreak).  No scrollable container
 *     needed at that bound.  When the customer has more than 10
 *     invoices, a "View all" link is rendered that navigates to
 *     ``/invoices?customer_id=<cid>`` — the main InvoicesList
 *     already parses ``?customer_id=`` from the search params
 *     (see line 127 of ``InvoicesList.jsx``) so no main-page
 *     wiring is required.  "View all" is HIDDEN when the count
 *     is ≤10 (everything is already visible — no second page to
 *     link to).
 *   * Data endpoint ``GET /api/quotes?doc_type=invoice`` already
 *     accepts ``customer_id`` + ``limit`` filters (see
 *     ``routers/quotes.py`` lines 262, 294).  When ``limit`` is
 *     passed the response is ``{rows, limit, offset, has_more,
 *     total_count}`` — otherwise a bare array.  We request
 *     ``limit=10`` here and consume the paginated shape so
 *     ``total_count`` drives the "View all" visibility.
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FileText } from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { Chip, EmptyState, Skeleton } from "@/components/ui-kit";
import { resolvePortalInvoiceTitle } from "@/lib/portalInvoiceTitle";
import { getInvoiceDisplayTitle } from "@/utils/invoiceTitle";


const OVERVIEW_INVOICE_CAP = 10;


export function _sortByCreatedDesc(rows) {
  // Newest first by ``created_at`` (same primary sort as
  // ``InvoicesList.jsx``'s default). Falls back to ``id`` lex DESC
  // as the deterministic tiebreak so a bulk-imported batch with
  // identical timestamps stays in a stable order.
  return [...(rows || [])].sort((a, b) => {
    const aT = a?.created_at || "";
    const bT = b?.created_at || "";
    if (aT !== bT) return bT.localeCompare(aT);
    return String(b?.id || "").localeCompare(String(a?.id || ""));
  });
}


export default function CustomerInvoiceList({ customerId }) {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!customerId) return;
    const q =
      `?doc_type=invoice&customer_id=${encodeURIComponent(customerId)}` +
      `&limit=${OVERVIEW_INVOICE_CAP}&offset=0`;
    api
      .get(`/quotes${q}`)
      .then((d) => {
        // When ``limit`` is passed the BE returns the paginated
        // shape ``{rows, total_count, has_more, ...}``. Defensive
        // fallback for the bare-array shape in case a future
        // refactor swaps the contract back.
        if (Array.isArray(d)) {
          const sorted = _sortByCreatedDesc(d);
          setRows(sorted.slice(0, OVERVIEW_INVOICE_CAP));
          setTotal(d.length);
        } else {
          const list = Array.isArray(d?.rows) ? d.rows : [];
          setRows(_sortByCreatedDesc(list).slice(0, OVERVIEW_INVOICE_CAP));
          setTotal(Number(d?.total_count || list.length));
        }
      })
      .catch((e) => {
        setErr(e?.message || "Failed to load invoices.");
        setRows([]);
        setTotal(0);
      });
  }, [customerId]);

  const hasMore = total > OVERVIEW_INVOICE_CAP;

  return (
    <section
      className="rounded-2xl p-4"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="cd-overview-invoices-section"
    >
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold"
          style={{ color: colors.onSurface }}
          data-testid="cd-overview-invoices-header"
        >
          Invoices
          {total > 0 ? (
            <span
              className="ml-2 text-xs font-normal"
              style={{ color: colors.muted }}
              data-testid="cd-overview-invoices-count"
            >
              ({total})
            </span>
          ) : null}
        </h3>
        {hasMore ? (
          <button
            type="button"
            className="text-sm font-semibold hover:underline"
            style={{ color: colors.brand }}
            onClick={() => navigate(`/invoices?customer_id=${encodeURIComponent(customerId)}`)}
            data-testid="cd-overview-invoices-view-all"
          >
            View all →
          </button>
        ) : null}
      </div>

      {rows === null ? (
        <Skeleton style={{ height: 120 }} />
      ) : err ? (
        <div
          className="text-sm px-3 py-2 rounded-lg"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.danger || "#B91C1C" }}
          data-testid="cd-overview-invoices-error"
        >
          {err}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No invoices yet"
          hint="New invoices for this customer will appear here."
          data-testid="cd-overview-invoices-empty"
        />
      ) : (
        <div
          className="rounded-xl overflow-hidden"
          style={{ border: `1px solid ${colors.border}` }}
          data-testid="cd-overview-invoices-table-wrap"
        >
          <table className="w-full text-sm">
            <thead style={{ backgroundColor: colors.surfaceSecondary }}>
              <tr>
                <th className="text-left px-3 py-2 font-semibold"
                     style={{ color: colors.onSurfaceSecondary }}>
                  Invoice #
                </th>
                <th className="text-left px-3 py-2 font-semibold"
                     style={{ color: colors.onSurfaceSecondary }}>
                  Invoice
                </th>
                <th className="text-left px-3 py-2 font-semibold hidden md:table-cell"
                     style={{ color: colors.onSurfaceSecondary }}>
                  Due
                </th>
                <th className="text-right px-3 py-2 font-semibold"
                     style={{ color: colors.onSurfaceSecondary }}>
                  Amount
                </th>
                <th className="text-right px-3 py-2 font-semibold"
                     style={{ color: colors.onSurfaceSecondary }}>
                  Status
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.id}
                  className="cursor-pointer hover:bg-zinc-50"
                  style={{ borderTop: `1px solid ${colors.divider}` }}
                  onClick={() => navigate(`/invoices/${r.id}`)}
                  data-testid={`cd-overview-invoice-row-${r.id}`}
                >
                  <td className="px-3 py-2 font-mono text-xs"
                       style={{ color: colors.onSurface }}>
                    {r.invoice_number || "—"}
                  </td>
                  <td className="px-3 py-2 font-semibold"
                       style={{ color: colors.onSurface }}>
                    {/* Feb-2026 · TD-invoice-title-display-fallback —
                        composes the two orthogonal resolvers:
                        getInvoiceDisplayTitle handles the
                        "title is empty" axis (5-case fallback);
                        resolvePortalInvoiceTitle still handles
                        the "Import #<N>" rewrite case so legacy
                        imported invoices don't surface raw
                        import-batch artefacts.  Order matters:
                        resolve the display source FIRST, then
                        run the import-rewrite over the result. */}
                    {resolvePortalInvoiceTitle({
                      ...r, title: getInvoiceDisplayTitle(r),
                    })}
                  </td>
                  <td className="px-3 py-2 hidden md:table-cell"
                       style={{ color: colors.onSurfaceSecondary }}>
                    {r.due_date || "—"}
                  </td>
                  <td className="px-3 py-2 text-right font-semibold"
                       style={{ color: colors.onSurface }}>
                    {money(r.total)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Chip
                      label={r.payment_status || "unpaid"}
                      tone={(() => {
                        const s = String(r.payment_status || "").toLowerCase();
                        if (s === "paid") return "success";
                        if (s === "overdue") return "danger";
                        if (s === "draft") return "neutral";
                        return "warn";
                      })()}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
