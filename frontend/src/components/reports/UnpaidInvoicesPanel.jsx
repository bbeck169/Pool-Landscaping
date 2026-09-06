import React from "react";
import { Link } from "react-router-dom";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { UnpaidInvoiceReminderButton } from "./UnpaidInvoiceReminderButton";
import { downloadCsv } from "./downloadCsv";
import { downloadServerPdf } from "./downloadServerPdf";
import { formatCurrency } from "./formatters";

function buildQuery(f) {
  const p = new URLSearchParams();
  p.set("period", f.period || "mtd");
  if (f.period === "custom" && f.start && f.end) {
    p.set("start", f.start);
    p.set("end", f.end);
  }
  if (f.service_type) p.set("service_type", f.service_type);
  if (f.tech_id) p.set("tech_id", f.tech_id);
  if (f.customer_id) p.set("customer_id", f.customer_id);
  return p.toString();
}

/**
 * Phase R1.b · Feb-2026 — Unpaid Invoices panel.
 *
 * Table columns:
 *   Customer · Invoice # · Amount · Balance · Age (days overdue)
 *   · Status · Actions ("View" + "Send reminder")
 *
 * ``customerFocusId`` scopes the fetch to a single customer (used
 * by the drill-down affordance in the AR Aging panel above).
 * The parent Financial tab writes it to the URL as
 * ``?customer_id=<id>`` so back-nav preserves the drill-down.
 */
