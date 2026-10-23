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
import { useNavigate } from "react-router-dom";
import { FileText } from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { Chip, EmptyState, Skeleton } from "@/components/ui-kit";
import { getInvoiceDisplayTitle } from "@/utils/invoiceTitle";


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


function _statusTone(paymentStatus) {
  const s = String(paymentStatus || "").toLowerCase();
  if (s === "paid") return "success";
  if (s === "overdue") return "danger";
  if (s === "draft") return "neutral";
  return "warn";
}


function _formatRowDate(raw) {
  if (!raw) return "—";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString();
}


export default function CustomerInvoicesTab({ customerId }) {
  const navigate = useNavigate();
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
        <div
          className="rounded-xl overflow-hidden"
          style={{ border: `1px solid ${colors.border}` }}
          data-testid="cd-invoices-tab-table-wrap"
        >
          <table className="w-full text-sm">
            <thead style={{ backgroundColor: colors.surfaceSecondary }}>
              <tr>
                <th
                  className="text-left px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}
                >
                  Invoice #
                </th>
                <th
                  className="text-left px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}
                >
                  Title
                </th>
                <th
                  className="text-left px-3 py-2 font-semibold hidden md:table-cell"
                  style={{ color: colors.onSurfaceSecondary }}
                >
                  Date
                </th>
                <th
                  className="text-right px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}
                >
                  Amount
                </th>
                <th
                  className="text-right px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}
                >
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
                  data-testid={`cd-invoices-tab-row-${r.id}`}
                >
                  <td
                    className="px-3 py-2 font-mono text-xs"
                    style={{ color: colors.onSurface }}
                    data-testid={`cd-invoices-tab-row-number-${r.id}`}
                  >
                    {r.invoice_number || "—"}
                  </td>
                  <td
                    className="px-3 py-2 font-semibold"
                    style={{ color: colors.onSurface }}
                    data-testid={`cd-invoices-tab-row-title-${r.id}`}
                  >
                    {getInvoiceDisplayTitle(r)}
                  </td>
                  <td
                    className="px-3 py-2 hidden md:table-cell"
                    style={{ color: colors.onSurfaceSecondary }}
                    data-testid={`cd-invoices-tab-row-date-${r.id}`}
                  >
                    {_formatRowDate(
                      r.invoice_date || r.issued_at || r.created_at,
                    )}
                  </td>
                  <td
                    className="px-3 py-2 text-right font-semibold"
                    style={{ color: colors.onSurface }}
                    data-testid={`cd-invoices-tab-row-amount-${r.id}`}
                  >
                    {money(r.total)}
                  </td>
                  <td
                    className="px-3 py-2 text-right"
                    data-testid={`cd-invoices-tab-row-status-${r.id}`}
                  >
                    <Chip
                      label={r.payment_status || "unpaid"}
                      tone={_statusTone(r.payment_status)}
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
