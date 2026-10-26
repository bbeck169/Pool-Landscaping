/**
 * TD-customer-profile-invoices-tab · Feb-2026 — Full invoice list
 * for the Customer admin profile's ``Invoices`` tab.
 *
 * Replaces the ``<EmptyState title="Invoices come in Phase 3"/>``
 * placeholder on ``pages/customers/CustomerDetail.jsx``.
 *
 * Scope / shape decisions
 * -----------------------
 *   * The Overview tab's ``CustomerInvoiceList`` is capped at 10
 *     rows + a "View all →" link.  THIS tab is the dedicated
 *     Invoices surface — no 10-row cap, surface everything the
 *     backend returns for this customer.
 *   * Backend endpoint ``GET /api/quotes?doc_type=invoice&
 *     customer_id=<cid>`` already supports tenant-isolated
 *     filter (``routers/quotes.py:272,506``).  Response shape
 *     depends on whether ``limit`` is passed — we DO pass
 *     ``limit=200`` (generous ceiling; large customers with
 *     more invoices than that are handled by the main
 *     ``/invoices?customer_id=X`` global list — we don't need
 *     to paginate inside this tab for the common case).
 *   * Title column uses ``getInvoiceDisplayTitle`` from
 *     ``@/utils/invoiceTitle`` (Ticket E pre-wire).  Overview
 *     tab's ``CustomerInvoiceList`` uses the OLDER
 *     ``resolvePortalInvoiceTitle`` which handles the
 *     ``Import #<N>`` leak — that's a DIFFERENT axis
 *     ("title is ugly" vs this helper's "title is missing").
 *     Ticket E's sweep will decide composition.  For now, we
 *     use the new helper as spec'd by the operator.
 *   * Visual shape mirrors ``CustomerInvoiceList`` so the two
 *     surfaces stay coherent — same columns, same theme tokens,
 *     same ``Chip`` tone mapping, same row-click to
 *     ``/invoices/${id}``.
 *   * Sort: ``created_at`` DESC with ``id`` lex DESC tiebreak
 *     (matches ``CustomerInvoiceList._sortByCreatedDesc``
 *     verbatim so the two surfaces order identically on the
 *     same data).
 */
import React, { useEffect, useState } from "react";
import { FileText } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { EmptyState, Skeleton } from "@/components/ui-kit";
import InvoiceTable from "@/components/invoices/InvoiceTable";


const TAB_INVOICE_FETCH_LIMIT = 200;


export function _sortByCreatedDesc(rows) {
  // Mirror of ``CustomerInvoiceList._sortByCreatedDesc`` so the
  // Overview tab and this tab sort identically on the same data.
  return [...(rows || [])].sort((a, b) => {
    const aT = a?.created_at || "";
    const bT = b?.created_at || "";
    if (aT !== bT) return bT.localeCompare(aT);
    return String(b?.id || "").localeCompare(String(a?.id || ""));
  });
}


export default function CustomerInvoicesTab({ customerId }) {
  const [rows, setRows] = useState(null);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!customerId) return;
    const q =
      `?doc_type=invoice&customer_id=${encodeURIComponent(customerId)}` +
      `&limit=${TAB_INVOICE_FETCH_LIMIT}&offset=0`;
    api
      .get(`/quotes${q}`)
      .then((d) => {
        if (Array.isArray(d)) {
          const sorted = _sortByCreatedDesc(d);
          setRows(sorted);
          setTotal(d.length);
        } else {
          const list = Array.isArray(d?.rows) ? d.rows : [];
          setRows(_sortByCreatedDesc(list));
          setTotal(Number(d?.total_count || list.length));
        }
      })
      .catch((e) => {
        setErr(e?.message || "Failed to load invoices.");
        setRows([]);
        setTotal(0);
      });
  }, [customerId]);

  return (
    <section
      className="rounded-2xl p-4"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="cd-invoices-tab-section"
    >
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold"
          style={{ color: colors.onSurface }}
          data-testid="cd-invoices-tab-header"
        >
          Invoices
          {total > 0 ? (
            <span
              className="ml-2 text-xs font-normal"
              style={{ color: colors.muted }}
              data-testid="cd-invoices-tab-count"
            >
              ({total})
            </span>
          ) : null}
        </h3>
      </div>

      {rows === null ? (
        <Skeleton
          style={{ height: 160 }}
          data-testid="cd-invoices-tab-loading"
        />
      ) : err ? (
        <div
          className="text-sm px-3 py-2 rounded-lg"
          style={{
            backgroundColor: colors.surfaceSecondary,
            color: colors.danger || "#B91C1C",
          }}
          data-testid="cd-invoices-tab-error"
        >
          {err}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No invoices yet"
          hint="New invoices for this customer will appear here."
          data-testid="cd-invoices-tab-empty"
        />
      ) : (
        <InvoiceTable
          rows={rows}
          columns={["invoice_number", "customer_name", "title", "date", "amount", "status", "actions"]}
          viewHref={(r) => `/invoices/${r.id}`}
          testidPrefix="cd-invoices-tab"
        />
      )}
    </section>
  );
}
