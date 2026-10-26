/**
 * Ticket FF · Feb-2026 — Shared invoice-table primitive.
 *
 * Serves two surfaces today:
 *   * ``components/customers/CustomerInvoicesTab`` — admin profile
 *     → Invoices tab (7 cols incl. Client Name).
 *   * ``pages/portal/PortalInvoices`` — customer portal invoices
 *     list (6 cols, no Client Name).
 *
 * The third invoice-list surface (``pages/invoices/InvoicesList``,
 * the main admin cross-customer list) deliberately does NOT consume
 * this primitive — it carries Phase 34 bulk-select, sortable
 * headers, Phase K47 Viewed indicator, and Card-on-file columns
 * that would be regressed by shoehorning into the shared shape.
 * See Commit E for that surface's light-touch update.
 *
 * Columns are declarative — pass a ``columns`` array in the order
 * you want them rendered.  Each entry is one of the known string
 * tokens: ``"invoice_number" | "customer_name" | "title" | "date" |
 * "amount" | "status" | "actions"``.  Unknown tokens render as a
 * neutral dash cell so a typo doesn't throw.
 *
 * Row click navigates to ``viewHref(invoice)``.  Kebab menu exposes
 * ``View`` + ``Download PDF`` only (operator-locked minimal set;
 * Resend / Mark paid / Delete are deferred to a follow-up ticket).
 *
 * Pure presentation.  Data fetching stays in the caller.  No
 * network calls, no state outside the row-level kebab open flag.
 */
import React from "react";
import { useNavigate } from "react-router-dom";
import { MoreHorizontal, Eye, Download } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { Chip } from "@/components/ui-kit";
import { colors } from "@/theme";
import { getInvoiceDisplayTitle } from "@/utils/invoiceTitle";
import { getInvoiceStatusTone } from "@/utils/invoiceStatusTone";

const DEFAULT_COLS = ["invoice_number", "title", "date", "amount", "status", "actions"];

const COL_LABELS = {
  invoice_number: "Invoice #",
  customer_name:  "Client",
  title:          "Title",
  date:           "Date",
  amount:         "Amount",
  status:         "Status",
  actions:        "",
};

function _formatDate(raw) {
  if (!raw) return "—";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString();
}

function _formatMoney(amount) {
  const n = Number(amount || 0);
  return `$${n.toFixed(2)}`;
}

function _alignFor(col) {
  if (col === "amount" || col === "status" || col === "actions") return "right";
  return "left";
}

/**
 * @param {object} props
 * @param {Array<object>} props.rows             invoices
 * @param {Array<string>} [props.columns]        column order
 * @param {(inv:object)=>string} props.viewHref  row-click + "View" target
 * @param {(inv:object)=>void} [props.onDownloadPdf]  download handler
 * @param {string} [props.testidPrefix]
 */
export default function InvoiceTable({
  rows,
  columns = DEFAULT_COLS,
  viewHref,
  onDownloadPdf,
  testidPrefix = "inv-table",
}) {
  const navigate = useNavigate();
  if (!Array.isArray(rows) || rows.length === 0) return null;

  const handleView = (inv) => {
    const href = viewHref ? viewHref(inv) : null;
    if (href) navigate(href);
  };

  const handleDownload = (inv) => {
    if (onDownloadPdf) {
      onDownloadPdf(inv);
      return;
    }
    // Default — open the magic-link PDF endpoint in a new tab.  Uses
    // the quote PDF route (invoices share the quotes router).
    const url = `/api/quotes/${inv.id}/pdf`;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const renderCell = (col, r) => {
    switch (col) {
      case "invoice_number":
        return <span className="font-mono text-xs" style={{ color: colors.onSurface }}>{r.invoice_number || "—"}</span>;
      case "customer_name":
        return <span style={{ color: colors.onSurface }}>{r.customer_name || "—"}</span>;
      case "title":
        return <span className="font-semibold" style={{ color: colors.onSurface }}>{getInvoiceDisplayTitle(r) || "—"}</span>;
      case "date":
        return <span style={{ color: colors.onSurfaceSecondary }}>{_formatDate(r.invoice_date || r.issued_at || r.created_at)}</span>;
      case "amount":
        return <span className="font-semibold" style={{ color: colors.onSurface }}>{_formatMoney(r.total)}</span>;
      case "status": {
        const { tone, label } = getInvoiceStatusTone(r);
        return <Chip label={label} tone={tone} testid={`${testidPrefix}-status-${r.id}`} />;
      }
      case "actions":
        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label="Row actions"
                data-testid={`${testidPrefix}-actions-${r.id}`}
                className="inline-flex items-center justify-center w-7 h-7 rounded-md hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
                onClick={(e) => e.stopPropagation()}
              >
                <MoreHorizontal size={16} style={{ color: colors.onSurfaceSecondary }} />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onClick={(e) => { e.stopPropagation(); handleView(r); }}
                data-testid={`${testidPrefix}-action-view-${r.id}`}
              >
                <Eye size={14} className="mr-2" /> View
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={(e) => { e.stopPropagation(); handleDownload(r); }}
                data-testid={`${testidPrefix}-action-download-${r.id}`}
              >
                <Download size={14} className="mr-2" /> Download PDF
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        );
      default:
        return <span style={{ color: colors.onSurfaceSecondary }}>—</span>;
    }
  };

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ border: `1px solid ${colors.border}` }}
      data-testid={`${testidPrefix}-wrap`}
    >
      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid={`${testidPrefix}-table`}>
          <thead style={{ backgroundColor: colors.surfaceSecondary }}>
            <tr>
              {columns.map((col) => (
                <th
                  key={col}
                  className={`px-3 py-2 font-semibold ${_alignFor(col) === "right" ? "text-right" : "text-left"}`}
                  style={{ color: colors.onSurfaceSecondary }}
                  data-testid={`${testidPrefix}-col-${col}`}
                >
                  {COL_LABELS[col] ?? ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.id}
                className="cursor-pointer hover:bg-zinc-50"
                style={{ borderTop: `1px solid ${colors.divider}` }}
                onClick={() => handleView(r)}
                data-testid={`${testidPrefix}-row-${r.id}`}
              >
                {columns.map((col) => (
                  <td
                    key={col}
                    className={`px-3 py-2 ${_alignFor(col) === "right" ? "text-right" : "text-left"}`}
                    data-testid={`${testidPrefix}-cell-${col}-${r.id}`}
                    onClick={col === "actions" ? (e) => e.stopPropagation() : undefined}
                  >
                    {renderCell(col, r)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