export function UnpaidInvoicesPanel({
  filters,
  customerFocusId,
  onClearFocus,
  testid = "unpaid-invoices-panel",
}) {
  const [state, setState] = React.useState({ loading: true, rows: [] });

  const qs = buildQuery({ ...filters, customer_id: customerFocusId });

  const [pdfBusy, setPdfBusy] = React.useState(false);
  const downloadPdf = async () => {
    if (pdfBusy) return;
    setPdfBusy(true);
    try { await downloadServerPdf(
      `/reports/kpi/unpaid_invoices/export.pdf?${qs}&limit=500`,
      `unpaid-invoices-${filters.period || "mtd"}.pdf`,
    ); }
    catch (e) { toast.error(e?.message || "PDF download failed"); }
    finally { setPdfBusy(false); }
  };

  const refetch = React.useCallback(async () => {
    setState({ loading: true, rows: state.rows || [] });
    try {
      const r = await api.get(`/reports/kpi/unpaid_invoices?${qs}`);
      setState({ loading: false, data: r, rows: r?.rows || [] });
    } catch (e) {
      setState({ loading: false, error: e?.message || "Failed", rows: [] });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qs]);

  React.useEffect(() => { refetch(); }, [refetch]);

  const patchRow = (patched) => {
    setState((prev) => ({
      ...prev,
      rows: (prev.rows || []).map((r) => r.id === patched.id ? { ...r, ...patched } : r),
    }));
  };

  const rows = state.rows;

  const exportCsv = () => {
    const body = rows.map((r) => [
      r.customer_name || "",
      r.invoice_number || "",
      Number(r.total || 0).toFixed(2),
      Number(r.balance || (r.total - r.amount_paid) || 0).toFixed(2),
      Number(r.days_overdue || 0),
      r.status || "",
      r.effective_due_date || "",
    ]);
    downloadCsv(
      `unpaid-invoices-${filters.period || "mtd"}.csv`,
      ["Customer", "Invoice #", "Amount", "Balance", "Days Overdue", "Status", "Effective Due"],
      body,
    );
  };

  return (
    <section className="space-y-4" data-testid={testid}>
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            Unpaid Invoices
          </h2>
          <p className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
            {state.loading ? "Loading…" : state.error ? "Error" : (
              <>
                {rows.length} outstanding
                {typeof state.data?.total === "number"
                  ? ` · ${formatCurrency(state.data.total)} total` : ""}
                {customerFocusId ? " · filtered to one customer" : ""}
              </>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {customerFocusId && onClearFocus ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={onClearFocus}
              data-testid={`${testid}-clear-focus`}
            >
              Clear customer filter
            </Button>
          ) : null}
          <Button
            variant="ghost"
            onClick={exportCsv}
            disabled={state.loading || rows.length === 0}
            data-testid={`${testid}-export`}
          >
            Export CSV
          </Button>
          <Button
            variant="ghost"
            onClick={downloadPdf}
            disabled={pdfBusy}
            data-testid={`${testid}-export-pdf`}
          >
            {pdfBusy ? "Preparing…" : "Download PDF"}
          </Button>
        </div>
      </header>

      <div
        className="rounded-xl border overflow-hidden"
        style={{ backgroundColor: colors.surface, borderColor: colors.border }}
      >
        <table className="w-full text-sm" data-testid={`${testid}-table`}>
          <thead style={{ backgroundColor: colors.surfaceSecondary }}>
            <tr>
              <th className="text-left px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}>Customer</th>
              <th className="text-left px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}>Invoice #</th>
              <th className="text-right px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}>Amount</th>
              <th className="text-right px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}>Balance</th>
              <th className="text-right px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}>Age (days)</th>
              <th className="text-left px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}>Status</th>
              <th className="text-right px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {state.loading ? (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-xs"
                      style={{ color: colors.onSurfaceSecondary }}>Loading…</td></tr>
            ) : state.error ? (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-xs"
                      style={{ color: colors.error }}>{state.error}</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-xs"
                      style={{ color: colors.onSurfaceSecondary }}
                      data-testid={`${testid}-empty`}>
                {customerFocusId ? "This customer has no unpaid invoices" : "All caught up!"}
              </td></tr>
            ) : rows.map((r) => {
              const balance = Number(r.balance ?? (Number(r.total || 0) - Number(r.amount_paid || 0)) ?? 0);
              const partial = !!r.partial;
              const badgeBg = partial ? "#FEF3C7"
                : (r.days_overdue || 0) > 60 ? "#FEE2E2"
                : "#DBEAFE";
              const badgeFg = partial ? colors.warning
                : (r.days_overdue || 0) > 60 ? colors.error
                : colors.brand;
              return (
                <tr key={r.id}
                    style={{ borderTop: `1px solid ${colors.border}` }}
                    data-testid={`${testid}-row-${r.id}`}>
                  <td className="px-3 py-2" style={{ color: colors.onSurface }}>
                    {r.customer_name || "(unnamed)"}
                  </td>
                  <td className="px-3 py-2" style={{ color: colors.onSurfaceSecondary }}>
                    #{r.invoice_number || r.id?.slice(0, 8)}
                    {r.reminder_count > 0 ? (
                      <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded-full"
                            style={{
                              backgroundColor: colors.brandTertiary,
                              color: colors.onBrandTertiary,
                            }}
                            data-testid={`${testid}-reminders-${r.id}`}>
                        {r.reminder_count} reminder{r.reminder_count === 1 ? "" : "s"}
                      </span>
                    ) : null}
                  </td>
                  <td className="text-right px-3 py-2" style={{ color: colors.onSurface }}>
                    {formatCurrency(r.total)}
                  </td>
                  <td className="text-right px-3 py-2 font-semibold" style={{ color: colors.onSurface }}>
                    {formatCurrency(balance)}
                  </td>
                  <td className="text-right px-3 py-2" style={{ color: colors.onSurface }}>
                    {r.days_overdue}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
                      style={{ backgroundColor: badgeBg, color: badgeFg }}
                    >
                      {partial ? "Partial" : (r.days_overdue || 0) > 60 ? "Aged" : "Due"}
                    </span>
                  </td>
                  <td className="text-right px-3 py-2">
                    <div className="inline-flex gap-1.5 items-center">
                      <Link
                        to={`/invoices/${r.id}`}
                        className="text-xs px-2 py-1 rounded border"
                        style={{
                          borderColor: colors.border,
                          color: colors.brand,
                          backgroundColor: colors.surface,
                        }}
                        data-testid={`${testid}-view-${r.id}`}
                      >
                        View
                      </Link>
                      <UnpaidInvoiceReminderButton
                        invoice={r}
                        onSent={patchRow}
                        testid={`${testid}-remind-${r.id}`}
                      />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default UnpaidInvoicesPanel;
